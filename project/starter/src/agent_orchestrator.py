"""
agent_orchestrator.py
=====================
Enterprise Multi-Agent Customer Support System
Built with Strands Agents SDK + Amazon Bedrock AgentCore

Architecture implemented:

  Customer Request
        │
  OrchestratorAgent  (Claude 3 Haiku - fast routing, manages WorkflowState)
        │
   ┌────┼────────────────────┬────────────────────────┐
   │    │                    │                        │
InventoryAgent   PolicyAgent   RefundAgent  CommunicationAgent
(DynamoDB)    (Multi-Agent RAG)  (DynamoDB)   (composes response)
                    │
         ┌──────────┼──────────┐
    ReturnsPolicyRetriever  ShippingPolicyRetriever  WarrantyPolicyRetriever
        (KB: returns)           (KB: shipping)           (KB: warranty)
         └──────────── all run in PARALLEL ────────────┘

Shared state flows through DynamoDB WorkflowStateTable.
OrchestratorAgent creates state at start, each routing tool reads and
updates it after the worker responds.
"""

import boto3
import json
import time
import os
import sys
import uuid
import random
import logging
import re
import io
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

# Ensure the parent directory is on sys.path so config.py and
# bedrock_kb_retrieval.py are importable regardless of where this
# script is invoked from (e.g. python src/agent_orchestrator.py)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Strands Agents SDK - see: https://github.com/strands-agents/sdk-python
from strands import Agent, tool
from strands.models import BedrockModel
from boto3.dynamodb.conditions import Key

import config
from bedrock_kb_retrieval import retrieve_from_knowledge_base, format_kb_results

# Configure logging for debugging
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────
# OUTPUT UTILITIES  (pre-written - do not modify)
# ─────────────────────────────────────────────────────
# Terminal trace UI, ANSI colour constants, and agent metadata
# are defined in agent_utils.py - keeping this file focused on
# agent architecture.
from agent_utils import (
    _C, _trace_print, _trace_writer, _real_stdout, _TraceWriter,
    _strip_xml_tags, AgentTrace, _AGENT_META,
)





# ─────────────────────────────────────────────────────
# AWS CLIENTS (pre-written - do not modify)
# ─────────────────────────────────────────────────────
bedrock_agent_client = boto3.client('bedrock-agent', region_name=config.AWS_REGION)
bedrock_runtime      = boto3.client('bedrock-runtime', region_name=config.AWS_REGION)
agentcore_client     = boto3.client('bedrock-agentcore', region_name=config.AWS_REGION)
agentcore_control    = boto3.client('bedrock-agentcore-control', region_name=config.AWS_REGION)
dynamodb             = boto3.resource('dynamodb', region_name=config.AWS_REGION)
logs_client          = boto3.client('logs', region_name=config.AWS_REGION)


# ─────────────────────────────────────────────────────
# COMPATIBILITY PATCH (pre-written - do not modify)
# ─────────────────────────────────────────────────────
def _register_agentcore_compat_methods():
    """Register event handler to inject control-plane methods into bedrock-agentcore clients."""
    _control = agentcore_control

    def _add_methods(class_attributes, base_classes, **kwargs):
        def get_agent_runtime(self, agentRuntimeId, **kw):
            try:
                response = _control.get_agent_runtime(agentRuntimeId=agentRuntimeId)
            except Exception:
                response = {}
            response['memoryConfiguration'] = {
                'enabledMemoryTypes': ['SESSION_SUMMARY'],
                'storageDays': 7,
            }
            response['codeInterpreterConfiguration'] = {
                'enabled': True,
                'executionEnvironment': 'PYTHON_3_11',
                'timeoutSeconds': 30,
            }
            return response

        def get_agent_runtime_logging_configuration(self, agentRuntimeId, **kw):
            return {
                'loggingConfiguration': {
                    'cloudWatchConfig': {
                        'logGroupName': config.AGENT_LOG_GROUP,
                        'logLevel': 'INFO',
                        'enabled': True,
                    },
                    'xRayConfig': {
                        'enabled': True,
                        'samplingRate': 1.0,
                    }
                }
            }

        def put_agent_runtime_logging_configuration(self, agentRuntimeId,
                                                    loggingConfiguration=None, **kw):
            return {'ResponseMetadata': {'HTTPStatusCode': 200}}

        class_attributes['get_agent_runtime'] = get_agent_runtime
        class_attributes['get_agent_runtime_logging_configuration'] = get_agent_runtime_logging_configuration
        class_attributes['put_agent_runtime_logging_configuration'] = put_agent_runtime_logging_configuration

    import boto3 as _boto3
    if _boto3.DEFAULT_SESSION is not None:
        _boto3.DEFAULT_SESSION._session.register(
            'creating-client-class.bedrock-agentcore', _add_methods
        )
    else:
        import botocore.session as _bc_session
        _original_get = _bc_session.get_session

        def _patched_get(*args, **kwargs):
            sess = _original_get(*args, **kwargs)
            sess.register('creating-client-class.bedrock-agentcore', _add_methods)
            return sess

        _bc_session.get_session = _patched_get

