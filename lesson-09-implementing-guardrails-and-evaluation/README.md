# Lesson 9: Implementing Guardrails and Evaluation at Scale

This lesson teaches production-grade governance for multi-agent systems. We implement four Bedrock Guardrail policy types (content filtering, PII protection, topic denial, word filtering), a CloudWatch-based kill switch that disables the agent when violation rates spike, API Gateway rate limiting, and a monitoring dashboard for real-time visibility. Every guardrail decision is audit-logged for compliance reporting.

The lesson uses **real Amazon Bedrock Guardrails**. When `HEALTHCARE_GUARDRAIL_ID` / `TRADING_GUARDRAIL_ID` are set (populated by the CloudFormation stack below), the code calls the actual `bedrock-runtime.apply_guardrail()` API. If those env vars are not set, the guardrail check is skipped and all requests pass through — useful for testing the agent in isolation. Deploy the stack before running the demo or exercise. Production-mapping comments throughout the code show the full boto3 API surface.

## Setup

Deploy the CloudFormation stack to create both guardrails:

```python
import boto3, json
cf = boto3.client("cloudformation", region_name="us-west-1")
with open("infrastructure/stack.yaml") as f:
    template = f.read()
cf.create_stack(StackName="lesson-09-guardrails", TemplateBody=template, Capabilities=["CAPABILITY_NAMED_IAM"])
waiter = cf.get_waiter("stack_create_complete")
waiter.wait(StackName="lesson-09-guardrails")
outputs = {o["OutputKey"]: o["OutputValue"] for o in cf.describe_stacks(StackName="lesson-09-guardrails")["Stacks"][0]["Outputs"]}
print(outputs)
```

Copy `HealthcareGuardrailId` → `HEALTHCARE_GUARDRAIL_ID` and `TradingGuardrailId` → `TRADING_GUARDRAIL_ID` in your `.env` file.

## Folder Structure

```
lesson-09-implementing-guardrails-and-evaluation/
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

## Cleanup

The CloudFormation stack creates two Bedrock Guardrails (Healthcare + Trading). Guardrails carry a small ongoing charge per evaluation request, but unused guardrails cost nothing — still, tear them down when you're done so they don't clutter the console:

```bash
aws cloudformation delete-stack --stack-name lesson-09-guardrails
```
