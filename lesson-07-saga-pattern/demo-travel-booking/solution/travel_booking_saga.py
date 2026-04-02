"""
travel_booking_saga.py - DEMO (Instructor-Led)
================================================
Module 7 Demo: Implementing the Saga Pattern for Travel Booking

Architecture:
    Customer books vacation package
         │
    ┌────┴─────────────────────────────────────────────────┐
    │  Saga Orchestrator (Python, NOT LLM-driven)           │
    │  Forward: Flight → Hotel → Car (sequential)           │
    │  Compensate: reverse order on failure                  │
    └────┬─────────────────────────────────────────────────┘
         │
    ┌────┴─────────────────────────────────────────────────┐
    │  Saga State Machine (Simulated DynamoDB)              │
    │  saga_id (PK) | current_phase | steps[] | lock       │
    │  Each step: {name, status, booking_ref, comp_ref}     │
    │  Statuses: pending → executing → completed            │
    │            → compensating → compensated                │
    └────┬─────────────────────────────────────────────────┘
         │
    Three booking agents (each has forward + compensating action):
    ┌────┴─────────────────────────────────────────────────┐
    │ FlightAgent:  book_flight / cancel_flight             │
    │ HotelAgent:   book_hotel  / cancel_hotel              │
    │ CarAgent:     book_car    / cancel_car                │
    └──────────────────────────────────────────────────────┘

Saga Pattern:
    1. Forward execution: call each agent sequentially
       - On success: update state machine, move to next step
       - On failure: transition to "compensating" mode
    2. Compensation: iterate completed steps in REVERSE order
       - Each agent has a cancel_X tool (the compensating action)
       - Update step status: completed → compensating → compensated
    3. Distributed lock: conditional write on lock field before compensating
       - Prevents concurrent compensation attempts
    4. State persistence: crash recovery reads state and resumes

    Why sagas? Distributed systems can't use traditional ACID transactions
    across services. Sagas provide eventual consistency via compensating
    transactions.

Key Concepts (Module 7):
  1. SAGA: sequence of local transactions, each with a compensating action
  2. COMPENSATING TRANSACTION: undoes a completed step on failure
  3. REVERSE ORDER: compensate step 2 before step 1
  4. STATE MACHINE: tracks saga progress (pending → completed → compensated)
  5. DISTRIBUTED LOCK: prevents concurrent compensations
  6. CRASH RECOVERY: read state machine, resume from last recorded phase

Tech Stack:
  - Python 3.11+
  - Strands Agents SDK (Agent class, @tool decorator)
  - Amazon Bedrock (Nova Lite for all agents)
  - Simulated DynamoDB (in-memory; production uses boto3 DynamoDB)

Note: This lesson uses in-memory simulations to keep the exercise self-contained.
Production-mapping comments show the exact boto3 API calls used in real systems.
"""

import json
import re
import time
import threading
import logging
from datetime import datetime, timezone
from strands import Agent, tool
from strands.models import BedrockModel

logging.basicConfig(level=logging.WARNING)


def clean_response(text: str) -> str:
    """Strip <thinking>...</thinking> tags from Nova model outputs."""
    return re.sub(r"<thinking>.*?</thinking>\s*", "", str(text), flags=re.DOTALL).strip()


def run_agent_with_retry(agent_builder, prompt: str, max_retries: int = 3) -> float:
    """Run an agent with retry logic for transient Bedrock errors."""
    for attempt in range(max_retries):
        try:
            agent = agent_builder()
            t = time.time()
            agent(prompt)
            return time.time() - t
        except Exception as e:
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                print(f"    [Retry {attempt + 1}/{max_retries}] {e.__class__.__name__}, waiting {wait}s...")
                time.sleep(wait)
            else:
                print(f"    [Failed] {e.__class__.__name__} after {max_retries} attempts")
                raise


# ─────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────
AWS_REGION = "us-east-1"
NOVA_LITE_MODEL = "amazon.nova-lite-v1:0"

