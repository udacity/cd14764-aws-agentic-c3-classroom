# Exercise Solution: Shared State for Food Delivery Orders

## Overview
This exercise builds a shared state system for food delivery orders using the same optimistic locking pattern from the demo, with two additions: 4 agents instead of 3 (more concurrent conflicts), and a state recovery pattern that cleans up partial updates after a restaurant rejection.

## Architecture
- **SimulatedDynamoDB:** OrderState table with optimistic locking (version-based conditional writes), TTL (2 hours)
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

## Key Differences from Demo
- **4 agents** (demo had 3) — more concurrent conflict opportunities
- **State recovery** — NEW pattern: cleanup partial writes after failure
- **Restaurant rejection** — real-world pattern where upstream failure invalidates downstream work
- **Simulated DynamoDB + AgentCore Memory** — same dual-service pattern for transactional state + conversational context, with production-mapping comments
