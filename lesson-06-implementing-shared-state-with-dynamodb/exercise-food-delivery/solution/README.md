# Exercise Solution: Shared State for Food Delivery Orders

## Architecture

![Architecture Diagram](architecture.svg)

## Overview
This exercise builds a shared state system for food delivery orders using the same optimistic locking pattern from the demo, with two additions: 4 agents instead of 3 (more concurrent conflicts), and a state recovery pattern that cleans up partial updates after a restaurant rejection.

## Setup

1. Copy the env template:
   ```bash
   cp .env.example .env
   ```
2. If you already deployed the stack while doing the starter (`lesson-06-exercise-shared-state`), you don't need to deploy again — copy your starter `.env` values into this one to point at the same resources. Otherwise:
   ```bash
   aws cloudformation deploy --template-file infrastructure/stack.yaml \
       --stack-name lesson-06-exercise-shared-state
   ```

## Architecture
- **DynamoDB:** Real OrderState table with optimistic locking (version-based conditional writes), TTL (2 hours)
- **4 worker agents:** RestaurantConfirmAgent (status), DriverAssignAgent (driver), PriceCalculatorAgent (total_price), StatusTrackerAgent (progress)
- **State recovery:** `recover_order()` resets driver/price to None and marks order cancelled when restaurant rejects
- **Cross-session memory:** customer_memory dict simulates AgentCore Memory SESSION_SUMMARY strategy — remembers preferred driver and favorite restaurant

## Test Cases (3 orders)
| Order | Scenario | Key Behavior |
|-------|----------|-------------|
| ORD-001 | Sequential | 4 agents run one at a time — no conflicts |
| ORD-002 | Concurrent | All 4 agents in parallel — version conflicts + retry |
| ORD-003 | State recovery + memory | Driver + Price agents write first, then restaurant REJECTS → recover_order() cleans up. Same customer as ORD-001 — preferred driver from memory |

## Running
```bash
python food_delivery_state.py
```

## Cleanup
```bash
aws cloudformation delete-stack --stack-name lesson-06-exercise-shared-state
```

## Key Differences from Demo
- **4 agents** (demo had 3) — more concurrent conflict opportunities
- **State recovery** — NEW pattern: cleanup partial writes after failure
- **Restaurant rejection** — real-world pattern where upstream failure invalidates downstream work
- **DynamoDB + simulated AgentCore Memory** — same dual-service pattern for transactional state + conversational context, with production-mapping comments for the AgentCore Memory side