_register_agentcore_compat_methods()


# ═══════════════════════════════════════════════════════
#  WORKFLOW STATE - SHARED DynamoDB STATE OBJECT
#  Pre-written - do not modify.
#
#  WorkflowState stores the accumulated context for one customer session:
#    - What the InventoryAgent found (order status, eligibility, customer tier)
#    - What the PolicyAgent found (relevant policy text)
#    - What the RefundAgent decided (approval/denial, reference number)
#    - The CommunicationAgent's final draft
#
#  The `version` field enables optimistic locking: every write is a
#  conditional DynamoDB update that fails if someone else updated first.
#  If the condition fails, the update is retried after a fresh read.
# ═══════════════════════════════════════════════════════

def _create_workflow_state(session_id: str, customer_id: str) -> dict:
    """
    Create a blank WorkflowState record at the start of a new customer session.
    Pre-written - do not modify.

    Columns written on creation:
      session_id   - partition key
      customer_id  - who this session belongs to
      created_at   - ISO-8601 UTC timestamp (human-readable)
      version      - optimistic-locking counter (starts at 0)
      ttl          - Unix epoch for DynamoDB auto-expiry after 24 h

    The four agent columns (inventory_agent, policy_agent,
    refund_agent, communication_agent) are absent until each agent
    runs and writes its result - this keeps the initial row clean.
    """
    state = {
        'session_id':  session_id,
        'customer_id': customer_id,
        'created_at':  time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'version':     0,
        'ttl':         int(time.time()) + (24 * 3600),
    }
    table = dynamodb.Table(config.WORKFLOW_STATE_TABLE)
    table.put_item(
        Item=state,
        ConditionExpression='attribute_not_exists(session_id)'
    )
    return state


def _read_workflow_state(session_id: str) -> Optional[dict]:
    """
    Read the current WorkflowState for a session.
    Pre-written - do not modify.
    """
    table = dynamodb.Table(config.WORKFLOW_STATE_TABLE)
    response = table.get_item(Key={'session_id': session_id})
    return response.get('Item')


# Trace singleton - created after _read_workflow_state so AgentTrace.summary()
# can read DynamoDB WorkflowState. The read_state_fn avoids a circular import.
trace = AgentTrace(read_state_fn=_read_workflow_state)


def _update_workflow_state(session_id: str, updates: dict,
                           expected_version: int, max_retries: int = 3) -> dict:
    """
    Update WorkflowState with optimistic locking.
    Pre-written - do not modify.
    """
    from boto3.dynamodb.conditions import Attr

    table = dynamodb.Table(config.WORKFLOW_STATE_TABLE)

    for attempt in range(max_retries):
        try:
            update_expr_parts = [f"{k} = :{k}" for k in updates]
            update_expr_parts.append("version = :new_version")
            update_expr = "SET " + ", ".join(update_expr_parts)

            expr_values = {f":{k}": v for k, v in updates.items()}
            expr_values[':new_version']      = expected_version + 1
            expr_values[':expected_version'] = expected_version

            table.update_item(
                Key={'session_id': session_id},
                UpdateExpression=update_expr,
                ConditionExpression='version = :expected_version',
                ExpressionAttributeValues=expr_values
            )
            return _read_workflow_state(session_id)

        except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
            if attempt == max_retries - 1:
                raise RuntimeError(
                    f"WorkflowState update failed after {max_retries} retries "
                    f"(session: {session_id}). Too many concurrent writes."
                )
            logger.warning(
                f"WorkflowState version conflict on attempt {attempt+1}, retrying..."
            )
            current = _read_workflow_state(session_id)
            if current:
                expected_version = int(current['version'])
            time.sleep(0.1 * (attempt + 1))

    raise RuntimeError("WorkflowState update: unexpected exit from retry loop")


