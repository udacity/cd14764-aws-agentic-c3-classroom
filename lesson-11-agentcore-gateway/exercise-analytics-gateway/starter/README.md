# Exercise Starter: Analytics Gateway

## Overview
Build an analytics agent connected to utility services through AgentCore Gateway following the demo pattern (supply_chain_gateway.py). Register 3 targets (2 Lambda + 1 REST API) and build an agent that discovers tools at runtime.

## Your Task
Complete **8 TODOs** in `analytics_gateway.py`:

### Agent TODOs (6)
| TODO | What to implement | Hint |
|------|-------------------|------|
| TODO 1 | BedrockModel | NOVA_LITE_MODEL, temperature=0.1 |
| TODO 2 | System prompt with Gateway tools | Use gateway.discover_tools() |
| TODO 3 | Weather @tool function | gateway.invoke_tool("weather_lambda", ...) |
| TODO 4 | Currency @tool function | gateway.invoke_tool("currency_lambda", ...) |
| TODO 5 | News @tool function | gateway.invoke_tool("news_api", ...) |
| TODO 6 | Return Agent | Agent(model, system_prompt, tools=[...]) |

### Gateway TODOs (2)
| TODO | What to implement | Hint |
|------|-------------------|------|
| TODO 7 | Register 3 targets on Gateway | register_target() for each API |
| TODO 8 | Run test queries through agent | run_agent_with_retry loop |

## What's Already Done
- SimulatedGateway class (fully implemented)
- All 3 API handler functions (weather, currency, news)
- Test queries with expected tools
- Main function skeleton with output formatting
- Helper functions (clean_response, run_agent_with_retry)

## Expected Results
- Query 1: Weather in Tokyo → Weather Lambda invoked
- Query 2: Convert 500 USD to EUR → Currency Lambda invoked
- Query 3: AI news headlines → News REST API invoked
- Gateway invocation log shows all 3 tools called

## Running
```bash
python analytics_gateway.py
```
