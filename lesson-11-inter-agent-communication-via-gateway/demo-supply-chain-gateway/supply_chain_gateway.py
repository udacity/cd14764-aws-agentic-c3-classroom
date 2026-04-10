"""
supply_chain_gateway.py - DEMO (Instructor-Led)
==============================================================
Module 11 Demo: Connecting Agents to Tools via AgentCore Gateway

Architecture:
    SupplyChainAgent
         │
    ┌────┴─────────────────────────────────────────────────┐
    │  LambdaGateway (AWS Lambda Tool Backends)              │
    │  Routes tool calls to Lambda functions as backends      │
    │  Agent discovers tools via registry at runtime          │
    └────┬──────────────┬──────────────┬──────────────────┘
         │              │              │
    ┌────┴────┐   ┌────┴────┐   ┌────┴──────────┐
    │Inventory│   │Shipping │   │  Supplier     │
    │ Lambda  │   │ Lambda  │   │    Lambda     │
    └─────────┘   └─────────┘   └───────────────┘

Gateway vs @tool:
  @tool: In-process Python functions, fast, tightly coupled
  Gateway: Runtime discovery, loose coupling, network latency

When to use Gateway:
  - Tools are independently deployed services (Lambda, microservices, APIs)
  - You need centralized auth and observability
  - Agents need to discover tools dynamically
  - Different teams manage different tools

Tech Stack:
  - Python 3.11+
  - Strands Agents SDK (Agent class, @tool decorator)
  - Amazon Bedrock (Nova Lite for the agent)
  - AWS Lambda (tool backends via boto3)
  - LambdaGateway (registry pattern for Lambda functions)

Production equivalent: Amazon Bedrock AgentCore Gateway (MCP protocol)
"""

import json
import os
import re
import time
import logging
import boto3
from dotenv import load_dotenv
from strands import Agent, tool
from strands.models import BedrockModel

load_dotenv()
logging.basicConfig(level=logging.WARNING)


def clean_response(text: str) -> str:
    """Strip <thinking>...</thinking> tags from Nova model outputs."""
    return re.sub(r"<thinking>.*?</thinking>\s*", "", str(text), flags=re.DOTALL).strip()


# NOTE: In production, extract shared helpers like run_agent_with_retry() and
# clean_response() to a common utils.py module to avoid code duplication.
def run_agent_with_retry(agent_builder, prompt: str, max_retries: int = 3) -> float:
    """Run an agent with retry logic for transient Bedrock errors.
    Uses exponential backoff (1s, 2s, 4s) to handle throttling."""
    for attempt in range(max_retries):
        try:
            agent = agent_builder()
            t = time.time()
            agent(prompt)
            return time.time() - t
        except Exception as e:
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                print(f"    [Retry {attempt + 1}/{max_retries}] {e.__class__.__name__}, waiting {wait}s...")
                time.sleep(wait)
            else:
                print(f"    [Failed] {e.__class__.__name__} after {max_retries} attempts")
                raise


# ─────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
NOVA_LITE_MODEL = os.environ.get("NOVA_LITE_MODEL", "amazon.nova-lite-v1:0")

# Lambda client for invoking tool backends
lambda_client = boto3.client("lambda", region_name=AWS_REGION)

# Lambda function names (from CloudFormation)
INVENTORY_FUNCTION = os.environ.get("INVENTORY_FUNCTION", "lesson-11-gateway-inventory")
SHIPPING_FUNCTION = os.environ.get("SHIPPING_FUNCTION", "lesson-11-gateway-shipping")
SUPPLIER_FUNCTION = os.environ.get("SUPPLIER_FUNCTION", "lesson-11-gateway-supplier")
QUALITY_INSPECTION_FUNCTION = os.environ.get("QUALITY_INSPECTION_FUNCTION", "lesson-11-gateway-quality-inspection")


# STEP 1: LAMBDA GATEWAY — Routes tool calls to AWS Lambda functions
# Production equivalent: Amazon Bedrock AgentCore Gateway (MCP protocol)

