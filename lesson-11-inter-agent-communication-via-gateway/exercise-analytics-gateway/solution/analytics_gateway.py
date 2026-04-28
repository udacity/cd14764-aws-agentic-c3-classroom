"""
analytics_gateway.py - EXERCISE SOLUTION (Student-Led)
==============================================================
Module 11 Exercise: Register and Invoke Tools through AgentCore Gateway

Architecture:
    AnalyticsAgent
         │
    ┌────┴─────────────────────────────────────────────────┐
    │  LambdaGateway (AWS Lambda Tool Backends)              │
    │  3 registered targets: 2 Lambda + 1 REST API           │
    └────┬──────────────┬──────────────┬──────────────────┘
         │              │              │
    ┌────┴────┐   ┌────┴────┐   ┌────┴──────────┐
    │Weather  │   │Currency │   │  News         │
    │ Lambda  │   │ Lambda  │   │   Lambda      │
    └─────────┘   └─────────┘   └───────────────┘

Same Gateway pattern as the demo (supply_chain_gateway.py),
with additions:
  1. MIXED FUNCTIONALITY: 2 analytical tools + 1 news tool
  2. DIFFERENT DOMAIN: Analytics utilities instead of supply chain
  3. SEMANTIC ROUTING FOCUS: Agent must select correct tool by query semantics

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
WEATHER_FUNCTION = os.environ.get("WEATHER_FUNCTION", "lesson-11-gateway-weather")
CURRENCY_FUNCTION = os.environ.get("CURRENCY_FUNCTION", "lesson-11-gateway-currency")
NEWS_FUNCTION = os.environ.get("NEWS_FUNCTION", "lesson-11-gateway-news")
STOCK_PRICE_FUNCTION = os.environ.get("STOCK_PRICE_FUNCTION", "lesson-11-gateway-stock-price")


# LAMBDA GATEWAY
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
        """Register a Lambda function as a gateway target."""
        self.targets[name] = {
            "description": description,
            "function_name": function_name,
            "target_type": target_type,
        }

    def discover_tools(self, query: str = None) -> list[dict]:
        """List all registered tools (or filter by query)."""
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
        """Invoke a registered tool via Lambda."""
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


# AGENTCORE GATEWAY API — Production equivalent of LambdaGateway
# In production, replace LambdaGateway with Amazon Bedrock AgentCore Gateway.

def _get_function_arn(function_name: str) -> str:
    """Resolve a Lambda function name to its full ARN."""
    resp = lambda_client.get_function(FunctionName=function_name)
    return resp["Configuration"]["FunctionArn"]


def create_agentcore_gateway(role_arn: str) -> dict:
    """Create a real AgentCore Gateway and register the analytics Lambda targets.

    Production equivalent of:
        gateway = LambdaGateway(...)
        gateway.register_target(...)

    Args:
        role_arn: IAM role ARN that AgentCore uses to invoke the Lambda functions.

    Returns:
        dict with gateway_id, gateway_url, and status.
    """
    agentcore = boto3.client("bedrock-agentcore-control", region_name=AWS_REGION)

    # create_gateway: managed MCP endpoint, open auth for lab
    print("  Calling create_gateway...")
    gw = agentcore.create_gateway(
        name="analytics-gateway",
        roleArn=role_arn,
        protocolType="MCP",
        authorizerType="NONE",
        protocolConfiguration={
            "mcp": {
                "instructions": (
                    "Analytics tool gateway. "
                    "Provides weather, currency conversion, and news tools."
                ),
                "searchType": "SEMANTIC",
            }
        },
    )
    gateway_id = gw["gatewayId"]
    print(f"    Gateway ID  : {gateway_id}")
    print(f"    Gateway URL : {gw['gatewayUrl']}")
    print(f"    Status      : {gw['status']}")

    # create_gateway_target: one call per Lambda backend
    targets = [
        {
            "name": "weather_lambda",
            "description": "Look up current weather conditions for a given city including temperature, humidity, and wind",
            "function": WEATHER_FUNCTION,
            "tool_name": "get_weather",
            "tool_description": "Get current weather conditions for a city",
            "param_name": "city",
            "param_desc": "City name (e.g. Tokyo, London, New York)",
        },
        {
            "name": "currency_lambda",
            "description": "Convert amounts between currencies using real-time exchange rates",
            "function": CURRENCY_FUNCTION,
            "tool_name": "convert_currency",
            "tool_description": "Convert an amount from one currency to another",
            "param_name": "amount",
            "param_desc": "Amount to convert as a number",
        },
        {
            "name": "news_api",
            "description": "Get latest news headlines by topic including AI, finance, and technology",
            "function": NEWS_FUNCTION,
            "tool_name": "get_news",
            "tool_description": "Get latest news headlines for a topic",
            "param_name": "topic",
            "param_desc": "News topic (e.g. ai, finance, technology)",
        },
    ]

    print(f"\n  Registering {len(targets)} Gateway targets...")
    for t in targets:
        lambda_arn = _get_function_arn(t["function"])
        resp = agentcore.create_gateway_target(
            gatewayIdentifier=gateway_id,
            name=t["name"],
            description=t["description"],
            targetConfiguration={
                "mcp": {
                    "lambda": {
                        "lambdaArn": lambda_arn,
                        "toolSchema": {
                            "inlinePayload": [
                                {
                                    "name": t["tool_name"],
                                    "description": t["tool_description"],
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {
                                            t["param_name"]: {
                                                "type": "string",
                                                "description": t["param_desc"],
                                            }
                                        },
                                        "required": [t["param_name"]],
                                    },
                                }
                            ]
                        },
                    }
                }
            },
            credentialProviderConfigurations=[
                {"credentialProviderType": "GATEWAY_IAM_ROLE"}
            ],
        )
        print(f"    [{resp['status']:12s}] {t['name']} → target {resp['targetId']}")

    return {
        "gateway_id": gateway_id,
        "gateway_url": gw["gatewayUrl"],
        "status": gw["status"],
    }


def build_analytics_agent(gateway: LambdaGateway) -> Agent:
    """Build an analytics agent connected to the Gateway."""

    model = BedrockModel(model_id=NOVA_LITE_MODEL, region_name=AWS_REGION, temperature=0.1)

    available_tools = gateway.discover_tools()
    tool_list = "\n".join(f"  - {t['name']}: {t['description']}" for t in available_tools)

    system_prompt = f"""You are a data analytics agent. You have access to the following
