# Exercise Solution: Saga Pattern for E-Commerce Checkout

## Architecture

![Architecture Diagram](../architecture.svg)

## Overview
This exercise implements a saga-based checkout flow where an order spans inventory reservation, payment processing, and shipping scheduling. Same saga pattern as the demo, with one addition: a barrier coordination primitive that ensures all compensations complete before the saga resolves.

## Architecture
- **3 checkout agents:** InventoryAgent (reserve/release items), PaymentAgent (charge/refund card), ShippingAgent (schedule/cancel delivery)
- **Saga orchestrator:** Python controller with forward execution + reverse-order compensation
- **Barrier (NEW):** Atomic counter that each compensation increments. Saga resolves to 'failed' only when counter equals steps to compensate.

## Test Cases (3 checkouts)
| Checkout | Scenario | Key Behavior |
|----------|----------|-------------|
| CHK-001 | All succeed | Inventory + Payment + Shipping all confirmed |
| CHK-002 | Payment fails | Release inventory (1 compensation, barrier: 1/1) |
| CHK-003 | Shipping fails | Refund payment + Release inventory (2 compensations, barrier: 2/2) |

## Running
```bash
python ecommerce_checkout_saga.py
```

## Key Differences from Demo
- **Barrier coordination** — NEW: atomic counter ensures saga doesn't resolve prematurely
- **E-commerce domain** — inventory, payment, shipping instead of flight, hotel, car
- **Financial refunds** — payment compensation involves actual refund tracking
