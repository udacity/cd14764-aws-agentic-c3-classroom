# Exercise Starter: Trading Compliance Guardrails

## Overview
Build the governance stack for a financial trading compliance agent following the demo pattern (healthcare_guardrails.py). Implement 4 guardrail policy types, a kill switch, rate limiting, and audit logging. Add guardrail versioning and output guardrail scanning.

## Your Task
Complete **16 TODOs** in `trading_compliance.py`:

### Guardrail TODOs (6)
| TODO | What to implement | Hint |
|------|-------------------|------|
| TODO 1 | `create_version()` — promote DRAFT to "1" | NEW: Set self.version = "1" |
| TODO 2 | Content filtering (Policy 1) | Same as demo — regex matching |
| TODO 3 | PII blocking (Policy 2a) | Block CC, SSN, account numbers |
| TODO 4 | PII anonymization (Policy 2b) | Anonymize email, phone |
| TODO 5 | Topic denial (Policy 3) | Deny trading recs, insider, competitor |
| TODO 6 | Word filtering (Policy 4) | Profanity check |

### Infrastructure TODOs (2)
| TODO | What to implement | Hint |
|------|-------------------|------|
| TODO 7 | `record_violation()` — kill switch tracking | Track timestamps, check threshold |
| TODO 8 | `allow_request()` — token bucket rate limiter | Same as demo |

### Agent TODOs (3)
| TODO | What to implement | Hint |
|------|-------------------|------|
| TODO 9 | BedrockModel for compliance agent | NOVA_LITE_MODEL, temperature=0.1 |
| TODO 10 | System prompt for compliance agent | Regulatory info only, no trade recs |
| TODO 11 | Return Agent | Same as demo |

### Pipeline TODOs (5)
| TODO | What to implement | Hint |
|------|-------------------|------|
| TODO 12 | Kill switch check | If triggered, reject request |
| TODO 13 | Rate limiter check | If exhausted, return 429 |
| TODO 14 | Input guardrail + handle results | Apply guardrail, handle BLOCKED/ANONYMIZED |
| TODO 15 | Invoke compliance agent | run_agent_with_retry |
| TODO 16 | Output guardrail (NEW) | Scan agent response |

## What's Already Done
- All guardrail policy configurations (TRADING_GUARDRAIL_POLICIES)
- MetricsDashboard class (fully implemented)
- All 15 test inputs with expected actions
- The `check_trading_rules` @tool function
- Helper functions (clean_response, run_agent_with_retry)
- Main function with evaluation and dashboard output

## Expected Results
- 5 legitimate queries → ALLOWED (agent responds)
- 3 PII inputs → BLOCKED (CC, SSN, account number)
- 4 topic inputs → BLOCKED (trade recs, insider x2, competitor)
- 1 profanity → BLOCKED
- 1 harmful content → BLOCKED
- 1 email/phone → ANONYMIZED (PII replaced, agent still responds)
- Kill switch triggers after 3rd violation

## Running
```bash
python trading_compliance.py
```