class LambdaGateway:
    """Gateway that routes tool calls to AWS Lambda functions.

    This gateway implements the registration → discovery → invocation pattern
    using AWS Lambda as the tool backend. Each registered tool maps to a
    Lambda function that is invoked via boto3.

    Production: Amazon Bedrock AgentCore Gateway (MCP protocol)
    """

    def __init__(self, name: str, description: str):
        self.gateway_id = f"GW-{name.upper().replace(' ', '-')[:20]}"
        self.name = name
        self.description = description
        self.targets = {}  # name → {description, function_name, target_type}
        self.invocation_log = []

    def register_target(self, name: str, description: str, function_name: str,
                        target_type: str = "lambda"):
        """Register a Lambda function as a gateway target.

        Production: agentcore.create_gateway_target()
        """
        self.targets[name] = {
            "description": description,
            "function_name": function_name,
            "target_type": target_type,
        }

    def discover_tools(self, query: str = None) -> list[dict]:
        """List all registered tools (or filter by query).

        Production: MCP list_tools protocol
        """
        tools = []
        for name, config in self.targets.items():
            if query is None or query.lower() in name.lower() or query.lower() in config["description"].lower():
                tools.append({
                    "name": name,
                    "description": config["description"],
                    "type": config["target_type"],
                })
        return tools

    def invoke_tool(self, tool_name: str, params: dict) -> dict:
        """Invoke a registered tool via Lambda.

        Production: MCP tool invocation protocol
        """
        if tool_name not in self.targets:
            return {"status": "error", "message": f"Tool '{tool_name}' not found in gateway"}

        target = self.targets[tool_name]
        function_name = target["function_name"]

        # Invoke Lambda function
        response = lambda_client.invoke(
            FunctionName=function_name,
            InvocationType="RequestResponse",
            Payload=json.dumps(params),
        )

        result = json.loads(response["Payload"].read().decode("utf-8"))

        self.invocation_log.append({
            "tool": tool_name,
            "function": function_name,
            "params": params,
            "result_status": result.get("status", "unknown"),
            "timestamp": time.time(),
        })

        return result


# Note: Handler functions now live in AWS Lambda (see infrastructure/stack.yaml)
# The data that was previously in-memory is now stored in Lambda functions,
# which are invoked through the gateway's invoke_tool() method.


# STEP 3: AGENT BUILDER — Supply chain agent with Gateway-based tools
def build_supply_chain_agent(gateway: LambdaGateway) -> Agent:
    """Build a supply chain agent connected to the Gateway."""
    # STEP 3.1: BedrockModel — Nova Lite for supply chain reasoning (temperature 0.1)
    model = BedrockModel(model_id=NOVA_LITE_MODEL, region_name=AWS_REGION, temperature=0.1)

    # List available tools from Gateway
    available_tools = gateway.discover_tools()
    tool_list = "\n".join(f"  - {t['name']}: {t['description']}" for t in available_tools)

    # STEP 3.2: System prompt — Supply chain management with dynamic tool discovery
    system_prompt = f"""You are a supply chain management agent. You have access to the following
tools via AgentCore Gateway:

{tool_list}

Use the appropriate tool for each query. Report results concisely.
If a query doesn't match any tool, say so."""

    @tool
    def check_inventory(item_id: str) -> str:
        """
        Check inventory levels for a specific item or list all inventory.

        Args:
            item_id: The item ID to look up (e.g., "WIDGET-001"), or "all" for full inventory

        Returns:
            JSON with inventory data from the Inventory API via Gateway
        """
        result = gateway.invoke_tool("inventory_api", {"item_id": item_id if item_id != "all" else ""})
        return json.dumps(result, indent=2)

    @tool
    def track_shipment(tracking_id: str) -> str:
        """
        Track a shipment status or list all shipments.

        Args:
            tracking_id: The shipment tracking ID (e.g., "SHIP-101"), or "all"

        Returns:
            JSON with shipment data from the Shipping API via Gateway
        """
        result = gateway.invoke_tool("shipping_api", {"tracking_id": tracking_id if tracking_id != "all" else ""})
        return json.dumps(result, indent=2)

    @tool
    def lookup_supplier(supplier_id: str) -> str:
        """
        Look up supplier information or list all suppliers.

        Args:
            supplier_id: The supplier ID (e.g., "SUP-A"), or "all"

        Returns:
            JSON with supplier data from the Supplier API via Gateway
        """
        result = gateway.invoke_tool("supplier_api", {"supplier_id": supplier_id if supplier_id != "all" else ""})
        return json.dumps(result, indent=2)

    @tool
    def inspect_quality(item_id: str) -> str:
        """
        Check quality inspection results for an item.

        Args:
            item_id: The item ID to inspect (e.g., "WIDGET-001"), or "all"

        Returns:
            JSON with inspection data from the Quality Inspection API via Gateway
        """
        result = gateway.invoke_tool("quality_inspection_api",
                                     {"item_id": item_id if item_id != "all" else ""})
        return json.dumps(result, indent=2)

    # STEP 3.3: Build Agent — bind model + prompt + 4 Gateway-based tools
    return Agent(model=model, system_prompt=system_prompt,
                 tools=[check_inventory, track_shipment, lookup_supplier, inspect_quality])


