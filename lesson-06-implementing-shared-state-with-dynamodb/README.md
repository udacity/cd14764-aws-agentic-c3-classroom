# Lesson 6: Implementing Shared State with DynamoDB and AgentCore Memory

This lesson teaches how to share mutable state across multiple agents using optimistic locking, and how to maintain cross-session conversational context using AgentCore Memory. The demo and exercise each use a real DynamoDB table (deployed per activity) for transactional state, plus an in-memory simulation of AgentCore Memory for conversational context.

Each activity folder below has its own `infrastructure/`, `.env.example`, and `README.md` — open the one you're working on for setup steps.

## Folder Structure

```
lesson-06-implementing-shared-state-with-dynamodb/
├── README.md
├── demo-ride-sharing/
│   ├── README.md
│   ├── .env.example
│   ├── infrastructure/stack.yaml      ← TripState table
│   └── ride_sharing_state.py
└── exercise-food-delivery/
    ├── starter/
    │   ├── README.md
    │   ├── .env.example
    │   ├── infrastructure/stack.yaml  ← OrderState table
    │   └── food_delivery_state.py
    └── solution/
        ├── README.md
        ├── .env.example
        ├── infrastructure/stack.yaml  ← same as starter; deploy only if you skipped the starter
        └── food_delivery_state.py
```

- **Demo (ride-sharing):** 3 worker agents updating the same trip record with optimistic locking, plus cross-session memory for preferred drivers.
- **Exercise (food delivery):** 4 worker agents updating the same order record, plus state recovery when the restaurant rejects.
