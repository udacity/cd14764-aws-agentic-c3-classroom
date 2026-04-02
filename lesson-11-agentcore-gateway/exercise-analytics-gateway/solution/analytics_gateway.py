"""
analytics_gateway.py - EXERCISE SOLUTION (Student-Led)
Module 11 Exercise: Register and Invoke Tools through AgentCore Gateway

Same Gateway pattern as demo, with additions:
  1. MIXED TARGET TYPES: 2 Lambda + 1 REST API
  2. DIFFERENT DOMAIN: Analytics instead of supply chain
  3. SEMANTIC ROUTING: Agent selects tool by query

Tech: Python 3.11+ | Strands SDK | Bedrock Nova | Simulated Gateway
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


# SIMULATED AgentCore GATEWAY
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


# SIMULATED APIs (Gateway targets)
def weather_lambda_handler(params: dict) -> dict:
    """Simulated Lambda: weather lookup by city."""
    weather_data = {
        "tokyo": {"city": "Tokyo", "temp_c": 22, "condition": "Partly Cloudy",
                  "humidity": 65, "wind_kph": 12},
        "london": {"city": "London", "temp_c": 14, "condition": "Rainy",
                   "humidity": 82, "wind_kph": 20},
        "new york": {"city": "New York", "temp_c": 18, "condition": "Sunny",
                     "humidity": 45, "wind_kph": 8},
        "sydney": {"city": "Sydney", "temp_c": 26, "condition": "Clear",
                   "humidity": 55, "wind_kph": 15},
    }
    city = params.get("city", "").lower()
    if city in weather_data:
        return {"status": "ok", "weather": weather_data[city]}
    return {"status": "error", "message": f"City '{city}' not found"}

def currency_lambda_handler(params: dict) -> dict:
    """Simulated Lambda: currency conversion."""
    rates = {
        "USD": 1.0, "EUR": 0.92, "GBP": 0.79, "JPY": 151.5,
        "AUD": 1.53, "CAD": 1.36, "CHF": 0.88,
    }
    amount = params.get("amount", 0)
    from_currency = params.get("from", "USD").upper()
    to_currency = params.get("to", "EUR").upper()

    if from_currency not in rates or to_currency not in rates:
        return {"status": "error", "message": "Unsupported currency"}
    usd_amount = amount / rates[from_currency]
    converted = round(usd_amount * rates[to_currency], 2)

    return {
        "status": "ok",
        "conversion": {
            "from": from_currency, "to": to_currency,
            "original_amount": amount, "converted_amount": converted,
            "rate": round(rates[to_currency] / rates[from_currency], 4),
        },
    }

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
            {"title": "Bitcoin Surges Past $70,000 Amid ETF Inflows", "source": "CoinDesk"},
        ],
        "technology": [
            {"title": "Apple Unveils M4 Ultra Chip at Developer Conference", "source": "The Verge"},
            {"title": "Quantum Computing Breakthrough: 1000-Qubit Processor", "source": "Nature"},
            {"title": "Cybersecurity Spending to Reach $200B in 2025", "source": "Gartner"},
        ],
    }
    topic = params.get("topic", "ai").lower()
    if topic in headlines:
        return {"status": "ok", "topic": topic, "headlines": headlines[topic]}
    return {"status": "ok", "topic": "general", "headlines": [
        item for sublist in headlines.values() for item in sublist[:1]
    ]}

def build_analytics_agent(gateway: SimulatedGateway) -> Agent:
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

    return Agent(model=model, system_prompt=system_prompt,
                 tools=[get_weather, convert_currency, get_news])


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
    gateway = SimulatedGateway(
        name="analytics-gateway",
        description="MCP endpoint for analytics utility services"
    )
    print(f"\n  Gateway: {gateway.gateway_id}")
    gateway.register_target(
        name="weather_lambda",
        description="Look up current weather conditions for a given city including temperature, humidity, and wind",
        target_type="LAMBDA",
        handler=weather_lambda_handler,
    )
    gateway.register_target(
        name="currency_lambda",
        description="Convert amounts between currencies using real-time exchange rates",
        target_type="LAMBDA",
        handler=currency_lambda_handler,
    )
    gateway.register_target(
        name="news_api",
        description="Get latest news headlines by topic including AI, finance, and technology",
        target_type="REST_API",
        handler=news_api_handler,
        openapi_spec={"openapi": "3.0.0", "info": {"title": "News API"}},
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
        print(f"  Tool: {entry['tool']:20s} Params: {json.dumps(entry['params'])}")

    print(f"\n  Key: 1) MIXED TARGETS — 2 Lambda + 1 REST API 2) SEMANTIC ROUTING")
    print(f"       3) ZERO CODE CHANGES — new API = config only\n")


if __name__ == "__main__":
    main()
