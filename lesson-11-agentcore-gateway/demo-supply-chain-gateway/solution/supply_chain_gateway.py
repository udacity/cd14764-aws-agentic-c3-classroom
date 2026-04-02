"""
supply_chain_gateway.py - DEMO (Instructor-Led)
==============================================================
Module 11 Demo: Connecting Agents to Tools via AgentCore Gateway

Architecture:
    SupplyChainAgent
         │
    ┌────┴─────────────────────────────────────────────────┐
    │  AgentCore Gateway (Simulated MCP Endpoint)            │
    │  Converts REST APIs into MCP-compatible tools           │
    │  Agent discovers tools via semantic search at runtime   │
    └────┬──────────────┬──────────────┬──────────────────┘
         │              │              │
    ┌────┴────┐   ┌────┴────┐   ┌────┴──────────┐
    │Inventory│   │Shipping │   │  Supplier     │
    │  API    │   │  API    │   │    API        │
    └─────────┘   └─────────┘   └───────────────┘

Gateway vs @tool:
  @tool: In-process Python functions, fast, tightly coupled
  Gateway: Runtime discovery, loose coupling, network latency

When to use Gateway:
  - Tools are independently deployed services
  - You need centralized auth and observability
  - Agents need to discover tools dynamically
  - Different teams manage different tools

Tech Stack:
  - Python 3.11+
  - Strands Agents SDK (Agent class, @tool decorator)
  - Amazon Bedrock (Nova Lite for the agent)
  - Simulated AgentCore Gateway (in-memory tool registry)
"""

import json
import re
import time
import logging
from strands import Agent, tool
from strands.models import BedrockModel

logging.basicConfig(level=logging.WARNING)


def clean_response(text: str) -> str:
    """Strip <thinking>...</thinking> tags from Nova model outputs."""
    return re.sub(r"<thinking>.*?</thinking>\s*", "", str(text), flags=re.DOTALL).strip()


def run_agent_with_retry(agent_builder, prompt: str, max_retries: int = 3) -> float:
    """Run an agent with retry logic for transient Bedrock errors."""
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
AWS_REGION = "us-east-1"
NOVA_LITE_MODEL = "amazon.nova-lite-v1:0"


# ═══════════════════════════════════════════════════════
# STEP 1: SIMULATED AgentCore GATEWAY
#
# Production equivalent:
#   agentcore = boto3.client('bedrock-agentcore')
#   gateway = agentcore.create_gateway(
#       name='supply-chain-gateway',
#       description='MCP endpoint for supply chain APIs',
#       authorizationConfig={'type': 'OAUTH2', ...}
#   )
#   agentcore.create_gateway_target(
#       gatewayIdentifier=gateway['gatewayId'],
#       name='inventory-api',
#       targetConfiguration={
#           'mcpTargetConfiguration': {
#               'openApiSchema': open('inventory-openapi.json').read(),
#               'lambdaArn': 'arn:aws:lambda:...:inventory-api'
#           }
#       },
#       credentialProviderConfigurations=[{'credentialProviderType': 'GATEWAY_IAM_ROLE'}]
#   )
# ═══════════════════════════════════════════════════════

class SimulatedGateway:
    """
    Simulates AgentCore Gateway — converts APIs into MCP-compatible tools.

    In production, Gateway:
      1. Accepts REST API / Lambda / OpenAPI specs as targets
      2. Auto-generates MCP tool definitions from specs
      3. Provides a single endpoint for agents to discover tools
      4. Handles authentication (inbound OAuth, outbound IAM/API key)
      5. Logs all tool invocations for observability
    """

    def __init__(self, name: str, description: str):
        self.gateway_id = f"gw-{name.lower().replace(' ', '-')[:20]}"
        self.name = name
        self.description = description
        self.targets = {}  # name → target config
        self.invocation_log = []

    def register_target(self, name: str, description: str, target_type: str,
                        handler: callable, openapi_spec: dict = None):
        """
        Register an API as a Gateway target.

        Production: agentcore.create_gateway_target(...)
        """
        self.targets[name] = {
            "name": name,
            "description": description,
            "type": target_type,
            "handler": handler,
            "openapi_spec": openapi_spec,
        }

    def discover_tools(self, query: str = None) -> list[dict]:
        """
        Discover available tools via semantic search.

        Production: Agent connects to Gateway MCP endpoint and
        discovers tools via the MCP list_tools protocol.
        """
        tools = []
        for name, target in self.targets.items():
            tools.append({
                "name": name,
                "description": target["description"],
                "type": target["type"],
            })
        return tools

    def invoke_tool(self, tool_name: str, params: dict) -> dict:
        """Invoke a registered tool through the Gateway."""
        if tool_name not in self.targets:
            return {"error": f"Tool '{tool_name}' not found in Gateway"}

        target = self.targets[tool_name]
        result = target["handler"](params)

        self.invocation_log.append({
            "tool": tool_name,
            "params": params,
            "timestamp": time.time(),
        })

        return result


