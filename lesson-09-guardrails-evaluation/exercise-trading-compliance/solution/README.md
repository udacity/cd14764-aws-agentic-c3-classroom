# Exercise Solution: Trading Compliance Guardrails

## Overview
This exercise implements the complete governance stack for a financial trading compliance agent. Same guardrail pattern as the demo, with additions: guardrail versioning (DRAFT → production), a stricter kill switch (3 violations in 60 seconds), and output guardrail scanning.

## Architecture
- **Compliance agent:** Strands Agent (Nova Lite) that answers regulatory questions
- **Guardrail versioning (NEW):** create_version() promotes from DRAFT to version "1"
- **Kill switch (stricter):** 3 violations in 60 seconds triggers agent shutdown
- **Output guardrail (NEW):** Scans agent responses for PII leaks

## Test Cases (15 inputs)
| Input | Label | Expected | Policy |
|-------|-------|----------|--------|
| 5 regulatory questions | Legitimate | ALLOWED | — |
| Credit card number | Adversarial | BLOCKED | PII |
| SSN | Adversarial | BLOCKED | PII |
| Account number | Adversarial | BLOCKED | PII |
| Trade recommendation | Adversarial | BLOCKED | TOPIC |
| Insider trading (x2) | Adversarial | BLOCKED | TOPIC |
| Competitor disparagement | Adversarial | BLOCKED | TOPIC |
| Profanity | Adversarial | BLOCKED | WORD |
| Harmful content | Adversarial | BLOCKED | CONTENT |
| Email/phone (anonymize) | Adversarial | ANONYMIZED | PII |

## Running
```bash
python trading_compliance.py
```

## Key Differences from Demo
- **Guardrail versioning** — NEW: DRAFT → version 1 promotion
- **Stricter kill switch** — 3 violations/60s vs percentage-based in demo
- **Output guardrail** — NEW: scans agent responses, not just inputs
- **Financial domain** — trading regulations, PII includes credit cards and account numbers
- **More adversarial inputs** — 10 vs 5, testing all four policy types
