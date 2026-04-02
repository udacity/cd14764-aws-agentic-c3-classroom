# Exercise Solution: Orchestrated Package Delivery Workflow

## Overview
This exercise builds an orchestrated logistics workflow for package delivery that combines a sequential gate, parallel execution, and conditional routing — the same three orchestration patterns from the demo, applied to a different domain.

## Architecture
- **Phase 1 SEQUENTIAL GATE:** AddressValidator → valid? If NO → halt entire workflow
- **Phase 2 PARALLEL:** LabelGenerator + InsuranceCalculator + CarrierSelector (via ThreadPoolExecutor)
- **Phase 3 CONDITIONAL:** DomesticShipping (same country) OR InternationalShipping (different country)
- **Orchestrator:** Python code (same pattern as demo)

## Models
- All 6 worker agents: Amazon Nova Lite (fast execution, temperature 0.0)

## Test Cases
| Package | Destination | Expected Route | Special |
|---------|------------|---------------|---------|
| PKG-001 Electronics | US → US | Domestic | Normal flow |
| PKG-002 Equipment | US → DE | International | Customs declaration |
| PKG-003 Books | US → US | HALTED | Empty address → gate stops workflow |

## Running
```bash
python delivery_workflow.py
```

## Key Differences from Demo
- **Gate pattern** — demo uses sequential chain (A then B, both always run); exercise uses gate (validate or halt)
- **Insurance tiers** — basic/standard/premium based on declared value thresholds
- **Carrier selection** — cheapest carrier auto-selected from available options
- **Customs handling** — international path adds customs declaration and duty calculation
