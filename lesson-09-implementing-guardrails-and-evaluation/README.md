# Lesson 9: Implementing Guardrails and Evaluation at Scale

This lesson teaches production-grade governance for multi-agent systems. We implement four Bedrock Guardrail policy types (content filtering, PII protection, topic denial, word filtering), a CloudWatch-based kill switch that disables the agent when violation rates spike, API Gateway rate limiting, and a monitoring dashboard for real-time visibility. Every guardrail decision is audit-logged for compliance reporting.

The lesson uses **real Amazon Bedrock Guardrails** in **us-east-1**. Each activity folder below has its own `infrastructure/`, `.env.example`, and `README.md` — open the one you're working on for setup steps.

## Folder Structure

```
lesson-09-implementing-guardrails-and-evaluation/
├── README.md
├── demo-healthcare-guardrails/
│   ├── README.md
│   ├── .env.example
│   ├── infrastructure/stack.yaml         ← Healthcare guardrail
│   └── healthcare_guardrails.py
└── exercise-trading-compliance/
    ├── starter/
    │   ├── README.md
    │   ├── .env.example
    │   ├── infrastructure/stack.yaml     ← Trading guardrail
    │   └── trading_compliance.py
    └── solution/
        ├── README.md
        ├── .env.example
        ├── infrastructure/stack.yaml     ← same as starter; deploy only if you skipped the starter
        └── trading_compliance.py
```

- **Demo (healthcare):** 4 policy types (content, PII, topic, word), kill switch, rate limiting, audit log.
- **Exercise (trading compliance):** Same governance stack with three additions — guardrail versioning (DRAFT → production), a stricter kill switch (3 violations / 60s), and output-guardrail scanning of agent responses.
