# Lesson 7: Implementing the Saga Pattern with Compensating Transactions

This lesson teaches the Saga pattern for multi-agent workflows that span multiple services without distributed transactions. Each agent provides both a forward action and a compensating action. When any step fails, the saga orchestrator runs compensating transactions in reverse order to undo previously completed steps. A DynamoDB-backed state machine tracks progress and enables crash recovery.

Each activity folder below has its own `infrastructure/`, `.env.example`, and `README.md` — open the one you're working on for setup steps.

## Folder Structure

```
lesson-07-saga-pattern-and-state-coordination/
├── README.md
├── demo-travel-booking/
│   ├── README.md
│   ├── .env.example
│   ├── infrastructure/stack.yaml         ← SagaState table
│   └── travel_booking_saga.py
└── exercise-ecommerce-checkout/
    ├── starter/
    │   ├── README.md
    │   ├── .env.example
    │   ├── infrastructure/stack.yaml     ← CheckoutSaga table
    │   └── ecommerce_checkout_saga.py
    └── solution/
        ├── README.md
        ├── .env.example
        ├── infrastructure/stack.yaml     ← same as starter; deploy only if you skipped the starter
        └── ecommerce_checkout_saga.py
```

- **Demo (travel booking):** 3 booking agents (flight, hotel, car), saga orchestrator with reverse-order compensation, DynamoDB state machine.
- **Exercise (e-commerce checkout):** 3 checkout agents (inventory, payment, shipping), saga orchestrator with a barrier coordination primitive that ensures all compensations complete before the saga resolves.