TEST_QUERIES = [
    {
        "query": "Check the inventory level for WIDGET-002 Copper Wire",
        "expected_tool": "inventory_api",
        "description": "Inventory lookup — routes to Inventory API",
    },
    {
        "query": "What is the status of shipment SHIP-102? Is it delayed?",
        "expected_tool": "shipping_api",
        "description": "Shipment tracking — routes to Shipping API",
    },
    {
        "query": "List all available suppliers and their lead times",
        "expected_tool": "supplier_api",
        "description": "Supplier lookup — routes to Supplier API",
    },
    {
        "query": "Check the quality inspection results for WIDGET-002",
        "expected_tool": "quality_inspection_api",
        "description": "Quality check — routes to dynamically added API",
    },
]


# STEP 4: DEMO EXECUTION — Gateway setup and agent queries
def main():
    print("=" * 70)
    print("  AgentCore Gateway Demo — Module 11")
    print("  Agent discovers and invokes tools via Gateway MCP endpoint")
    print("=" * 70)

    # ── Create Gateway ──
    gateway = LambdaGateway(
        name="supply-chain-gateway",
        description="Lambda-backed tool gateway for supply chain operations"
    )
    print(f"\n  Gateway: {gateway.gateway_id}")
    gateway.register_target(
        name="inventory_api",
        description="Check inventory levels, stock counts, and reorder status for warehouse items",
        function_name=INVENTORY_FUNCTION,
    )
    gateway.register_target(
        name="shipping_api",
        description="Track shipment status, ETAs, and delivery confirmations by tracking ID",
        function_name=SHIPPING_FUNCTION,
    )
    gateway.register_target(
        name="supplier_api",
        description="Look up supplier information, ratings, lead times, and minimum order quantities",
        function_name=SUPPLIER_FUNCTION,
    )

    print(f"  Registered 3 targets:")
    for t in gateway.discover_tools():
        print(f"    [{t['type']:8s}] {t['name']}")
    print(f"\n  Adding Quality Inspection API (NO code changes)...")
    gateway.register_target(
        name="quality_inspection_api",
        description="Check quality inspection results, defect rates, and pass/fail status for items",
        function_name=QUALITY_INSPECTION_FUNCTION,
    )
    print(f"  {len(gateway.targets)} tools available:")
    for t in gateway.discover_tools():
        print(f"    [{t['type']:8s}] {t['name']}")
    for i, test in enumerate(TEST_QUERIES):
        print(f"\n{'━' * 70}")
        print(f"  QUERY {i + 1}: \"{test['query']}\"")
        print(f"  Expected tool: {test['expected_tool']}")
        print(f"  {test['description']}")
        print(f"{'━' * 70}")

        elapsed = run_agent_with_retry(
            lambda: build_supply_chain_agent(gateway),
            test["query"]
        )
        print(f"    Time: {elapsed:.1f}s")
    print(f"\n{'═' * 70}")
    print("INVOCATION LOG")
    print(f"{'═' * 70}")
    for entry in gateway.invocation_log:
        print(f"  Tool: {entry['tool']:25s} Lambda: {entry['function']:35s} Status: {entry['result_status']}")


    print(f"\n  Key: 1) PLUGIN ARCH — register APIs 2) DYNAMIC DISCOVERY — no code changes")
    print(f"       3) SEMANTIC ROUTING — agent selects by description 4) MULTI-TEAM APIs\n")


if __name__ == "__main__":
    main()