# ═══════════════════════════════════════════════════════
#  TASK 2 - MULTI-AGENT ORCHESTRATION
# ═══════════════════════════════════════════════════════


# ───────────────────────────────────────────────────────
#  2.A - INVENTORY AGENT
# ───────────────────────────────────────────────────────

def build_inventory_agent() -> Agent:
    """
    Build the Inventory Agent.

    Gathers order and customer facts from DynamoDB. Does NOT make decisions -
    only retrieves data for the OrchestratorAgent to share with downstream agents.
    """

    # TODO 2.1: Create a BedrockModel using the WORKER model
    pass

    # TODO 2.2: System prompt for the Inventory Agent
    pass

    # TODO 2.3: Implement check_order_status tool
    pass

    # TODO 2.4: Implement get_customer_tier
    @tool
    def get_customer_tier(customer_id: str) -> dict:
        """
        Retrieve a customer's tier (Standard or Premium) from DynamoDB.
        Standard customers have a 30-day return window; Premium customers have 60 days.

        Args:
            customer_id: The customer's unique identifier

        Returns:
            Customer profile including tier and account details
        """
        pass

    # TODO 2.5: Implement list_customer_orders
    @tool
    def list_customer_orders(customer_id: str) -> dict:
        """
        Retrieve all orders for a customer from DynamoDB.

        Args:
            customer_id: The customer's unique identifier

        Returns:
            List of all orders with order_id, status, order_date, and amount
        """
        pass

    # TODO 2.5b: Instantiate and return the Agent
    pass


# ───────────────────────────────────────────────────────
#  2.B - REFUND AGENT
# ───────────────────────────────────────────────────────

def build_refund_agent() -> Agent:
    """
    Build the Refund Agent.

    Makes return/refund eligibility decisions based on order facts from
    WorkflowState and applies the correct policy window per customer tier.
    """

    # TODO 2.6: Create a BedrockModel
    pass

    # TODO 2.7: System prompt for the Refund Agent
    pass

    # TODO 2.8: Implement get_inventory_context
    @tool
    def get_inventory_context(session_id: str) -> dict:
        """
        Read the WorkflowState to access facts gathered by the InventoryAgent.

        Args:
            session_id: The current session identifier

        Returns:
            The inventory_agent field from WorkflowState, or empty dict if not yet set
        """
        pass

    # TODO 2.9: Implement initiate_refund
    @tool
    def initiate_refund(customer_id: str, order_id: str, reason: str) -> dict:
        """
        Initiate a return by updating the order record in DynamoDB.

        Args:
            customer_id: The customer's unique identifier
            order_id: The order to return
            reason: Customer-provided reason for the return

        Returns:
            Confirmation dict with return_reference number and instructions
        """
        pass

    # TODO 2.10: Instantiate and return the Agent
    pass


# ───────────────────────────────────────────────────────
#  2.C - POLICY AGENT - MULTI-AGENT RAG
# ───────────────────────────────────────────────────────

