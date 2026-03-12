"""
test_agent.py
=============
Test suite for the Udacity AgentCore Project.

Run after each task to validate your implementation:
  python tests/test_agent.py task2    # Test multi-agent orchestration
  python tests/test_agent.py task3    # Test AgentCore deployment + guardrails
  python tests/test_agent.py task4    # Test memory
  python tests/test_agent.py task5    # Test Bedrock Knowledge Base configuration
  python tests/test_agent.py task6    # Test observability
  python tests/test_agent.py all      # Run all tests

"""

import sys
import os
import json
import time
import boto3
import unittest
from unittest.mock import patch, MagicMock

# Add parent dir to path so we can import student files
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import config

# ─────────────────────────────────────────────────────
# HELPER UTILITIES
# ─────────────────────────────────────────────────────

class Colors:
    GREEN  = '\033[92m'
    RED    = '\033[91m'
    YELLOW = '\033[93m'
    CYAN   = '\033[96m'
    BOLD   = '\033[1m'
    RESET  = '\033[0m'

def passed(msg):
    print(f"  {Colors.GREEN}✓ PASS{Colors.RESET} {msg}")

def failed(msg, detail=""):
    print(f"  {Colors.RED}✗ FAIL{Colors.RESET} {msg}")
    if detail:
        print(f"         {Colors.YELLOW}{detail}{Colors.RESET}")

def header(title):
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'─'*55}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}  {title}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'─'*55}{Colors.RESET}")

score = {'earned': 0, 'possible': 0}

def check(condition, points, pass_msg, fail_msg, detail=""):
    score['possible'] += points
    if condition:
        score['earned'] += points
        passed(f"[+{points}pts] {pass_msg}")
        return True
    else:
        failed(f"[+{points}pts] {fail_msg}", detail)
        return False


# ═══════════════════════════════════════════════════════
#  TASK 2 TESTS - Multi-Agent Orchestration
# ═══════════════════════════════════════════════════════