# ═══════════════════════════════════════════════════════
# STEP 2: SIMULATED REST APIs (Gateway targets)
# ═══════════════════════════════════════════════════════

# ── Inventory API ──
def inventory_api_handler(params: dict) -> dict:
    """Simulated Inventory REST API."""
    inventory = {
        "WIDGET-001": {"name": "Steel Bolts M8", "stock": 15000, "warehouse": "WH-East", "reorder_point": 5000},
        "WIDGET-002": {"name": "Copper Wire 12AWG", "stock": 2000, "warehouse": "WH-West", "reorder_point": 3000},
        "WIDGET-003": {"name": "Aluminum Sheet 2mm", "stock": 8500, "warehouse": "WH-East", "reorder_point": 2000},
    }
    item_id = params.get("item_id", "")
    if item_id in inventory:
        item = inventory[item_id]
        item["needs_reorder"] = item["stock"] < item["reorder_point"]
        return {"status": "ok", "item": item}
    return {"status": "ok", "inventory": list(inventory.values())}


# ── Shipping API ──
def shipping_api_handler(params: dict) -> dict:
    """Simulated Shipping REST API."""
    shipments = {
        "SHIP-101": {"destination": "New York", "status": "in_transit", "eta": "2024-03-15", "carrier": "FedEx"},
        "SHIP-102": {"destination": "Chicago", "status": "delayed", "eta": "2024-03-18", "carrier": "UPS",
                     "delay_reason": "Weather disruption"},
        "SHIP-103": {"destination": "Miami", "status": "delivered", "delivered_at": "2024-03-10", "carrier": "USPS"},
    }
    tracking_id = params.get("tracking_id", "")
    if tracking_id in shipments:
        return {"status": "ok", "shipment": shipments[tracking_id]}
    return {"status": "ok", "all_shipments": list(shipments.values())}


# ── Supplier API ──
def supplier_api_handler(params: dict) -> dict:
    """Simulated Supplier REST API."""
    suppliers = {
        "SUP-A": {"name": "SteelCo Industries", "rating": 4.5, "lead_time_days": 7, "min_order": 1000},
        "SUP-B": {"name": "CopperWire Direct", "rating": 3.8, "lead_time_days": 14, "min_order": 500},
        "SUP-C": {"name": "MetalSheets Global", "rating": 4.2, "lead_time_days": 10, "min_order": 200},
    }
    supplier_id = params.get("supplier_id", "")
    if supplier_id in suppliers:
        return {"status": "ok", "supplier": suppliers[supplier_id]}
    return {"status": "ok", "all_suppliers": list(suppliers.values())}


# ── Quality Inspection API (added dynamically — STEP 5) ──
def quality_inspection_handler(params: dict) -> dict:
    """Simulated Quality Inspection API — added AFTER initial setup."""
    inspections = {
        "WIDGET-001": {"last_inspection": "2024-03-01", "result": "PASS", "defect_rate": 0.02},
        "WIDGET-002": {"last_inspection": "2024-02-28", "result": "FAIL", "defect_rate": 0.08,
                       "issues": ["Insulation thickness below spec"]},
        "WIDGET-003": {"last_inspection": "2024-03-05", "result": "PASS", "defect_rate": 0.01},
    }
    item_id = params.get("item_id", "")
    if item_id in inspections:
        return {"status": "ok", "inspection": inspections[item_id]}
    return {"status": "ok", "all_inspections": list(inspections.values())}


# ═══════════════════════════════════════════════════════
# STEP 3: BUILD THE AGENT WITH GATEWAY TOOLS
# ═══════════════════════════════════════════════════════