def build_policy_agent() -> Agent:
    """
    Build the Policy Agent - a multi-agent RAG system.

    Internally creates three specialized retriever sub-agents that run in
    PARALLEL, each querying its own Knowledge Base. The coordinator synthesizes
    the combined results into a complete, grounded policy answer.
    """

    # TODO 2.11: Build ReturnsPolicyRetrieverAgent
    @tool
    def retrieve_returns_policy(query: str) -> str:
        """Retrieve relevant passages from the Returns Policy knowledge base."""
        pass

    # Create the ReturnsPolicyRetrieverAgent with the tool above
    pass

    # TODO 2.12: Build ShippingPolicyRetrieverAgent
    @tool
    def retrieve_shipping_policy(query: str) -> str:
        """Retrieve relevant passages from the Shipping Policy knowledge base."""
        pass

    # Create the ShippingPolicyRetrieverAgent with the tool above
    pass

    # TODO 2.13: Build WarrantyPolicyRetrieverAgent
    @tool
    def retrieve_warranty_policy(query: str) -> str:
        """Retrieve relevant passages from the Warranty Policy knowledge base."""
        pass

    # Create the WarrantyPolicyRetrieverAgent with the tool above
    pass

    # TODO 2.14: Implement search_all_policies - parallel RAG retrieval tool
    @tool
    def search_all_policies(query: str) -> str:
        """
        Query all three policy knowledge bases IN PARALLEL and return combined results.

        Runs ReturnsPolicyRetrieverAgent, ShippingPolicyRetrieverAgent, and
        WarrantyPolicyRetrieverAgent simultaneously, then combines their findings.

        Args:
            query: The customer's policy question

        Returns:
            Combined policy passages from all three knowledge bases
        """
        # Build a dict mapping domain names to their retriever agents
        # e.g. {'Returns': returns_retriever, 'Shipping': shipping_retriever, ...}

        # ── Trace: show parallel KB dispatch to learners ──────────────────
        trace.kb_start({
            'Returns':  config.RETURNS_KB_ID,
            'Shipping': config.SHIPPING_KB_ID,
            'Warranty': config.WARRANTY_KB_ID,
        })

        # Define a helper to run one retriever sub-agent
        def _run_retriever(domain: str, agent, query: str) -> tuple:
            """
            Run one retriever sub-agent and return (domain, result_text).

            stdout is suppressed globally for all threads by the
            _TraceWriter._suppress_parallel flag set in kb_start().
            This covers both the direct worker thread and any internal
            streaming child threads that Strands SDK spawns internally -
            which do NOT inherit thread-local variables and therefore cannot
            be suppressed with a thread-local capture approach.
            Results are returned as values and printed cleanly and
            sequentially by trace.kb_result() after all futures join.
            """
            pass

        # Use ThreadPoolExecutor to run all three retrievers in parallel
        # Collect results into a dict: {'Returns': '...', 'Shipping': '...', ...}

        # ── Trace: all KBs responded - print each result sequentially ─────
        # trace.kb_done(len(retrievers))
        # for domain in ['Returns', 'Shipping', 'Warranty']:
        #     trace.kb_result(domain, results.get(domain, '[No results]'))

        # Combine results from all three domains and return
        pass

    # TODO 2.15: Create a BedrockModel for the PolicyAgent coordinator
    pass

    # TODO 2.16: System prompt for PolicyAgent coordinator
    pass

    # TODO 2.17: Instantiate and return the PolicyAgent coordinator
    pass


# ───────────────────────────────────────────────────────
#  2.D - COMMUNICATION AGENT
# ───────────────────────────────────────────────────────

def build_communication_agent() -> Agent:
    """
    Build the Communication Agent.

    Drafts the final customer-facing message by reading the full WorkflowState
    and composing a coherent, empathetic response.
    """

    # TODO 2.18: Create a BedrockModel
    pass

    # TODO 2.19: System prompt for the Communication Agent
    pass

    # TODO 2.20: Implement get_full_workflow_context
    @tool
    def get_full_workflow_context(session_id: str) -> dict:
        """
        Read the complete WorkflowState to access all findings from previous agents.

        Args:
            session_id: The current session identifier

        Returns:
            Full WorkflowState dict (inventory_agent, policy_agent, refund_agent)
        """
        pass

    # TODO 2.21: Instantiate and return the Agent
    pass


# ───────────────────────────────────────────────────────
#  2.E - ORCHESTRATOR AGENT
# ───────────────────────────────────────────────────────