class TestTask2(unittest.TestCase):

    def setUp(self):
        """Import student's agent_orchestrator module."""
        try:
            import agent_orchestrator as ao
            self.ao = ao
        except ImportError as e:
            self.fail(f"Could not import agent_orchestrator: {e}")

    def _get_model_id(self, agent):
        """Extract the model ID string from a Strands Agent's BedrockModel.

        Strands BedrockModel exposes config as a plain dict via model.config,
        with 'model_id' as a key. Falls back to a direct attribute check for
        future SDK versions.
        """
        model = getattr(agent, 'model', None)
        if model is None:
            return ''
        # Strands stores config as a dict: model.config['model_id']
        cfg = getattr(model, 'config', None)
        if isinstance(cfg, dict):
            val = cfg.get('model_id', '')
            if val:
                return val
        # Fallback: direct attribute (future SDK versions)
        val = getattr(model, 'model_id', '')
        if isinstance(val, str) and val:
            return val
        return ''

    def _get_tool_count(self, agent):
        """Count tools registered on a Strands Agent.

        Strands stores tools in agent.tool_registry (a ToolRegistry object)
        whose inner .registry attribute is a plain dict of {name: tool}.
        """
        tool_registry = getattr(agent, 'tool_registry', None)
        if tool_registry is not None:
            inner = getattr(tool_registry, 'registry', None)
            if isinstance(inner, dict):
                return len(inner)
        return 0

    def test_2_1_inventory_agent_instantiates(self):
        """InventoryAgent should return a Strands Agent object."""
        header("Task 2 - Multi-Agent Orchestration")
        try:
            agent = self.ao.build_inventory_agent()
            check(
                agent is not None,
                5,
                "build_inventory_agent() returns an Agent object",
                "build_inventory_agent() returned None",
                "Ensure you return Agent(...) at the end of the function"
            )
        except Exception as e:
            check(False, 5, "", "build_inventory_agent() raised an exception", str(e))

    def test_2_2_inventory_agent_has_tools(self):
        """InventoryAgent should have exactly 3 tools registered."""
        try:
            agent = self.ao.build_inventory_agent()
            tool_count = self._get_tool_count(agent)
            check(
                tool_count == 3,
                5,
                f"InventoryAgent has 3 tools ({tool_count} found)",
                f"InventoryAgent should have 3 tools, found {tool_count}",
                "Expected: check_order_status, get_customer_tier, list_customer_orders"
            )
        except Exception as e:
            check(False, 5, "", "Error checking InventoryAgent tools", str(e))

    def test_2_3_policy_agent_instantiates(self):
        """PolicyAgent should return a Strands Agent object."""
        try:
            agent = self.ao.build_policy_agent()
            check(
                agent is not None,
                5,
                "build_policy_agent() returns an Agent object",
                "build_policy_agent() returned None"
            )
        except Exception as e:
            check(False, 5, "", "build_policy_agent() raised an exception", str(e))

    def test_2_4_policy_agent_has_tool(self):
        """PolicyAgent should have 1 tool: search_all_policies."""
        try:
            agent = self.ao.build_policy_agent()
            tool_count = self._get_tool_count(agent)
            check(
                tool_count == 1,
                5,
                f"PolicyAgent has 1 tool ({tool_count} found)",
                f"PolicyAgent should have 1 tool, found {tool_count}",
                "Expected: search_all_policies"
            )
        except Exception as e:
            check(False, 5, "", "Error checking PolicyAgent tools", str(e))

    def test_2_5_orchestrator_instantiates(self):
        """OrchestratorAgent should return a Strands Agent object."""
        try:
            inventory  = self.ao.build_inventory_agent()
            refund     = self.ao.build_refund_agent()
            policy     = self.ao.build_policy_agent()
            comm       = self.ao.build_communication_agent()
            orchestrator = self.ao.build_orchestrator_agent(inventory, refund, policy, comm)
            check(
                orchestrator is not None,
                5,
                "build_orchestrator_agent() returns an Agent object",
                "build_orchestrator_agent() returned None"
            )
        except Exception as e:
            check(False, 5, "", "build_orchestrator_agent() raised an exception", str(e))

    def test_2_6_orchestrator_has_routing_tools(self):
        """OrchestratorAgent should have 5 routing tools."""
        try:
            inventory  = self.ao.build_inventory_agent()
            refund     = self.ao.build_refund_agent()
            policy     = self.ao.build_policy_agent()
            comm       = self.ao.build_communication_agent()
            orchestrator = self.ao.build_orchestrator_agent(inventory, refund, policy, comm)
            tool_count = self._get_tool_count(orchestrator)
            check(
                tool_count == 5,
                5,
                f"OrchestratorAgent has 5 routing tools ({tool_count} found)",
                f"OrchestratorAgent should have 5 tools, found {tool_count}",
                "Expected: initialize_session, route_to_inventory_agent, route_to_policy_agent, "
                "route_to_refund_agent, route_to_communication_agent"
            )
        except Exception as e:
            check(False, 5, "", "Error checking OrchestratorAgent tools", str(e))

    def test_2_7_routing_uses_different_models(self):
        """Orchestrator should use Haiku; Workers should use Sonnet."""
        try:
            inventory  = self.ao.build_inventory_agent()
            refund     = self.ao.build_refund_agent()
            policy     = self.ao.build_policy_agent()
            comm       = self.ao.build_communication_agent()
            orchestrator = self.ao.build_orchestrator_agent(inventory, refund, policy, comm)

            orchestrator_model = self._get_model_id(orchestrator)
            inventory_model    = self._get_model_id(inventory)

            uses_haiku  = 'haiku' in orchestrator_model.lower()
            uses_sonnet = 'sonnet' in inventory_model.lower()

            check(
                uses_haiku,
                5,
                "OrchestratorAgent uses Claude 3 Haiku (correct for routing)",
                "OrchestratorAgent should use Claude 3 Haiku (config.ORCHESTRATOR_MODEL_ID)",
                f"Found model: {orchestrator_model}"
            )
            check(
                uses_sonnet,
                5,
                "Worker agents use Claude 3 Sonnet (correct for reasoning)",
                "Worker agents should use Claude 3 Sonnet (config.WORKER_MODEL_ID)",
                f"Found model: {inventory_model}"
            )
        except Exception as e:
            check(False, 10, "", "Error checking model assignments", str(e))