tools via AgentCore Gateway:

{tool_list}

Use the appropriate tool for each query. Report results concisely."""

    @tool
    def get_weather(city: str) -> str:
        """
        Look up current weather conditions for a city.

        Args:
            city: City name (e.g., "Tokyo", "London", "New York")

        Returns:
            JSON with temperature, conditions, humidity, wind
        """
        result = gateway.invoke_tool("weather_lambda", {"city": city})
        return json.dumps(result, indent=2)

    @tool
    def convert_currency(amount: float, from_currency: str, to_currency: str) -> str:
        """
        Convert an amount between currencies using real-time exchange rates.

        Args:
            amount: The amount to convert
            from_currency: Source currency code (e.g., "USD")
            to_currency: Target currency code (e.g., "EUR")

        Returns:
            JSON with conversion result and exchange rate
        """
        result = gateway.invoke_tool("currency_lambda", {
            "amount": amount, "from": from_currency, "to": to_currency
        })
        return json.dumps(result, indent=2)

    @tool
    def get_news(topic: str) -> str:
        """
        Get latest news headlines by topic.

        Args:
            topic: News topic (e.g., "ai", "finance", "technology")

        Returns:
            JSON with headline titles and sources
        """
        result = gateway.invoke_tool("news_api", {"topic": topic})
        return json.dumps(result, indent=2)

    @tool
    def stock_price(symbol: str) -> str:
        """
        Get the current stock price for a ticker symbol.

        Args:
            symbol: Stock ticker symbol (e.g., "AMZN", "GOOG", "AAPL", "MSFT", "NVDA")

        Returns:
            JSON with price, daily change, and company name
        """
        result = gateway.invoke_tool("stock_price", {"symbol": symbol})
        return json.dumps(result, indent=2)

    return Agent(model=model, system_prompt=system_prompt,
                 tools=[get_weather, convert_currency, get_news, stock_price])


TEST_QUERIES = [
    {
        "query": "What is the weather in Tokyo right now?",
        "expected_tool": "weather_lambda",
        "description": "Weather lookup — routes to Weather Lambda",
    },
    {
        "query": "Convert 500 USD to EUR",
        "expected_tool": "currency_lambda",
        "description": "Currency conversion — routes to Currency Lambda",
    },
    {
        "query": "What are the latest AI news headlines?",
        "expected_tool": "news_api",
        "description": "News headlines — routes to News REST API",
    },
]


def main():
    print("=" * 70)
    print("  Analytics Gateway — Module 11 Exercise")
    print("  Agent discovers tools via Gateway (2 Lambda + 1 REST API)")
    print("=" * 70)

    # ── Create Gateway ──
    gateway = LambdaGateway(
        name="analytics-gateway",
        description="Lambda-backed tool gateway for analytics utilities"
    )
    print(f"\n  Gateway: {gateway.gateway_id}")
    gateway.register_target(
        name="weather_lambda",
        description="Look up current weather conditions for a given city including temperature, humidity, and wind",
        function_name=WEATHER_FUNCTION,
    )
    gateway.register_target(
        name="currency_lambda",
        description="Convert amounts between currencies using real-time exchange rates",
        function_name=CURRENCY_FUNCTION,
    )
    gateway.register_target(
        name="news_api",
        description="Get latest news headlines by topic including AI, finance, and technology",
        function_name=NEWS_FUNCTION,
    )

    print(f"  Registered {len(gateway.targets)} targets:")
    for t in gateway.discover_tools():
        print(f"    [{t['type']:8s}] {t['name']}")
    for i, test in enumerate(TEST_QUERIES):
        print(f"\n{'━' * 70}")
        print(f"  QUERY {i + 1}: \"{test['query']}\"")
        print(f"  Expected tool: {test['expected_tool']}")
        print(f"  {test['description']}")
        print(f"{'━' * 70}")

        elapsed = run_agent_with_retry(
            lambda: build_analytics_agent(gateway),
            test["query"]
        )
        print(f"    Time: {elapsed:.1f}s")
    print(f"\n{'═' * 70}")
    print("INVOCATION LOG")
    print(f"{'═' * 70}")
    for entry in gateway.invocation_log:
        print(f"  Tool: {entry['tool']:20s} Lambda: {entry['function']:30s} Status: {entry['result_status']}")

    print(f"\n  Key: 1) MIXED TARGETS — 2 Lambda + 1 REST API 2) SEMANTIC ROUTING")
    print(f"       3) ZERO CODE CHANGES — new API = config only\n")

    # ═══════════════════════════════════════════════════════
    #  EXTENSION: DYNAMIC TOOL REGISTRATION
    #  The gateway pattern's key advantage: add tools WITHOUT changing agent code.
    # ═══════════════════════════════════════════════════════

    print(f"{'═' * 70}")
    print("  EXTENSION: Adding 4th tool dynamically (no code changes)")
    print(f"{'═' * 70}")
    gateway.register_target(
        name="stock_price",
        description="Get current stock price for any ticker symbol including price and daily change",
        function_name=STOCK_PRICE_FUNCTION,
    )
    print(f"\n  {len(gateway.targets)} tools available:")
    for t in gateway.discover_tools():
        print(f"    [{t['type']:8s}] {t['name']}")

    # Rebuild agent to discover new tool
    test_query = "What is the current stock price of AMZN?"
    print(f"\n{'━' * 70}")
    print(f"  DYNAMIC QUERY: \"{test_query}\"")
    print(f"{'━' * 70}")
    elapsed = run_agent_with_retry(
        lambda: build_analytics_agent(gateway),
        test_query
    )
    print(f"    Time: {elapsed:.1f}s")

    print(f"\n{'═' * 70}")
    print("FINAL INVOCATION LOG")
    print(f"{'═' * 70}")
    for entry in gateway.invocation_log:
        print(f"  Tool: {entry['tool']:20s} Lambda: {entry['function']:30s} Status: {entry['result_status']}")

    print(f"\n  Gateway Pattern Advantage: register a 4th tool (stock_price) with NO changes to:")
    print(f"    - Agent invocation logic  (no re-deployment)")
    print(f"    - System prompt           (rebuilt automatically from gateway.discover_tools())\n")

    # ── AgentCore Gateway API (Production) ────────────────────────────────────
    print(f"{'═' * 70}")
    print("AgentCore Gateway API (Production)")
    print(f"{'═' * 70}")
    print("  Replace LambdaGateway with Amazon Bedrock AgentCore Gateway.")
    print("  These exact API calls register the same tools on a managed MCP endpoint:\n")

    agentcore_role = os.environ.get("AGENTCORE_ROLE_ARN", "")
    if not agentcore_role or agentcore_role.startswith("PASTE"):
        print("  AGENTCORE_ROLE_ARN not set in .env")
        print("  Run:  python infrastructure/deploy_stack.py")
        print("  Then paste the printed role ARN into .env as AGENTCORE_ROLE_ARN\n")
    else:
        try:
            result = create_agentcore_gateway(agentcore_role)
            print(f"\n  AgentCore Gateway is live:")
            print(f"    Gateway URL : {result['gateway_url']}")
            print(f"    Status      : {result['status']}")
            print(f"    Agents connect via MCP at this endpoint — no code changes needed")
        except Exception as e:
            print(f"  [{e.__class__.__name__}] {e}")
            print("  (Check AGENTCORE_ROLE_ARN and that the Lambda stack is deployed)\n")


if __name__ == "__main__":
    main()