# ─────────────────────────────────────────────────────
# SAMPLE BOOKING DATA
# ─────────────────────────────────────────────────────
TRAVEL_PACKAGES = [
    {
        "saga_id": "SAGA-001",
        "customer": "Alice Chen",
        "trip": "NYC → Paris Vacation",
        "flight": {"route": "JFK → CDG", "class": "business", "price": 2400.00},
        "hotel": {"name": "Le Marais Hotel", "nights": 5, "price": 1750.00},
        "car": {"type": "midsize", "days": 5, "price": 350.00},
        "simulate_failure": None,  # All succeed
    },
    {
        "saga_id": "SAGA-002",
        "customer": "Bob Martinez",
        "trip": "LAX → Tokyo Adventure",
        "flight": {"route": "LAX → NRT", "class": "economy", "price": 1200.00},
        "hotel": {"name": "Shinjuku Grand", "nights": 7, "price": 2100.00},
        "car": {"type": "compact", "days": 7, "price": 420.00},
        "simulate_failure": "car",  # Car fails → compensate hotel, then flight
    },
    {
        "saga_id": "SAGA-003",
        "customer": "Carol Davis",
        "trip": "ORD → London Business",
        "flight": {"route": "ORD → LHR", "class": "first", "price": 5500.00},
        "hotel": {"name": "The Savoy", "nights": 3, "price": 3600.00},
        "car": {"type": "luxury", "days": 3, "price": 900.00},
        "simulate_failure": "hotel",  # Hotel fails → compensate flight only
    },
]


# ═══════════════════════════════════════════════════════
#  SIMULATED DYNAMODB — Saga State Machine
#  Production: dynamodb = boto3.resource('dynamodb'); table = dynamodb.Table('SagaState')
# ═══════════════════════════════════════════════════════

class ConditionalCheckFailedException(Exception):
    """Version mismatch on conditional write. Production: botocore.exceptions.ClientError."""
    pass


class SimulatedDynamoDB:
    """In-memory DynamoDB simulator for saga state machine."""

    def __init__(self):
        self._tables = {}
        self._lock = threading.Lock()

    def create_table(self, table_name: str):
        self._tables[table_name] = {}

    def put_item(self, table_name: str, item: dict):
        with self._lock:
            pk = item.get("saga_id") or item.get("checkout_id")
            self._tables[table_name][pk] = item.copy()

    def get_item(self, table_name: str, pk_value: str) -> dict | None:
        with self._lock:
            record = self._tables.get(table_name, {}).get(pk_value)
            return record.copy() if record else None

    def update_item_conditional(self, table_name: str, pk_value: str,
                                 updates: dict, condition_field: str,
                                 expected_value) -> dict:
        """Conditional update for distributed locking. Production: table.update_item with ConditionExpression."""
        with self._lock:
            record = self._tables.get(table_name, {}).get(pk_value)
            if not record:
                raise KeyError(f"Record {pk_value} not found")
            if record.get(condition_field) != expected_value:
                raise ConditionalCheckFailedException(
                    f"Condition failed: {condition_field} is {record.get(condition_field)}, "
                    f"expected {expected_value}"
                )
            record.update(updates)
            record["updated_at"] = datetime.now(timezone.utc).isoformat()
            return record.copy()

    def update_item(self, table_name: str, pk_value: str, updates: dict) -> dict:
        with self._lock:
            record = self._tables.get(table_name, {}).get(pk_value)
            if not record:
                raise KeyError(f"Record {pk_value} not found")
            record.update(updates)
            record["updated_at"] = datetime.now(timezone.utc).isoformat()
            return record.copy()


# Global state store
db = SimulatedDynamoDB()
db.create_table("SagaState")


# ═══════════════════════════════════════════════════════
#  SAGA STATE MACHINE
#
#  STEP 1: create_saga()     — Initialize state machine
#  STEP 2: update_step()     — Transition a step's status
#  STEP 3: acquire_lock()    — Distributed lock for compensation
#  STEP 4: release_lock()    — Release lock after compensation
#  STEP 5: get_saga()        — Read current state
# ═══════════════════════════════════════════════════════