# ═══════════════════════════════════════════════════════
#  TASK 3 TESTS - AgentCore Deployment + Guardrails
# ═══════════════════════════════════════════════════════

class TestTask3(unittest.TestCase):

    def setUp(self):
        self.bedrock = boto3.client('bedrock', region_name=config.AWS_REGION)
        self.agentcore = boto3.client('bedrock-agentcore', region_name=config.AWS_REGION)

    def test_3_1_guardrail_exists(self):
        """A Bedrock Guardrail should exist with the correct name."""
        header("Task 3 - AgentCore Deployment + Guardrails")
        try:
            response = self.bedrock.list_guardrails()
            guardrails = response.get('guardrails', [])
            names = [g['name'] for g in guardrails]
            
            check(
                config.GUARDRAIL_NAME in names,
                10,
                f"Guardrail '{config.GUARDRAIL_NAME}' exists in Bedrock",
                f"Guardrail '{config.GUARDRAIL_NAME}' not found",
                f"Found guardrails: {names}"
            )
        except Exception as e:
            check(False, 10, "", "Error checking guardrail", str(e))

    def test_3_2_guardrail_has_required_policies(self):
        """Guardrail should have content, PII, and topic policies."""
        try:
            guardrail_id = config.GUARDRAIL_ID
            if not guardrail_id:
                check(False, 5, "", "GUARDRAIL_ID not set in environment",
                      "Add GUARDRAIL_ID to your .env file (printed by the deploy command)")
                return
            
            response = self.bedrock.get_guardrail(
                guardrailIdentifier=guardrail_id,
                guardrailVersion=config.GUARDRAIL_VERSION
            )
            
            has_content = 'contentPolicy' in response
            has_pii     = 'sensitiveInformationPolicy' in response
            has_topics  = 'topicPolicy' in response
            
            check(
                has_content and has_pii and has_topics,
                5,
                "Guardrail has content, PII, and topic policies",
                "Guardrail is missing required policies",
                f"content={has_content}, PII={has_pii}, topics={has_topics}"
            )
        except Exception as e:
            check(False, 5, "", "Error validating guardrail policies", str(e))

    def test_3_3_agentcore_runtime_exists(self):
        """AgentCore Runtime should be deployed."""
        try:
            runtime_arn = config.AGENTCORE_RUNTIME_ARN
            check(
                bool(runtime_arn),
                5,
                "AGENTCORE_RUNTIME_ARN is set in environment",
                "AGENTCORE_RUNTIME_ARN is not set",
                "Run deploy command then add AGENTCORE_RUNTIME_ARN to your .env file"
            )
        except Exception as e:
            check(False, 5, "", "Error checking runtime ARN", str(e))


# ═══════════════════════════════════════════════════════
#  TASK 4 TESTS - Memory
# ═══════════════════════════════════════════════════════

class TestTask4(unittest.TestCase):

    def setUp(self):
        self.agentcore = boto3.client('bedrock-agentcore', region_name=config.AWS_REGION)

    def test_4_1_memory_is_configured(self):
        """AgentCore Memory should be enabled on the runtime."""
        header("Task 4 - Memory")
        try:
            runtime_arn = config.AGENTCORE_RUNTIME_ARN
            if not runtime_arn:
                check(False, 15, "", "AGENTCORE_RUNTIME_ARN not set - complete Task 3 first")
                return

            runtime_id = runtime_arn.split('/')[-1]
            response = self.agentcore.get_agent_runtime(agentRuntimeId=runtime_id)

            memory_config = response.get('memoryConfiguration', {})
            memory_enabled = 'SESSION_SUMMARY' in memory_config.get('enabledMemoryTypes', [])

            check(
                memory_enabled,
                15,
                "AgentCore Memory is enabled (SESSION_SUMMARY type)",
                "AgentCore Memory is not enabled on the runtime",
                f"Found memoryConfiguration: {memory_config}"
            )
        except Exception as e:
            check(False, 15, "", "Error checking memory configuration", str(e))


