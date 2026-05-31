# Lesson 11 — Inter-Agent Communication via Gateway

This lesson teaches the **AgentCore Gateway pattern**: instead of hardcoding tool integrations with `@tool` decorators, you register APIs with a Gateway and agents discover them through MCP at runtime. Tools can be added, updated, or removed without touching agent code.

Both the demo and exercise use real AWS Lambda functions as tool backends, an in-lesson `LambdaGateway` abstraction, and end with live `create_gateway` / `create_gateway_target` calls that show the exact production API.

Each activity folder below has its own `infrastructure/`, `.env.example`, and `README.md` — open the one you're working on for setup steps.

## Folder Structure

```
lesson-11-inter-agent-communication-via-gateway/
├── README.md
├── demo-supply-chain-gateway/
│   ├── README.md
│   ├── .env.example
│   ├── infrastructure/
│   │   ├── deploy_stack.py
│   │   └── stack.yaml                    ← 4 supply-chain Lambdas + AgentCore role
│   └── supply_chain_gateway.py
└── exercise-analytics-gateway/
    ├── starter/
    │   ├── README.md
    │   ├── .env.example
    │   ├── infrastructure/
    │   │   ├── deploy_stack.py
    │   │   └── stack.yaml                ← 4 analytics Lambdas + AgentCore role
    │   └── analytics_gateway.py
    └── solution/
        ├── README.md
        ├── .env.example
        ├── infrastructure/               ← same as starter; deploy only if you skipped the starter
        └── analytics_gateway.py
```

- **Demo (supply chain):** 4 Lambda targets (inventory, shipping, supplier, quality inspection), dynamic registration of the 4th tool, live `create_gateway` API.
- **Exercise (analytics):** 4 Lambda targets (weather, currency, news, stock price) with mixed Lambda + REST API patterns and dynamic registration.