def create_saga(saga_id: str, steps: list[str]) -> dict:
    """STEP 1: Initialize saga state machine with steps=pending, overall_status=in_progress, locked=False."""
    record = {
        "saga_id": saga_id,
        "steps": [
            {"name": name, "status": "pending", "booking_ref": None, "compensation_ref": None}
            for name in steps
        ],
        "current_phase": 0,
        "overall_status": "in_progress",
        "locked": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    db.put_item("SagaState", record)
    return record


def update_step(saga_id: str, step_index: int, updates: dict) -> dict:
    """STEP 2: Update step status (pending→executing→completed or completed→compensating→compensated)."""
    saga = db.get_item("SagaState", saga_id)
    saga["steps"][step_index].update(updates)
    db.update_item("SagaState", saga_id, {"steps": saga["steps"]})
    return db.get_item("SagaState", saga_id)


def acquire_lock(saga_id: str) -> bool:
    """STEP 3: Acquire distributed lock (conditional write, only if locked==False)."""
    try:
        db.update_item_conditional(
            "SagaState", saga_id,
            {"locked": True}, "locked", False
        )
        return True
    except ConditionalCheckFailedException:
        print(f"      [Lock] Failed to acquire lock for {saga_id} — already locked")
        return False


def release_lock(saga_id: str):
    """STEP 4: Release lock after compensation completes."""
    db.update_item("SagaState", saga_id, {"locked": False})

def get_saga(saga_id: str) -> dict | None:
    """STEP 5: Read current saga state."""
    return db.get_item("SagaState", saga_id)

# ═══════════════════════════════════════════════════════
#  BOOKING AGENTS — Each has forward + compensating action
#
#  FlightAgent:  book_flight / cancel_flight
#  HotelAgent:   book_hotel  / cancel_hotel
#  CarAgent:     book_car    / cancel_car
# ═══════════════════════════════════════════════════════

def build_flight_agent(flight_data: dict, saga_id: str,
                       cancel_mode: bool = False) -> Agent:
    """Booking agent for flights (forward or compensating)."""

    model = BedrockModel(model_id=NOVA_LITE_MODEL, region_name=AWS_REGION, temperature=0.0)

    if cancel_mode:
        system_prompt = f"""You are a flight cancellation agent. Your ONLY job:
1. Call cancel_flight with saga_id '{saga_id}'
2. Report: Flight cancelled for {saga_id}
Do NOT add any other commentary."""

        @tool
        def cancel_flight(saga_id: str) -> str:
            """Cancel a previously booked flight (compensating transaction).

            Args:
                saga_id: The saga ID

            Returns:
                JSON with cancellation confirmation
            """
            saga = get_saga(saga_id)
            flight_step = saga["steps"][0]
            booking_ref = flight_step.get("booking_ref", "UNKNOWN")

            # Simulated cancellation (idempotent — safe to call twice)
            cancel_ref = f"CANCEL-FLT-{saga_id.split('-')[1]}"

            update_step(saga_id, 0, {
                "status": "compensated",
                "compensation_ref": cancel_ref,
            })

            return json.dumps({
                "saga_id": saga_id,
                "action": "cancel_flight",
                "original_booking": booking_ref,
                "cancel_ref": cancel_ref,
                "refund": flight_data["price"],
            }, indent=2)

        return Agent(model=model, system_prompt=system_prompt, tools=[cancel_flight])

    else:
        system_prompt = f"""You are a flight booking agent. Your ONLY job:
1. Call book_flight with saga_id '{saga_id}'
2. Report: Flight booked for {saga_id}
Do NOT add any other commentary."""

        @tool
        def book_flight(saga_id: str) -> str:
            """Book a flight for the travel package.

            Args:
                saga_id: The saga ID

            Returns:
                JSON with booking confirmation
            """
            booking_ref = f"FLT-{saga_id.split('-')[1]}-{int(time.time()) % 10000}"

            update_step(saga_id, 0, {
                "status": "completed",
                "booking_ref": booking_ref,
            })

            return json.dumps({
                "saga_id": saga_id,
                "action": "book_flight",
                "route": flight_data["route"],
                "class": flight_data["class"],
                "price": flight_data["price"],
                "booking_ref": booking_ref,
                "status": "confirmed",
            }, indent=2)

        return Agent(model=model, system_prompt=system_prompt, tools=[book_flight])


def build_hotel_agent(hotel_data: dict, saga_id: str,
                      simulate_failure: bool = False,
                      cancel_mode: bool = False) -> Agent:
    """Booking agent for hotels (forward or compensating)."""

    model = BedrockModel(model_id=NOVA_LITE_MODEL, region_name=AWS_REGION, temperature=0.0)

    if cancel_mode:
        system_prompt = f"""You are a hotel cancellation agent. Your ONLY job:
1. Call cancel_hotel with saga_id '{saga_id}'
2. Report: Hotel cancelled for {saga_id}
Do NOT add any other commentary."""

        @tool
        def cancel_hotel(saga_id: str) -> str:
            """Cancel a previously booked hotel (compensating transaction).

            Args:
                saga_id: The saga ID

            Returns:
                JSON with cancellation confirmation
            """
            saga = get_saga(saga_id)
            hotel_step = saga["steps"][1]
            booking_ref = hotel_step.get("booking_ref", "UNKNOWN")

            cancel_ref = f"CANCEL-HTL-{saga_id.split('-')[1]}"

            update_step(saga_id, 1, {
                "status": "compensated",
                "compensation_ref": cancel_ref,
            })

            return json.dumps({
                "saga_id": saga_id,
                "action": "cancel_hotel",
                "original_booking": booking_ref,
                "cancel_ref": cancel_ref,
                "refund": hotel_data["price"],
            }, indent=2)

        return Agent(model=model, system_prompt=system_prompt, tools=[cancel_hotel])

    else:
        system_prompt = f"""You are a hotel booking agent. Your ONLY job:
1. Call book_hotel with saga_id '{saga_id}'
2. Report: Hotel booked for {saga_id} OR Hotel booking failed for {saga_id}
Do NOT add any other commentary."""

        @tool
        def book_hotel(saga_id: str) -> str:
            """Book a hotel for the travel package.

            Args:
                saga_id: The saga ID

            Returns:
                JSON with booking result
            """
            if simulate_failure:
                update_step(saga_id, 1, {"status": "failed"})
                return json.dumps({
                    "saga_id": saga_id,
                    "action": "book_hotel",
                    "hotel": hotel_data["name"],
                    "status": "failed",
                    "reason": "No rooms available for requested dates",
                }, indent=2)

            booking_ref = f"HTL-{saga_id.split('-')[1]}-{int(time.time()) % 10000}"

            update_step(saga_id, 1, {
                "status": "completed",
                "booking_ref": booking_ref,
            })

            return json.dumps({
                "saga_id": saga_id,
                "action": "book_hotel",
                "hotel": hotel_data["name"],
                "nights": hotel_data["nights"],
                "price": hotel_data["price"],
                "booking_ref": booking_ref,
                "status": "confirmed",
            }, indent=2)

        return Agent(model=model, system_prompt=system_prompt, tools=[book_hotel])


def build_car_agent(car_data: dict, saga_id: str,
                    simulate_failure: bool = False,
                    cancel_mode: bool = False) -> Agent:
    """Booking agent for car rental (forward or compensating)."""

    model = BedrockModel(model_id=NOVA_LITE_MODEL, region_name=AWS_REGION, temperature=0.0)

    if cancel_mode:
        system_prompt = f"""You are a car rental cancellation agent. Your ONLY job:
1. Call cancel_car with saga_id '{saga_id}'
2. Report: Car rental cancelled for {saga_id}
Do NOT add any other commentary."""

        @tool
        def cancel_car(saga_id: str) -> str:
            """Cancel a previously booked car rental (compensating transaction).

            Args:
                saga_id: The saga ID

            Returns:
                JSON with cancellation confirmation
            """
            saga = get_saga(saga_id)
            car_step = saga["steps"][2]
            booking_ref = car_step.get("booking_ref", "UNKNOWN")

            cancel_ref = f"CANCEL-CAR-{saga_id.split('-')[1]}"

            update_step(saga_id, 2, {
                "status": "compensated",
                "compensation_ref": cancel_ref,
            })

            return json.dumps({
                "saga_id": saga_id,
                "action": "cancel_car",
                "original_booking": booking_ref,
                "cancel_ref": cancel_ref,
                "refund": car_data["price"],
            }, indent=2)

        return Agent(model=model, system_prompt=system_prompt, tools=[cancel_car])

    else:
        system_prompt = f"""You are a car rental booking agent. Your ONLY job:
1. Call book_car with saga_id '{saga_id}'
2. Report: Car booked for {saga_id} OR Car booking failed for {saga_id}
Do NOT add any other commentary."""

        @tool
        def book_car(saga_id: str) -> str:
            """Book a car rental for the travel package.

            Args:
                saga_id: The saga ID

            Returns:
                JSON with booking result
            """
            if simulate_failure:
                update_step(saga_id, 2, {"status": "failed"})
                return json.dumps({
                    "saga_id": saga_id,
                    "action": "book_car",
                    "type": car_data["type"],
                    "status": "failed",
                    "reason": "No cars available at destination",
                }, indent=2)

            booking_ref = f"CAR-{saga_id.split('-')[1]}-{int(time.time()) % 10000}"

            update_step(saga_id, 2, {
                "status": "completed",
                "booking_ref": booking_ref,
            })

            return json.dumps({
                "saga_id": saga_id,
                "action": "book_car",
                "type": car_data["type"],
                "days": car_data["days"],
                "price": car_data["price"],
                "booking_ref": booking_ref,
                "status": "confirmed",
            }, indent=2)

        return Agent(model=model, system_prompt=system_prompt, tools=[book_car])


# ═══════════════════════════════════════════════════════
#  SAGA ORCHESTRATOR — Forward execution + compensation
#
#  This is a Python orchestrator (NOT LLM-driven).
#  The orchestrator:
#    1. Runs agents sequentially (forward execution)
#    2. Detects failures via state machine
#    3. Acquires distributed lock
#    4. Runs compensating agents in REVERSE order
#    5. Releases lock
# ═══════════════════════════════════════════════════════

def run_saga(package: dict):
    """
    Execute a full saga for a travel booking package.

    Forward execution:
        Flight → Hotel → Car (sequential)
    Compensation on failure:
        Reverse order — compensate completed steps only
    """
    saga_id = package["saga_id"]
    fail_at = package.get("simulate_failure")

    print(f"\n  Creating saga state machine...")
    saga = create_saga(saga_id, ["flight", "hotel", "car"])
    print(f"    State: {[s['name'] + '=' + s['status'] for s in saga['steps']]}")

    # ── Forward Execution ────────────────────────────
    agents_config = [
        {
            "name": "flight",
            "index": 0,
            "builder": lambda: build_flight_agent(package["flight"], saga_id),
            "prompt": f"Book flight for saga {saga_id}",
        },
        {
            "name": "hotel",
            "index": 1,
            "builder": lambda: build_hotel_agent(
                package["hotel"], saga_id,
                simulate_failure=(fail_at == "hotel")
            ),
            "prompt": f"Book hotel for saga {saga_id}",
        },
        {
            "name": "car",
            "index": 2,
            "builder": lambda: build_car_agent(
                package["car"], saga_id,
                simulate_failure=(fail_at == "car")
            ),
            "prompt": f"Book car for saga {saga_id}",
        },
    ]

    failed_step = None

    for agent_config in agents_config:
        name = agent_config["name"]
        idx = agent_config["index"]

        # Mark step as executing
        update_step(saga_id, idx, {"status": "executing"})
        db.update_item("SagaState", saga_id, {"current_phase": idx})

        print(f"\n  [{idx + 1}/3] {name.title()}Agent (forward)...")
        try:
            t = run_agent_with_retry(agent_config["builder"], agent_config["prompt"])
        except Exception as e:
            print(f"    AGENT ERROR: {e}")
            update_step(saga_id, idx, {"status": "failed"})
            failed_step = idx
            break

        # Check if agent reported failure (via state machine)
        saga = get_saga(saga_id)
        step = saga["steps"][idx]

        if step["status"] == "failed":
            print(f"    FAILED: {name} booking failed")
            failed_step = idx
            break
        else:
            print(f"    OK: {step.get('booking_ref', '?')} ({t:.1f}s)")

    # ── Check Result ─────────────────────────────────
    saga = get_saga(saga_id)

    if failed_step is None:
        # All steps succeeded
        db.update_item("SagaState", saga_id, {"overall_status": "completed"})
        print(f"\n  ✓ Saga {saga_id} COMPLETED — all bookings confirmed")
        return get_saga(saga_id)

    # ── Compensation Phase ───────────────────────────
    print(f"\n  ✗ Step '{agents_config[failed_step]['name']}' failed — starting compensation...")
    db.update_item("SagaState", saga_id, {"overall_status": "compensating"})

    # Acquire distributed lock
    print(f"  Acquiring compensation lock...")
    if not acquire_lock(saga_id):
        print(f"  ERROR: Could not acquire lock — another compensator is running")
        return get_saga(saga_id)
    print(f"    Lock acquired")

    # Find completed steps (need compensation) — iterate in REVERSE order
    completed_steps = [
        (i, s) for i, s in enumerate(saga["steps"])
        if s["status"] == "completed"
    ]
    completed_steps.reverse()  # Compensate in reverse order!

    print(f"  Compensating {len(completed_steps)} completed step(s) in reverse order...")

    compensation_builders = {
        "flight": lambda: build_flight_agent(package["flight"], saga_id, cancel_mode=True),
        "hotel": lambda: build_hotel_agent(package["hotel"], saga_id, cancel_mode=True),
        "car": lambda: build_car_agent(package["car"], saga_id, cancel_mode=True),
    }

    total_refund = 0.0
    for idx, step in completed_steps:
        name = step["name"]
        update_step(saga_id, idx, {"status": "compensating"})

        print(f"\n  [COMPENSATE] {name.title()}Agent (cancel)...")
        builder = compensation_builders[name]
        prompt = f"Cancel {name} for saga {saga_id}"

        try:
            t = run_agent_with_retry(builder, prompt)
            saga_after = get_saga(saga_id)
            comp_step = saga_after["steps"][idx]
            print(f"    Compensated: {comp_step.get('compensation_ref', '?')} ({t:.1f}s)")

            # Track refund
            refund = package.get(name, {}).get("price", 0)
            total_refund += refund

        except Exception as e:
            print(f"    COMPENSATION FAILED: {e}")
            # In production: alert, manual intervention needed

    # Release lock
    release_lock(saga_id)
    print(f"\n  Lock released")

    # Update overall status
    db.update_item("SagaState", saga_id, {"overall_status": "failed"})

    saga_final = get_saga(saga_id)
    print(f"  Total refund: ${total_refund:.2f}")

    return saga_final


# ═══════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("  Travel Booking Saga — Module 7 Demo")
    print("  Saga Pattern with Compensating Transactions")
    print("  3 Booking Agents: Flight → Hotel → Car")
    print("=" * 70)

    results = []

    for package in TRAVEL_PACKAGES:
        print(f"\n{'━' * 70}")
        print(f"  {package['saga_id']} — {package['customer']}: {package['trip']}")
        total = package['flight']['price'] + package['hotel']['price'] + package['car']['price']
        print(f"    Flight: {package['flight']['route']} ({package['flight']['class']}) ${package['flight']['price']:.2f}")
        print(f"    Hotel: {package['hotel']['name']} ({package['hotel']['nights']}n) ${package['hotel']['price']:.2f}")
        print(f"    Car: {package['car']['type']} ({package['car']['days']}d) ${package['car']['price']:.2f} | Total: ${total:.2f}")
        if package['simulate_failure']:
            print(f"    ⚠ Failure scenario: {package['simulate_failure']} will fail")
        print(f"{'━' * 70}")

        result = run_saga(package)
        results.append(result)

        # Print state machine
        print(f"\n  Saga {result['saga_id']} | Status: {result['overall_status']}")
        for step in result["steps"]:
            ref = step.get("booking_ref") or "—"
            comp = step.get("compensation_ref") or "—"
            print(f"    {step['name']:<8} {step['status']:<14} book={ref:<20} cancel={comp}")

    # ── Summary ──────────────────────────────────────────
    print(f"\n{'═' * 70}")
    print("  SAGA PATTERN SUMMARY")
    print(f"{'═' * 70}")

    for result in results:
        status_icon = "✓" if result["overall_status"] == "completed" else "✗"
        compensated = sum(1 for s in result["steps"] if s["status"] == "compensated")
        print(f"  {status_icon} {result['saga_id']}: {result['overall_status']}"
              f" ({compensated} step(s) compensated)")

    print(f"\n  Key Insights:")
    print(f"  1. SAGA PATTERN — sequence of local transactions, each reversible")
    print(f"  2. COMPENSATING TRANSACTIONS — undo completed steps on failure")
    print(f"  3. REVERSE ORDER — compensate last-completed first (hotel before flight)")
    print(f"  4. STATE MACHINE — tracks each step: pending → executing → completed/failed")
    print(f"     On compensation: completed → compensating → compensated")
    print(f"  5. DISTRIBUTED LOCK — conditional write prevents concurrent compensation")
    print(f"  6. IDEMPOTENT COMPENSATIONS — safe to retry (cancel twice = same result)")
    print(f"  7. CRASH RECOVERY — read state machine, resume from last recorded phase\n")


if __name__ == "__main__":
    main()
