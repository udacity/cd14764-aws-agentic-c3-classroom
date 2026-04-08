# Lesson 9: Implementing Guardrails and Evaluation at Scale

This lesson teaches production-grade governance for multi-agent systems. We implement four Bedrock Guardrail policy types (content filtering, PII protection, topic denial, word filtering), a CloudWatch-based kill switch that disables the agent when violation rates spike, API Gateway rate limiting, and a monitoring dashboard for real-time visibility. Every guardrail decision is audit-logged for compliance reporting.

The lesson uses simulated Bedrock Guardrails, CloudWatch, and API Gateway so students can focus on the governance patterns without infrastructure setup. Production-mapping comments throughout the code show the exact boto3 API calls.

## Folder Structure

```
lesson-09-guardrails-evaluation/
├── README.md
├── demo-healthcare-guardrails/
│   ├── README.md
│   └── healthcare_guardrails.py
└── exercise-trading-compliance/
    ├── solution/
    │   ├── README.md
    │   └── trading_compliance.py
    └── starter/
        ├── README.md
        └── trading_compliance.py
```

## Demo: Healthcare Agent Guardrails (Instructor-led)
- **Domain:** Telehealth patient intake agent
- **Guardrail:** 4 policy types — content (block violence/self-harm), PII (block SSN/insurance, anonymize email/phone), topic (deny legal advice/prescriptions), word (profanity filter)
- **Kill switch:** Violation rate threshold over 5-minute window
- **Rate limiting:** Token bucket at 100 req/sec (burst 200)
- **Test cases:** 5 legitimate patient queries + 5 adversarial inputs
- **Key insight:** Guardrails wrap the agent, not replace it — input guardrail → agent → output guardrail

## Exercise: Trading Compliance Guardrails (Student-led)
- **Domain:** Financial trading compliance agent for a brokerage firm
- **Guardrail versioning (NEW):** DRAFT → create_version() → production release
- **Stricter kill switch:** 3 violations in 60 seconds (vs 5-minute window in demo)
- **Output guardrail (NEW):** Scans agent responses for PII leaks, not just inputs
- **Test cases:** 5 legitimate queries + 10 adversarial inputs (PII, insider trading, competitor disparagement, profanity)
- **Key insight:** Financial governance requires defense in depth — every guardrail action must be auditable