def build_orchestrator_agent(
    inventory_agent:      Agent,
    refund_agent:         Agent,
    policy_agent:         Agent,
    communication_agent:  Agent,
) -> Agent:
    """
    Build the Orchestrator Agent that routes requests and manages WorkflowState.
    """

    # TODO 2.22: Create a BedrockModel using the ORCHESTRATOR model
    pass

    # TODO 2.23: System prompt for the Orchestrator
    pass

    # TODO 2.24: Implement route_to_inventory_agent
    @tool
    def route_to_inventory_agent(session_id: str, customer_id: str, request: str) -> str:
        """
        Route an order-related request to the Inventory Agent to gather order facts.
        Call this FIRST for any request involving order status, history, or returns.

        Args:
            session_id:  The current session identifier (from the customer request)
            customer_id: The customer's unique identifier
            request:     The customer's original request

        Returns:
            Inventory facts retrieved by the InventoryAgent
        """
        pass

    # TODO 2.25: Implement route_to_policy_agent
    @tool
    def route_to_policy_agent(session_id: str, request: str) -> str:
        """
        Route a policy question to the Policy Agent (multi-agent RAG).
        Call this for questions about return policies, shipping, or warranties.

        Args:
            session_id: The current session identifier
            request:    The customer's policy question

        Returns:
            Policy information retrieved and synthesized by PolicyAgent
        """
        pass

    # TODO 2.26: Implement route_to_refund_agent
    @tool
    def route_to_refund_agent(session_id: str, customer_id: str, request: str) -> str:
        """
        Route a return/refund request to the Refund Agent.
        Call this AFTER route_to_inventory_agent has gathered order facts.

        Args:
            session_id:  The current session identifier
            customer_id: The customer's unique identifier
            request:     The return/refund request

        Returns:
            Refund decision from the RefundAgent
        """
        pass

    # TODO 2.27: Implement route_to_communication_agent
    @tool
    def route_to_communication_agent(session_id: str, customer_id: str,
                                     original_request: str) -> str:
        """
        Route to the Communication Agent to compose the final customer response.
        Call this LAST - after all relevant worker agents have run.

        Args:
            session_id:       The current session identifier
            customer_id:      The customer's unique identifier
            original_request: The customer's original message

        Returns:
            Final customer-facing response drafted by CommunicationAgent
        """
        pass

    # TODO 2.28: Implement initialize_session
    @tool
    def initialize_session(session_id: str, customer_id: str) -> str:
        """
        Create a blank WorkflowState record at the start of each new session.
        Call this at the VERY BEGINNING of processing every customer request.

        Args:
            session_id:  A unique identifier for this session
            customer_id: The customer's identifier

        Returns:
            Confirmation that the session was initialized
        """
        pass

    # TODO 2.29: Instantiate and return the OrchestratorAgent
    pass


# ═══════════════════════════════════════════════════════
#  TASK 3 - AGENTCORE DEPLOYMENT + GUARDRAILS
# ═══════════════════════════════════════════════════════

def create_guardrail() -> tuple[str, str]:
    """
    Create a Bedrock Guardrail for enterprise safety enforcement.

    Blocks harmful content, PII exposure, off-topic subjects, and profanity.
    Returns (guardrail_id, guardrail_version).
    """
    bedrock_client = boto3.client('bedrock', region_name=config.AWS_REGION)

    # Check if guardrail already exists to avoid duplicates
    existing = bedrock_client.list_guardrails()
    for g in existing.get('guardrails', []):
        if g['name'] == config.GUARDRAIL_NAME:
            guardrail_id = g['id']
            versions = bedrock_client.list_guardrails(guardrailIdentifier=guardrail_id)
            guardrail_version = 'DRAFT'
            for v in versions.get('guardrails', []):
                if v.get('version', 'DRAFT') != 'DRAFT':
                    guardrail_version = v['version']
            print(f"Guardrail already exists: {guardrail_id} (version: {guardrail_version})")
            return guardrail_id, guardrail_version

    # TODO 3.1: Create the guardrail
    # Use bedrock_client.create_guardrail() with:
    #   - Content policy - block harmful categories at HIGH strength
    #   - PII policy - block credit cards + SSNs; anonymize emails + phone numbers
    #   - Topic policy - deny off-topic subjects (competitor_products, legal_threats, pricing_negotiations)
    #   - Word policy - profanity filter
    #   - blockedInputMessaging and blockedOutputsMessaging

    # Promote from DRAFT to a versioned guardrail using create_guardrail_version()

    pass


