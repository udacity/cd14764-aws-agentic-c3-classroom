"""
analytics_gateway.py - EXERCISE STARTER (Student-Led)
==============================================================
Module 11 Exercise: Register and Invoke Tools through AgentCore Gateway

Same Gateway pattern as the demo (supply_chain_gateway.py),
with additions:
  1. MIXED TARGET TYPES: 2 Lambda + 1 REST API
  2. DIFFERENT DOMAIN: Analytics utilities
  3. SEMANTIC ROUTING: Agent selects tool by query meaning

Instructions:
  - Follow the demo pattern (supply_chain_gateway.py)
  - Look for TODO 1-8 below
  - Register 3 targets on the Gateway
  - Build an agent that discovers and uses Gateway tools

Tech Stack:
  - Python 3.11+
  - Strands Agents SDK (Agent class, @tool decorator)
  - Amazon Bedrock (Nova Lite for the agent)
  - Simulated AgentCore Gateway
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
# CONFIGURATION (provided)
# ─────────────────────────────────────────────────────
AWS_REGION = "us-east-1"
NOVA_LITE_MODEL = "amazon.nova-lite-v1:0"


# SIMULATED GATEWAY
class SimulatedGateway:
    """Simulates AgentCore Gateway with tool registration and discovery."""

    def __init__(self, name: str, description: str):
        self.gateway_id = f"gw-{name.lower().replace(' ', '-')[:20]}"
        self.name = name
        self.description = description
        self.targets = {}
        self.invocation_log = []

    def register_target(self, name: str, description: str, target_type: str,
                        handler: callable, openapi_spec: dict = None):
        self.targets[name] = {
            "name": name, "description": description,
            "type": target_type, "handler": handler,
            "openapi_spec": openapi_spec,
        }

    def discover_tools(self, query: str = None) -> list[dict]:
        return [{"name": n, "description": t["description"], "type": t["type"]}
                for n, t in self.targets.items()]

    def invoke_tool(self, tool_name: str, params: dict) -> dict:
        if tool_name not in self.targets:
            return {"error": f"Tool '{tool_name}' not found"}
        result = self.targets[tool_name]["handler"](params)
        self.invocation_log.append({"tool": tool_name, "params": params, "timestamp": time.time()})
        return result


# SIMULATED APIs
def weather_lambda_handler(params: dict) -> dict:
    """Simulated Lambda: weather lookup by city."""
    weather_data = {
        "tokyo": {"city": "Tokyo", "temp_c": 22, "condition": "Partly Cloudy", "humidity": 65, "wind_kph": 12},
        "london": {"city": "London", "temp_c": 14, "condition": "Rainy", "humidity": 82, "wind_kph": 20},
        "new york": {"city": "New York", "temp_c": 18, "condition": "Sunny", "humidity": 45, "wind_kph": 8},
        "sydney": {"city": "Sydney", "temp_c": 26, "condition": "Clear", "humidity": 55, "wind_kph": 15},
    }
    city = params.get("city", "").lower()
    if city in weather_data:
        return {"status": "ok", "weather": weather_data[city]}
    return {"status": "error", "message": "City not found"}


def currency_lambda_handler(params: dict) -> dict:
    """Simulated Lambda: currency conversion."""
    rates = {"USD": 1.0, "EUR": 0.92, "GBP": 0.79, "JPY": 151.5, "AUD": 1.53, "CAD": 1.36, "CHF": 0.88}
    amount = params.get("amount", 0)
    from_c = params.get("from", "USD").upper()
    to_c = params.get("to", "EUR").upper()
    if from_c not in rates or to_c not in rates:
        return {"status": "error", "message": "Currency not supported"}
    converted = round((amount / rates[from_c]) * rates[to_c], 2)
    return {"status": "ok", "conversion": {"from": from_c, "to": to_c, "amount": converted}}


def news_api_handler(params: dict) -> dict:
    """Simulated REST API: news headlines by topic."""
    headlines = {
        "ai": [
            {"title": "OpenAI Announces GPT-5 with Multimodal Reasoning", "source": "TechCrunch"},
            {"title": "AWS Launches AgentCore for Multi-Agent Systems", "source": "AWS Blog"},
            {"title": "AI Regulation Framework Advances in EU Parliament", "source": "Reuters"},
        ],
        "finance": [
            {"title": "Fed Holds Interest Rates Steady at 5.25%", "source": "Bloomberg"},
            {"title": "S&P 500 Hits New All-Time High on Tech Rally", "source": "CNBC"},
        ],
        "technology": [
            {"title": "Apple Unveils M4 Ultra Chip at Developer Conference", "source": "The Verge"},
            {"title": "Quantum Computing Breakthrough: 1000-Qubit Processor", "source": "Nature"},
        ],
    }
    topic = params.get("topic", "ai").lower()
    return {"status": "ok", "topic": topic, "headlines": headlines.get(topic, headlines["ai"])}


# ANALYTICS AGENT
def build_analytics_agent(gateway: SimulatedGateway) -> Agent:
    """Build an analytics agent connected to the Gateway."""

    # TODO 1: Create a BedrockModel
    # Hint: NOVA_LITE_MODEL, temperature=0.1
    model = None  # Replace with BedrockModel(...)

    # TODO 2: Build system prompt listing available Gateway tools
    # Hint: Use gateway.discover_tools() to list tools dynamically
    system_prompt = ""  # Replace with system prompt

    # TODO 3: Create @tool function for weather lookup
    # Hint: Call gateway.invoke_tool("weather_lambda", {"city": city})
    @tool
    def get_weather(city: str) -> str:
        """Look up current weather conditions for a city.
        Args:
            city: City name (e.g., "Tokyo")
        Returns:
            JSON with weather data
        """
        pass  # Replace with gateway.invoke_tool call

    # TODO 4: Create @tool function for currency conversion
    # Hint: Call gateway.invoke_tool("currency_lambda", {"amount": ..., "from": ..., "to": ...})
    @tool
    def convert_currency(amount: float, from_currency: str, to_currency: str) -> str:
        """Convert an amount between currencies.
        Args:
            amount: Amount to convert
            from_currency: Source currency (e.g., "USD")
            to_currency: Target currency (e.g., "EUR")
        Returns:
            JSON with conversion result
        """
        pass  # Replace with gateway.invoke_tool call

    # TODO 5: Create @tool function for news headlines
    # Hint: Call gateway.invoke_tool("news_api", {"topic": topic})
    @tool
    def get_news(topic: str) -> str:
        """Get latest news headlines by topic.
        Args:
            topic: News topic (e.g., "ai", "finance", "technology")
        Returns:
            JSON with headlines
        """
        pass  # Replace with gateway.invoke_tool call

    # TODO 6: Return Agent with model, system_prompt, and all 3 tools
    pass  # Replace with return Agent(...)

TEST_QUERIES = [
    {"query": "What is the weather in Tokyo right now?",
     "expected_tool": "weather_lambda", "description": "Weather lookup — routes to Weather Lambda"},
    {"query": "Convert 500 USD to EUR",
     "expected_tool": "currency_lambda", "description": "Currency conversion — routes to Currency Lambda"},
    {"query": "What are the latest AI news headlines?",
     "expected_tool": "news_api", "description": "News headlines — routes to News REST API"},
]


def main():
    print("=" * 70)
    print("  Analytics Gateway — Module 11 Exercise")
    print("  Agent discovers tools via Gateway (2 Lambda + 1 REST API)")
    print("=" * 70)

    # ── Create Gateway ──
    gateway = SimulatedGateway(
        name="analytics-gateway",
        description="MCP endpoint for analytics utility services"
    )
    print(f"\n  Gateway: {gateway.gateway_id}")
    # TODO 7: Register 3 targets on the Gateway
    # Hint: Same as demo — register_target() for each API
    #   weather_lambda (LAMBDA), currency_lambda (LAMBDA), news_api (REST_API)
    #   Include descriptive descriptions for semantic tool selection
    # Replace with 3 gateway.register_target() calls

    print(f"  Registered {len(gateway.targets)} targets:")
    for t in gateway.discover_tools():
        print(f"    [{t['type']:8s}] {t['name']}")
    # TODO 8: Run test queries through the agent
    # Hint: Same as demo — loop through TEST_QUERIES,
    #   run_agent_with_retry(lambda: build_analytics_agent(gateway), query)
    for i, test in enumerate(TEST_QUERIES):
        print(f"\n{'━' * 70}")
        print(f"  QUERY {i + 1}: \"{test['query']}\"")
        print(f"  Expected tool: {test['expected_tool']}")
        print(f"  {test['description']}")
        print(f"{'━' * 70}")
    print(f"\n{'═' * 70}")
    print("INVOCATION LOG")
    print(f"{'═' * 70}")
    for entry in gateway.invocation_log:
        print(f"  Tool: {entry['tool']:20s} Params: {json.dumps(entry['params'])}")

    print(f"\n  Key: 1) MIXED TARGETS — 2 Lambda + 1 REST API 2) SEMANTIC ROUTING")
    print(f"       3) ZERO CODE CHANGES — new API = config only\n")


if __name__ == "__main__":
    main()
