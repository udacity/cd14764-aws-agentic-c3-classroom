# Lesson 7: Implementing the Saga Pattern with Compensating Transactions

This lesson teaches the Saga pattern for multi-agent workflows that span multiple services without distributed transactions. Each agent provides both a forward action and a compensating action. When any step fails, the saga orchestrator runs compensating transactions in reverse order to undo previously completed steps. A DynamoDB-backed state machine tracks progress and enables crash recovery.

## Setup

**1. Copy and configure `.env`**

```bash
cp .env.example .env
```

Open `.env` and fill in:
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` — from your classroom AWS gateway
- `AWS_REGION` — match the region shown in your classroom console (commonly `us-west-1` or `us-west-2`)

**2. Deploy infrastructure**

Via the AWS Console: CloudFormation → Create stack → Upload `infrastructure/stack.yaml` → Stack name: `lesson-07-saga`

Or with Python (if no AWS CLI is available):

```bash
python3 -c "
import boto3, os
from dotenv import load_dotenv
load_dotenv()
cf = boto3.client('cloudformation', region_name=os.environ['AWS_REGION'])
cf.create_stack(StackName='lesson-07-saga', TemplateBody=open('infrastructure/stack.yaml').read())
print('Stack creation started — wait ~30 seconds before running the demo')
"
```

**3. Common issues**

| Error | Cause | Fix |
|-------|-------|-----|
| `NoCredentialsError` | Credentials missing or expired | Re-copy credentials from AWS gateway into `.env` |
| `ResourceNotFoundException` | Stack not deployed or wrong region | Check `AWS_REGION` in `.env` matches where stack was deployed |
| `ValidationException: on-demand throughput isn't supported` | Wrong model ID | Use `us.amazon.nova-lite-v1:0` (not bare `amazon.nova-lite-v1:0`) in `.env` |

## Folder Structure

```
lesson-07-saga-pattern-and-state-coordination/
├── README.md
├── .env.example
├── infrastructure/
│   └── stack.yaml
├── demo-travel-booking/
│   ├── README.md
│   └── travel_booking_saga.py
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
- **State Machine:** DynamoDB tracks saga progress (pending → executing → completed → compensating → compensated)
- **Distributed Lock:** Conditional write prevents concurrent compensation attempts
- **Test cases:** 3 packages — all succeed, car fails (compensate hotel + flight), hotel fails (compensate flight only)
- **Key insight:** Compensating transactions run in reverse order — last-completed step compensates first

## Exercise: Saga Pattern for E-Commerce Checkout (Student-led)
- **Domain:** E-commerce checkout (inventory reservation, payment processing, shipping scheduling)
- **Architecture:** 3 checkout agents with forward + compensating actions, plus a barrier coordination primitive
- **Barrier (NEW):** Atomic counter tracks compensation completions — saga resolves to 'failed' only when all compensations finish
- **Test cases:** 3 checkouts — all succeed, payment fails (release inventory), shipping fails (refund payment + release inventory)
- **Key insight:** The barrier primitive prevents premature saga resolution while compensations are still running

## Cleanup

The CloudFormation stack creates two DynamoDB tables (SagaState + CheckoutSaga), both billed on-demand. Delete them when you're done via the AWS Console (CloudFormation → Stacks → lesson-07-saga → Delete), or with Python:

```bash
python3 -c "
import boto3, os
from dotenv import load_dotenv
load_dotenv()
cf = boto3.client('cloudformation', region_name=os.environ['AWS_REGION'])
cf.delete_stack(StackName='lesson-07-saga')
print('Stack deletion started')
"
```