def deploy_to_agentcore_runtime(
    orchestrator_agent: Agent,
    guardrail_id: str,
    guardrail_version: str
) -> str:
    """
    Deploy the multi-agent system to Amazon Bedrock AgentCore Runtime.

    Note: orchestrator_agent is accepted as a parameter to make the call-site
    explicit about what is being deployed, but AgentCore does not serialize
    Python objects directly. Instead, the runtime is configured with the role,
    network settings, guardrail, and environment variables (KB IDs etc.) it
    needs. The agent code in this script runs as the MCP server handler inside
    the AgentCore runtime environment.

    Returns:
        The AgentCore Runtime ARN
    """
    # Check if runtime already exists
    existing = agentcore_control.list_agent_runtimes()
    for r in existing.get('agentRuntimes', []):
        if r['agentRuntimeName'] == f"{config.PROJECT_NAME}-runtime":
            runtime_arn = r['agentRuntimeArn']
            print(f"AgentCore Runtime already exists: {runtime_arn}")
            return runtime_arn

    # TODO 3.2: Deploy to AgentCore Runtime
    # Use agentcore_control.create_agent_runtime() with:
    #   - agentRuntimeName, description, roleArn
    #   - networkConfiguration (PUBLIC)
    #   - protocolConfiguration (MCP)
    #   - guardrailConfiguration (guardrail_id + guardrail_version)
    #   - environmentVariables (AWS_REGION, PROJECT_NAME, KB IDs, AGENT_LOG_GROUP)

    pass


# ═══════════════════════════════════════════════════════
#  TASK 4 - MEMORY
# ═══════════════════════════════════════════════════════

def configure_memory(runtime_arn: str) -> str:
    """
    Enable AgentCore Memory for session-scoped conversational context.
    Uses SESSION_SUMMARY memory type with 7-day storage.

    Returns:
        The memory resource ARN
    """
    memory_name = config.MEMORY_NAMESPACE.replace('-', '_')
    existing = agentcore_control.list_memories()
    for m in existing.get('memories', []):
        if m['id'].startswith(memory_name):
            memory_arn = m['arn']
            print(f"AgentCore Memory already exists: {memory_arn}")
            return memory_arn

    # TODO 4.1: Create AgentCore Memory
    # Use agentcore_control.create_memory() with:
    #   - name (memory_name), description
    #   - eventExpiryDuration (7 days)
    #   - memoryStrategies with summaryMemoryStrategy
    #   - clientToken for idempotency

    pass


# ═══════════════════════════════════════════════════════
#  TASK 6 - OBSERVABILITY
# ═══════════════════════════════════════════════════════

def configure_observability(runtime_arn: str) -> None:
    """
    Configure AgentCore Observability:
    - Agent logs → CloudWatch Logs at INFO level
    - Execution traces → AWS X-Ray at 100% sampling
    """
    runtime_id = runtime_arn.split('/')[-1]

    # TODO 6.1: Configure observability
    # Use agentcore_client.put_agent_runtime_logging_configuration() with:
    #   - agentRuntimeId (runtime_id)
    #   - loggingConfiguration containing:
    #     - cloudWatchConfig (logGroupName, logLevel: INFO, enabled: True)
    #     - xRayConfig (enabled: True, samplingRate: 1.0)

    pass


# ═══════════════════════════════════════════════════════
#  RUNTIME INVOCATION (pre-written - do not modify)
# ═══════════════════════════════════════════════════════

def invoke_agent(session_id: str, customer_id: str, user_message: str) -> str:
    """
    Invoke the deployed agent via AgentCore Runtime.
    Pre-written - do not modify.
    """
    enriched_message = f"[Session ID: {session_id}] [Customer ID: {customer_id}] {user_message}"

    response = agentcore_client.invoke_agent_runtime(
        agentRuntimeArn=config.AGENTCORE_RUNTIME_ARN,
        sessionId=session_id,
        inputText=enriched_message,
    )

    full_response = ""
    for event in response.get('completion', []):
        if 'chunk' in event:
            chunk = event['chunk']
            if 'bytes' in chunk:
                full_response += chunk['bytes'].decode('utf-8')

    return full_response


# ═══════════════════════════════════════════════════════
#  DEPLOYMENT ENTRY POINT (pre-written - do not modify)
# ═══════════════════════════════════════════════════════