def build_supply_chain_agent(gateway: SimulatedGateway) -> Agent:
    """Build a supply chain agent connected to the Gateway."""

    model = BedrockModel(model_id=NOVA_LITE_MODEL, region_name=AWS_REGION, temperature=0.1)

    # List available tools from Gateway
    available_tools = gateway.discover_tools()
    tool_list = "\n".join(f"  - {t['name']}: {t['description']}" for t in available_tools)

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

    return Agent(model=model, system_prompt=system_prompt,
                 tools=[check_inventory, track_shipment, lookup_supplier, inspect_quality])


# ═══════════════════════════════════════════════════════
# TEST QUERIES
# ═══════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("  AgentCore Gateway Demo — Module 11")
    print("  Agent discovers and invokes tools via Gateway MCP endpoint")
    print("=" * 70)

    # ── Create Gateway ──
    gateway = SimulatedGateway(
        name="supply-chain-gateway",
        description="MCP endpoint for supply chain REST APIs"
    )
    print(f"\n  Created Gateway: {gateway.gateway_id}")

    # ── Register 3 initial APIs ──
    gateway.register_target(
        name="inventory_api",
        description="Check inventory levels, stock counts, and reorder status for warehouse items",
        target_type="REST_API",
        handler=inventory_api_handler,
    )
    gateway.register_target(
        name="shipping_api",
        description="Track shipment status, ETAs, and delivery confirmations by tracking ID",
        target_type="REST_API",
        handler=shipping_api_handler,
    )
    gateway.register_target(
        name="supplier_api",
        description="Look up supplier information, ratings, lead times, and minimum order quantities",
        target_type="REST_API",
        handler=supplier_api_handler,
    )

    print(f"  Registered 3 API targets:")
    for t in gateway.discover_tools():
        print(f"    [{t['type']:8s}] {t['name']}: {t['description'][:60]}...")

    # ── Dynamically add a NEW API (no agent code changes!) ──
    print(f"\n  Adding Quality Inspection API to Gateway (NO agent code changes)...")
    gateway.register_target(
        name="quality_inspection_api",
        description="Check quality inspection results, defect rates, and pass/fail status for items",
        target_type="LAMBDA",
        handler=quality_inspection_handler,
    )
    print(f"  Now {len(gateway.targets)} tools available via Gateway:")
    for t in gateway.discover_tools():
        print(f"    [{t['type']:8s}] {t['name']}")

    # ── Run test queries ──
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
        print(f"    Response time: {elapsed:.1f}s")

    # ── Gateway Invocation Log ──
    print(f"\n{'═' * 70}")
    print("  GATEWAY INVOCATION LOG")
    print(f"{'═' * 70}")
    for entry in gateway.invocation_log:
        print(f"  Tool: {entry['tool']:25s} Params: {json.dumps(entry['params'])}")

    # ── Comparison: Gateway vs @tool ──
    print(f"\n{'═' * 70}")
    print("  GATEWAY vs @tool COMPARISON")
    print(f"{'═' * 70}")
    print(f"  {'Feature':<30s} {'@tool (Lessons 1-9)':<25s} {'Gateway (This Lesson)'}")
    print(f"  {'─' * 80}")
    print(f"  {'Coupling':<30s} {'Tight (in-process)':<25s} {'Loose (network call)'}")
    print(f"  {'Discovery':<30s} {'Static (hardcoded)':<25s} {'Dynamic (runtime)'}")
    print(f"  {'Latency':<30s} {'~0ms (function call)':<25s} {'~50-200ms (network)'}")
    print(f"  {'Auth':<30s} {'IAM role (shared)':<25s} {'Inbound OAuth + Outbound IAM'}")
    print(f"  {'Adding new tools':<30s} {'Code change + deploy':<25s} {'Gateway config only'}")
    print(f"  {'Observability':<30s} {'Custom logging':<25s} {'Built-in via Gateway'}")
    print(f"  {'Best for':<30s} {'Tight integration':<25s} {'Multi-team, independent APIs'}")

    print(f"\n  Key Insights:")
    print(f"  1. GATEWAY = PLUGIN ARCHITECTURE — register APIs, agents discover them")
    print(f"  2. DYNAMIC DISCOVERY — Quality Inspection API added with zero agent code changes")
    print(f"  3. SEMANTIC TOOL SELECTION — agent matches query to tool by description")
    print(f"  4. DUAL AUTH — inbound OAuth (agent→Gateway), outbound IAM (Gateway→API)")
    print(f"  5. USE @tool FOR CAPSTONE — tight integration, no network latency")
    print(f"  6. USE GATEWAY FOR ENTERPRISE — independent APIs, multi-team, centralized auth\n")


if __name__ == "__main__":
    main()
