# Exercise Starter: Orchestrated Package Delivery Workflow

## Overview
Build an orchestrated logistics workflow for package delivery following the same pattern from the demo (hr_onboarding.py).

## Your Task
Complete **18 TODOs** (3 per agent × 6 agents) in `delivery_workflow.py`:

Each `build_*()` function needs three things (same STEP 1/2/3 pattern as the demo):

| TODO | What to do | Hint |
|------|-----------|------|
| STEP 1 | Create `BedrockModel` | `BedrockModel(model_id=NOVA_LITE_MODEL, region_name=AWS_REGION, temperature=0.0)` |
| STEP 2 | Write system prompt | Tell the agent its ONE job — which tool to call and what to report |
| STEP 3 | Return `Agent(...)` | `return Agent(model=model, system_prompt=system_prompt, tools=[the_tool])` |

## What's Already Done
- All 6 `@tool` functions (validate_address, generate_label, calculate_insurance, select_carrier, process_domestic, process_international)
- The orchestrator (orchestrate_delivery) with all 3 phases
- The main() function with test execution and summary table
- Helper functions (clean_response, run_agent_with_retry)
- Sample data (DELIVERIES, CARRIER_RATES, INSURANCE_RATES)

## Architecture (same 3-pattern approach as demo)
1. **Phase 1 — Sequential Gate:** AddressValidator must return 'valid' before continuing
2. **Phase 2 — Parallel:** LabelGenerator + InsuranceCalculator + CarrierSelector run simultaneously
3. **Phase 3 — Conditional:** Route to DomesticShipping or InternationalShipping based on country

## Expected Results
| Package | Route | Notes |
|---------|-------|-------|
| PKG-001 | Domestic | US → US, USPS Priority, basic insurance |
| PKG-002 | International | US → DE, DHL International, premium insurance + customs |
| PKG-003 | HALTED | Empty address → gate stops workflow |

## Running
```bash
python delivery_workflow.py
```