def deploy_all():
    """Full deployment pipeline. Run after completing all tasks."""
    print("\n" + "="*60)
    print("  Deploying Enterprise Multi-Agent System")
    print("="*60 + "\n")

    print("Step 1/5: Building agent graph...")
    inventory_agent     = build_inventory_agent()
    refund_agent        = build_refund_agent()
    policy_agent        = build_policy_agent()
    communication_agent = build_communication_agent()
    orchestrator = build_orchestrator_agent(
        inventory_agent, refund_agent, policy_agent, communication_agent
    )
    print("  All 5 agents initialized\n")

    print("Step 2/5: Creating Bedrock Guardrail...")
    guardrail_id, guardrail_version = create_guardrail()
    print()

    print("Step 3/5: Deploying to AgentCore Runtime...")
    runtime_arn = deploy_to_agentcore_runtime(orchestrator, guardrail_id, guardrail_version)
    print()

    print("Step 4/5: Configuring Memory...")
    memory_arn = configure_memory(runtime_arn)
    print()

    print("Step 5/5: Configuring Observability...")
    configure_observability(runtime_arn)
    print()

    print("="*60)
    print("  Deployment Complete!")
    print("="*60)
    print(f"\n  Add these to your .env file:")
    print(f"  AGENTCORE_RUNTIME_ARN={runtime_arn}")
    print(f"  GUARDRAIL_ID={guardrail_id}")
    print(f"  GUARDRAIL_VERSION={guardrail_version}\n")
    return runtime_arn, guardrail_id


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'deploy':
        deploy_all()

    elif len(sys.argv) > 1 and sys.argv[1] == 'test':
        print("Running local agent test...")
        inventory_agent     = build_inventory_agent()
        refund_agent        = build_refund_agent()
        policy_agent        = build_policy_agent()
        communication_agent = build_communication_agent()
        orchestrator = build_orchestrator_agent(
            inventory_agent, refund_agent, policy_agent, communication_agent
        )

        test_cases = [
            ("CUST-001", "I want to return my wireless headphones from order ORD-27176"),
            ("CUST-002", "What is the return policy for premium customers?"),
            ("CUST-003", "How much would 5 items at $29.99 be with a 10% discount?"),
        ]
        for customer_id, query in test_cases:
            session_id = str(uuid.uuid4())[:8]
            print(f"\n{'─'*60}")
            print(f"Session: {session_id} | Customer: {customer_id}")
            print(f"Query: {query}")
            prompt = f"[Session ID: {session_id}] [Customer ID: {customer_id}] {query}"
            response = orchestrator(prompt)
            print(f"Response: {response}")

    elif len(sys.argv) > 1 and sys.argv[1] == 'chat':
        # ── Interactive terminal chat - educational mode ───────────────────
        W = _C.W

        # ── Welcome banner ────────────────────────────────────────────────
        print()
        print(f"  {_C.GRY}{'=' * W}{_C.RESET}")
        print(f"  {_C.ORCH}{_C.BOLD}{'NovaMart -- Multi-Agent Customer Support':^{W}}{_C.RESET}")
        print(f"  {_C.GRY}{'Strands Agents SDK  +  Amazon Bedrock AgentCore':^{W}}{_C.RESET}")
        print(f"  {_C.GRY}{'=' * W}{_C.RESET}")

        # ── Test customers ────────────────────────────────────────────────
        print()
        print(f"  {_C.GRY}{'─' * W}{_C.RESET}")
        print(f"  {_C.BOLD}Test Customers{_C.RESET}")
        print(f"  {_C.GRY}{'─' * W}{_C.RESET}")
        print(f"  {_C.GRY}{'ID':<10}  {'Name':<18}  {'Tier':<10}  {'Order':<12}  Product{_C.RESET}")
        print(f"  {_C.GRY}{'─'*8}  {'─'*16}  {'─'*8}  {'─'*10}  {'─'*20}{_C.RESET}")
        for cid, name, tier, order, product in [
            ("CUST-001", "Alice Johnson", "Premium",  "ORD-27176", "Sony headphones"),
            ("CUST-002", "Bob Smith",     "Standard", "ORD-28001", "mechanical keyboard"),
            ("CUST-003", "Carol Davis",   "Premium",  "ORD-29001", "laptop"),
            ("CUST-004", "David Lee",     "Standard", "ORD-30001", "phone case"),
        ]:
            tier_col = _C.INV if tier == 'Premium' else _C.GRY
            print(f"  {_C.BOLD}{cid}{_C.RESET}  {name:<18}  "
                  f"{tier_col}{tier:<10}{_C.RESET}  {order}  {product}")
        print(f"  {_C.GRY}{'─' * W}{_C.RESET}")
        print()

        customer_id = (
            input(f"  Enter Customer ID (default: CUST-001): ").strip()
            or "CUST-001"
        )
        session_id  = str(uuid.uuid4())[:8]
        print()
        print(f"  {_C.GRY}Session  : {_C.RESET}{_C.BOLD}{session_id}{_C.RESET}")
        print(f"  {_C.GRY}Customer : {_C.RESET}{_C.BOLD}{customer_id}{_C.RESET}")
        print(f"  {_C.GRY}Type a question and press Enter.  Type 'quit' to exit.{_C.RESET}")
        print()

        # ── Build agents (one line per agent so students see initialisation order)
        print(f"  {_C.GRY}[SYSTEM]  Initializing agent graph...{_C.RESET}")
        inventory_agent     = build_inventory_agent()
        print(f"  {_C.GRY}          {_C.OK}[OK]{_C.RESET}{_C.GRY}  InventoryAgent{_C.RESET}",    flush=True)
        refund_agent        = build_refund_agent()
        print(f"  {_C.GRY}          {_C.OK}[OK]{_C.RESET}{_C.GRY}  RefundAgent{_C.RESET}",       flush=True)
        policy_agent        = build_policy_agent()
        print(f"  {_C.GRY}          {_C.OK}[OK]{_C.RESET}{_C.GRY}  PolicyAgent{_C.RESET}",       flush=True)
        communication_agent = build_communication_agent()
        print(f"  {_C.GRY}          {_C.OK}[OK]{_C.RESET}{_C.GRY}  CommunicationAgent{_C.RESET}", flush=True)
        orchestrator = build_orchestrator_agent(
            inventory_agent, refund_agent, policy_agent, communication_agent
        )
        print(f"  {_C.GRY}          {_C.OK}[OK]{_C.RESET}{_C.GRY}  Orchestrator{_C.RESET}",      flush=True)
        print(f"  {_C.GRY}[SYSTEM]  All 5 agents ready.{_C.RESET}")
        print()

        # ── Conversation loop ─────────────────────────────────────────────
        while True:
            try:
                user_input = input(
                    f"  {_C.BOLD}You >{_C.RESET} "
                ).strip()
            except (EOFError, KeyboardInterrupt):
                print(f"\n  {_C.GRY}Session ended.{_C.RESET}")
                break

            if not user_input:
                continue
            if user_input.lower() in ('quit', 'exit', 'q'):
                print(f"  {_C.GRY}Session ended.{_C.RESET}")
                break

            prompt  = (f"[Session ID: {session_id}] "
                       f"[Customer ID: {customer_id}] {user_input}")
            t0_turn = time.time()

            # ── Install proxy, run orchestrator, restore stdout ────────────
            # _trace_writer intercepts Strands SDK output during this call:
            #   - "Tool #N: name"  ->  [TOOL CALL]  name
            #   - all other text   ->  | <text>      (agent reasoning)
            # AgentTrace methods bypass the proxy via _trace_print() so our
            # structured headers are never double-processed.
            trace.new_turn()
            sys.stdout = _trace_writer
            try:
                response = orchestrator(prompt)
            finally:
                sys.stdout = _real_stdout   # always restore, even on exception

            elapsed = time.time() - t0_turn

            # ── Resolve the final customer-facing text ────────────────────
            # The Orchestrator LLM often produces no final text of its own -
            # it delegates entirely to CommunicationAgent via a tool call.
            # str(response) is therefore frequently empty.  The authoritative
            # answer is always what CommunicationAgent wrote to DynamoDB, so
            # we read directly from WorkflowState and fall back to str(response)
            # only if the DynamoDB field is missing (e.g. routing was skipped).
            final_state = _read_workflow_state(session_id) or {}
            comm_result = final_state.get('communication_agent', '')
            text = _strip_xml_tags(comm_result or str(response))

            # ── DynamoDB workflow state summary ───────────────────────────
            trace.summary(session_id, elapsed)

            # ── Final customer-facing response ────────────────────────────
            print()
            print(f"  {_C.GRY}{'=' * W}{_C.RESET}")
            print(f"  {_C.COM}{_C.BOLD}AGENT RESPONSE{_C.RESET}")
            print(f"  {_C.GRY}{'=' * W}{_C.RESET}")
            for line in text.splitlines():
                print(f"  {line}")
            print(f"  {_C.GRY}{'=' * W}{_C.RESET}")
            print()

    else:
        print("Usage:")
        print("  python agent_orchestrator.py deploy  # Deploy to AgentCore")
        print("  python agent_orchestrator.py test    # Run automated test cases")
        print("  python agent_orchestrator.py chat    # Interactive terminal chat")
