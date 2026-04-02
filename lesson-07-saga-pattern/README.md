# Lesson 7: Implementing the Saga Pattern with Compensating Transactions

This lesson teaches the Saga pattern for multi-agent workflows that span multiple services without distributed transactions. Each agent provides both a forward action and a compensating action. When any step fails, the saga orchestrator runs compensating transactions in reverse order to undo previously completed steps. A DynamoDB-backed state machine tracks progress and enables crash recovery.

The lesson uses in-memory simulations of DynamoDB so students can focus on the saga pattern without infrastructure setup. Production-mapping comments throughout the code show the exact boto3 API calls.

## Folder Structure

```
lesson-07-saga-pattern/
├── README.md
├── demo-travel-booking/
│   └── solution/
│       ├── README.md
│       └── travel_booking_saga.py
└── exercise-ecommerce-checkout/
    ├── solution/
    │   ├── README.md
    │   └── ecommerce_checkout_saga.py
    └── starter/
        ├── README.md
        └── ecommerce_checkout_saga.py
```

## Demo: Saga Pattern for Travel Booking (Instructor-led)
- **Domain:** Travel booking (flight, hotel, car rental)
- **Architecture:** 3 booking agents, each with forward + compensating action, orchestrated by a Python saga controller
- **State Machine:** SimulatedDynamoDB tracks saga progress (pending → executing → completed → compensating → compensated)
- **Distributed Lock:** Conditional write prevents concurrent compensation attempts
- **Test cases:** 3 packages — all succeed, car fails (compensate hotel + flight), hotel fails (compensate flight only)
- **Key insight:** Compensating transactions run in reverse order — last-completed step compensates first

## Exercise: Saga Pattern for E-Commerce Checkout (Student-led)
- **Domain:** E-commerce checkout (inventory reservation, payment processing, shipping scheduling)
- **Architecture:** 3 checkout agents with forward + compensating actions, plus a barrier coordination primitive
- **Barrier (NEW):** Atomic counter tracks compensation completions — saga resolves to 'failed' only when all compensations finish
- **Test cases:** 3 checkouts — all succeed, payment fails (release inventory), shipping fails (refund payment + release inventory)
- **Key insight:** The barrier primitive prevents premature saga resolution while compensations are still running
