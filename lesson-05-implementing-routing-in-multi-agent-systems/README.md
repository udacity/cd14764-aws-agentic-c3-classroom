# Lesson 5: Implementing Routing in Multi-Agent Systems

This lesson teaches how to build a hybrid routing system that combines rule-based routing (fast, free, deterministic) with LLM-powered classification (flexible, handles ambiguity), plus priority routing for business-critical requests and a fallback safety net.

Each activity folder below has its own `infrastructure/`, `.env.example`, and `README.md` — open the one you're working on for setup steps.

## Folder Structure

```
lesson-05-implementing-routing-in-multi-agent-systems/
├── README.md
├── demo-financial-router/
│   ├── README.md
│   ├── .env.example
│   ├── infrastructure/stack.yaml         ← demo routing-audit table
│   └── financial_router.py
└── exercise-telecom-router/
    ├── starter/
    │   ├── README.md
    │   ├── .env.example
    │   ├── infrastructure/stack.yaml     ← exercise routing-audit table
    │   └── telecom_router.py
    └── solution/
        ├── README.md
        ├── .env.example
        ├── infrastructure/stack.yaml     ← same as starter; deploy only if you skipped the starter
        └── telecom_router.py
```

- **Demo (financial transactions):** 5 specialist agents + 1 LLM classifier, hybrid router with priority/rule/LLM/fallback paths.
- **Exercise (telecom support):** 4 specialist agents + 1 LLM classifier, same hybrid router pattern applied to telecom tickets with a routing-effectiveness report.