# ═══════════════════════════════════════════════════════
#  TASK 5 TESTS - Bedrock Knowledge Bases
# ═══════════════════════════════════════════════════════

class TestTask5(unittest.TestCase):

    def setUp(self):
        self.bedrock_agent = boto3.client('bedrock-agent', region_name=config.AWS_REGION)

    def test_5_1_returns_kb_configured(self):
        """RETURNS_KB_ID should be set and the Knowledge Base should be active."""
        header("Task 5 - Bedrock Knowledge Bases")
        kb_id = config.RETURNS_KB_ID
        check(
            bool(kb_id),
            8,
            f"RETURNS_KB_ID is set in environment ({kb_id})",
            "RETURNS_KB_ID is not set - create the Returns Knowledge Base in AWS Console and add the ID to .env"
        )
        if kb_id:
            try:
                response = self.bedrock_agent.get_knowledge_base(knowledgeBaseId=kb_id)
                status = response.get('knowledgeBase', {}).get('status', 'UNKNOWN')
                check(
                    status == 'ACTIVE',
                    0,
                    f"Returns Knowledge Base is ACTIVE",
                    f"Returns Knowledge Base status is {status} - sync the data source in AWS Console"
                )
            except Exception as e:
                check(False, 0, "", f"Error verifying Returns KB: {e}")

    def test_5_2_shipping_kb_configured(self):
        """SHIPPING_KB_ID should be set and the Knowledge Base should be active."""
        kb_id = config.SHIPPING_KB_ID
        check(
            bool(kb_id),
            8,
            f"SHIPPING_KB_ID is set in environment ({kb_id})",
            "SHIPPING_KB_ID is not set - create the Shipping Knowledge Base in AWS Console and add the ID to .env"
        )
        if kb_id:
            try:
                response = self.bedrock_agent.get_knowledge_base(knowledgeBaseId=kb_id)
                status = response.get('knowledgeBase', {}).get('status', 'UNKNOWN')
                check(
                    status == 'ACTIVE',
                    0,
                    f"Shipping Knowledge Base is ACTIVE",
                    f"Shipping Knowledge Base status is {status} - sync the data source in AWS Console"
                )
            except Exception as e:
                check(False, 0, "", f"Error verifying Shipping KB: {e}")

    def test_5_3_warranty_kb_configured(self):
        """WARRANTY_KB_ID should be set and the Knowledge Base should be active."""
        kb_id = config.WARRANTY_KB_ID
        check(
            bool(kb_id),
            9,
            f"WARRANTY_KB_ID is set in environment ({kb_id})",
            "WARRANTY_KB_ID is not set - create the Warranty Knowledge Base in AWS Console and add the ID to .env"
        )
        if kb_id:
            try:
                response = self.bedrock_agent.get_knowledge_base(knowledgeBaseId=kb_id)
                status = response.get('knowledgeBase', {}).get('status', 'UNKNOWN')
                check(
                    status == 'ACTIVE',
                    0,
                    f"Warranty Knowledge Base is ACTIVE",
                    f"Warranty Knowledge Base status is {status} - sync the data source in AWS Console"
                )
            except Exception as e:
                check(False, 0, "", f"Error verifying Warranty KB: {e}")


# ═══════════════════════════════════════════════════════
#  TASK 6 TESTS - Observability
# ═══════════════════════════════════════════════════════

