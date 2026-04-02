# Exercise Starter: Multi-Strategy Router for Telecom Customer Tickets

## Overview
Build a hybrid routing system for telecom support tickets following the same pattern from the demo (financial_router.py).

## Your Task
Complete **18 TODOs** in `telecom_router.py`:

### Routing Strategy TODOs (3)
| TODO | What to implement | Hint |
|------|-------------------|------|
| TODO 1 | `priority_route()` — detect cancellation keywords | `re.search(r"\b(cancel\|switch provider\|...)\b", text.lower())` |
| TODO 2 | `rule_based_route()` + `ROUTING_RULES` — billing & technical keywords | Same pattern as demo's `ROUTING_RULES` list |
| TODO 3 | `build_classifier_agent()` — STEP 1/2/3 | Same as demo's classifier but for telecom intents |

### Worker Agent TODOs (12 = 3 per agent × 4 agents)
| Agent | TODOs | Tool provided |
|-------|-------|---------------|
| BillingAgent | 4, 5, 6 | handle_billing |
| TechnicalAgent | 7, 8, 9 | handle_technical |
| RetentionAgent | 10, 11, 12 | handle_retention |
| GeneralSupportAgent | 13, 14, 15 | handle_general |

Each agent follows STEP 1 → STEP 2 → STEP 3 (model → prompt → agent).

## What's Already Done
- All `@tool` functions for workers and classifier
- The hybrid router (`hybrid_route()`)
- The main function with all 20 test tickets
- Routing effectiveness report
- DynamoDB audit logging
- Helper functions (clean_response, run_agent_with_retry)

## Expected Results
- 8 billing tickets → BillingAgent (rule)
- 6 technical tickets → TechnicalAgent (rule)
- 2 cancellation tickets → RetentionAgent (priority)
- 3 ambiguous tickets → LLM-classified
- 1 nonsensical ticket → GeneralSupportAgent (fallback)

## Running
```bash
python telecom_router.py
```
