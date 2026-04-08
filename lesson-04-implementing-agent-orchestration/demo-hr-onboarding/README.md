# Demo: HR Employee Onboarding Orchestration

## Architecture

![Architecture Diagram](architecture.svg)

## Overview
This demo builds an orchestrated employee onboarding workflow that demonstrates three core orchestration patterns in a single workflow: sequential execution, parallel branches, and conditional routing — all managed by a Python code orchestrator.

## Architecture
- **Phase 1 SEQUENTIAL:** AccountCreator → ManagerAssigner (account must exist before manager assignment)
- **Phase 2 PARALLEL:** LaptopProvisioner + EmailSetup + BuildingAccess (independent tasks via ThreadPoolExecutor)
- **Phase 3 CONDITIONAL:** EngineeringOnboarding OR SalesOnboarding (based on department field)
- **Orchestrator:** Python code (NOT an LLM) — deterministic, debuggable, testable

## Models
- All 6 worker agents: Amazon Nova Lite (fast execution, temperature 0.0)

## Test Cases
| Employee | Department | Path | Special |
|----------|-----------|------|---------|
| EMP-001 Alice Chen | Engineering | Engineering onboarding | Normal |
| EMP-002 Bob Martinez | Sales | Sales onboarding | Normal |
| EMP-003 Carol Johnson | Engineering | Engineering onboarding | Simulated laptop failure (retry) |

## Running
```bash
python hr_onboarding.py
```

## Key Takeaways
1. **Sequential** — when steps depend on each other (account → manager)
2. **Parallel** — when steps are independent (laptop + email + building)
3. **Conditional** — when the path depends on data (department routing)
4. **Failure handling** — retry with exponential backoff for transient errors
5. **Code orchestrator** — Python manages execution order; worker agents stay simple and stateless
