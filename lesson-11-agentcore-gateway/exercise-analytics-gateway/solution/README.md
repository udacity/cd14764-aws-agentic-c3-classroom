# Exercise Solution: Analytics Gateway

## Overview
This exercise implements an analytics agent connected to utility services through AgentCore Gateway. Same pattern as the demo with mixed target types: 2 Lambda functions and 1 REST API.

## Architecture
- **Gateway:** SimulatedGateway with 3 registered targets
- **Targets:** Weather Lambda, Currency Lambda, News REST API
- **Agent:** AnalyticsAgent discovers and invokes tools via Gateway

## Test Cases (3 queries)
| Query | Expected Tool | Description |
|-------|--------------|-------------|
| Weather in Tokyo | weather_lambda | Routes to Weather Lambda |
| Convert 500 USD to EUR | currency_lambda | Routes to Currency Lambda |
| Latest AI news | news_api | Routes to News REST API |

## Running
```bash
python analytics_gateway.py
```

## Key Differences from Demo
- **Mixed targets** — 2 Lambda + 1 REST API (vs all REST in demo)
- **Analytics domain** — weather, currency, news instead of supply chain
- **Semantic routing focus** — agent must correctly match query to tool