class TestTask6(unittest.TestCase):

    def setUp(self):
        self.agentcore = boto3.client('bedrock-agentcore', region_name=config.AWS_REGION)
        self.logs = boto3.client('logs', region_name=config.AWS_REGION)

    def test_6_1_cloudwatch_logging_enabled(self):
        """CloudWatch logging should be enabled for the runtime."""
        header("Task 6 - Observability")
        try:
            runtime_arn = config.AGENTCORE_RUNTIME_ARN
            if not runtime_arn:
                check(False, 10, "", "AGENTCORE_RUNTIME_ARN not set - complete Task 3 first")
                return
            
            runtime_id = runtime_arn.split('/')[-1]
            response = self.agentcore.get_agent_runtime_logging_configuration(
                agentRuntimeId=runtime_id
            )
            
            cw_config = response.get('loggingConfiguration', {}).get('cloudWatchConfig', {})
            cw_enabled = cw_config.get('enabled', False)
            
            check(
                cw_enabled,
                10,
                "CloudWatch logging is enabled for the AgentCore runtime",
                "CloudWatch logging is not enabled",
                f"Found config: {cw_config}"
            )
        except Exception as e:
            check(False, 10, "", "Error checking CloudWatch config", str(e))

    def test_6_2_xray_tracing_enabled(self):
        """X-Ray tracing should be enabled for the runtime."""
        try:
            runtime_arn = config.AGENTCORE_RUNTIME_ARN
            if not runtime_arn:
                check(False, 10, "", "AGENTCORE_RUNTIME_ARN not set")
                return
            
            runtime_id = runtime_arn.split('/')[-1]
            response = self.agentcore.get_agent_runtime_logging_configuration(
                agentRuntimeId=runtime_id
            )
            
            xray_config = response.get('loggingConfiguration', {}).get('xRayConfig', {})
            xray_enabled = xray_config.get('enabled', False)
            
            check(
                xray_enabled,
                10,
                "X-Ray tracing is enabled for the AgentCore runtime",
                "X-Ray tracing is not enabled",
                f"Found config: {xray_config}"
            )
        except Exception as e:
            check(False, 10, "", "Error checking X-Ray config", str(e))


# ═══════════════════════════════════════════════════════
#  RUNNER
# ═══════════════════════════════════════════════════════

TASK_SUITES = {
    'task2': TestTask2,
    'task3': TestTask3,
    'task4': TestTask4,
    'task5': TestTask5,
    'task6': TestTask6,
}

def run_task(task_name: str):
    suite = unittest.TestLoader().loadTestsFromTestCase(TASK_SUITES[task_name])
    unittest.TextTestRunner(verbosity=0, stream=open(os.devnull, 'w', encoding='utf-8')).run(suite)

def print_score():
    print(f"\n{'═'*55}")
    pct = (score['earned'] / score['possible'] * 100) if score['possible'] > 0 else 0
    color = Colors.GREEN if pct >= 70 else Colors.YELLOW if pct >= 50 else Colors.RED
    print(f"  {Colors.BOLD}Score: {color}{score['earned']}/{score['possible']} pts ({pct:.0f}%){Colors.RESET}")
    print(f"{'═'*55}\n")


if __name__ == '__main__':
    arg = sys.argv[1] if len(sys.argv) > 1 else 'all'
    
    if arg == 'all':
        tasks = ['task2', 'task3', 'task4', 'task5', 'task6']
    elif arg in TASK_SUITES:
        tasks = [arg]
    else:
        print(f"Unknown argument: {arg}")
        print(f"Usage: python test_agent.py [{'|'.join(TASK_SUITES.keys())}|all]")
        sys.exit(1)
    
    for task in tasks:
        run_task(task)
    
    print_score()
    
    if score['earned'] == score['possible']:
        print(f"  {Colors.GREEN}{Colors.BOLD}🎉 Perfect score! All tasks complete.{Colors.RESET}")
    elif score['earned'] >= score['possible'] * 0.7:
        print(f"  {Colors.YELLOW}{Colors.BOLD}Good progress! Review failed checks above.{Colors.RESET}")
    else:
        print(f"  {Colors.RED}Keep going - re-read the TODO comments carefully.{Colors.RESET}")
    print()
