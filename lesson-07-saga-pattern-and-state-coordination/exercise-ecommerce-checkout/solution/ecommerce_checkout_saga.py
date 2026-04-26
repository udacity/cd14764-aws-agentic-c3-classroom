"""
ecommerce_checkout_saga.py - EXERCISE SOLUTION (Student-Led)
==============================================================
Module 7 Exercise: Build a Saga with Compensations for E-Commerce Checkout

Architecture:
    Customer places checkout order
         │
    ┌────┴─────────────────────────────────────────────────┐
    │  Saga Orchestrator (Python, NOT LLM-driven)           │
    │  Forward: Inventory → Payment → Shipping (sequential) │
    │  Compensate: reverse order on failure                  │
    └────┬─────────────────────────────────────────────────┘
         │
    ┌────┴─────────────────────────────────────────────────┐
    │  Saga State Machine (DynamoDB)                        │
    │  checkout_id (PK) | steps[] | overall_status | lock   │
    │  + Barrier counter: compensations_completed           │
    │  Saga resolves to 'failed' only when barrier reached  │
    └────┬─────────────────────────────────────────────────┘
         │
    Three checkout agents (each has forward + compensating action):
    ┌────┴─────────────────────────────────────────────────┐
    │ InventoryAgent:  reserve_items   / release_items      │
    │ PaymentAgent:    charge_card     / refund_card         │
    │ ShippingAgent:   schedule_delivery / cancel_delivery   │
    └──────────────────────────────────────────────────────┘

Same saga pattern as the demo (travel_booking_saga.py),
with one addition:
  BARRIER COORDINATION — an atomic counter that each compensation
  increments. Saga resolves to 'failed' only when the counter
  equals the number of steps to compensate.

  Production: DynamoDB atomic counter via ADD expression:
    table.update_item(
        Key={'checkout_id': id},
        UpdateExpression='ADD compensations_completed :one',
        ExpressionAttributeValues={':one': 1},
    )

Tech Stack:
  - Python 3.11+
  - Strands Agents SDK (Agent class, @tool decorator)
  - Amazon Bedrock (Nova Lite for all agents)
  - DynamoDB saga state (real AWS resource — created by CloudFormation)
"""

import json
import re
import time
import logging
import os
import boto3
from decimal import Decimal
from datetime import datetime, timezone
from dotenv import load_dotenv
from botocore.exceptions import ClientError
from strands import Agent, tool
from strands.models import BedrockModel

load_dotenv()

logging.basicConfig(level=logging.WARNING)


def clean_response(text: str) -> str:
    """Strip <thinking>...</thinking> tags from Nova model outputs."""
    return re.sub(r"<thinking>.*?</thinking>\s*", "", str(text), flags=re.DOTALL).strip()


def run_agent_with_retry(agent_builder, prompt: str, max_retries: int = 3) -> float:
    """Run an agent with retry logic for transient Bedrock errors.
    Uses exponential backoff (1s, 2s, 4s) to handle throttling."""
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
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
NOVA_LITE_MODEL = os.environ.get("NOVA_LITE_MODEL", "amazon.nova-lite-v1:0")

# ─────────────────────────────────────────────────────
# SAMPLE CHECKOUT DATA
# ─────────────────────────────────────────────────────
CHECKOUTS = [
    {
        "checkout_id": "CHK-001",
        "customer": "Alice Chen",
        "items": [
            {"sku": "LAPTOP-001", "name": "Pro Laptop 15\"", "qty": 1, "price": 1299.99},
            {"sku": "CASE-042", "name": "Laptop Sleeve", "qty": 1, "price": 49.99},
        ],
        "payment": {"method": "credit_card", "last4": "4242", "token": "tok_visa_success"},
        "shipping": {"address": "123 Main St, Seattle, WA 98101", "method": "express"},
        "simulate_failure": None,  # All succeed
    },
    {
        "checkout_id": "CHK-002",
        "customer": "Bob Martinez",
        "items": [
            {"sku": "PHONE-007", "name": "SmartPhone X", "qty": 2, "price": 899.99},
            {"sku": "CHARGER-01", "name": "Wireless Charger", "qty": 2, "price": 39.99},
        ],
        "payment": {"method": "credit_card", "last4": "0000", "token": "tok_insufficient_funds"},
        "shipping": {"address": "456 Oak Ave, Portland, OR 97201", "method": "standard"},
        "simulate_failure": "payment",  # Payment fails → release inventory
    },
    {
        "checkout_id": "CHK-003",
        "customer": "Carol Davis",
        "items": [
            {"sku": "DESK-100", "name": "Standing Desk", "qty": 1, "price": 599.99},
            {"sku": "MONITOR-22", "name": "4K Monitor 27\"", "qty": 1, "price": 449.99},
        ],
        "payment": {"method": "credit_card", "last4": "1234", "token": "tok_visa_success"},
        "shipping": {"address": "PO Box 999, Nowhere, XX 00000", "method": "express"},
        "simulate_failure": "shipping",  # Shipping fails → refund + release inventory
    },
]


# ═══════════════════════════════════════════════════════
#  DYNAMODB — Saga State Machine + Barrier
#  Real AWS DynamoDB resource (created by CloudFormation)
# ═══════════════════════════════════════════════════════

def to_dynamo(obj):
    """Convert Python objects to DynamoDB-compatible types (float→Decimal)."""
    return json.loads(json.dumps(obj), parse_float=Decimal)


def _dynamo_default(o):
    """Convert Decimal to int if whole number, float otherwise."""
    if isinstance(o, Decimal):
        return int(o) if o == int(o) else float(o)
    raise TypeError(f"Object of type {type(o)} is not JSON serializable")

def from_dynamo(obj):
    """Convert DynamoDB types back to Python (Decimal→int or float)."""
    return json.loads(json.dumps(obj, default=_dynamo_default))


# DynamoDB checkout saga table (real AWS resource — created by CloudFormation)
CHECKOUT_SAGA_TABLE = os.environ.get("CHECKOUT_SAGA_TABLE", "lesson-07-saga-checkout-saga")
dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
checkout_table = dynamodb.Table(CHECKOUT_SAGA_TABLE)


# ═══════════════════════════════════════════════════════
#  SAGA STATE MACHINE + BARRIER
# ═══════════════════════════════════════════════════════

def create_saga(checkout_id: str, steps: list[str]) -> dict:
    """Initialize saga state machine with steps=pending, barrier counter=0."""
    record = {
        "checkout_id": checkout_id,
        "steps": [
            {"name": name, "status": "pending", "forward_ref": None, "compensation_ref": None}
            for name in steps
        ],
        "current_phase": 0,
        "overall_status": "in_progress",
        "locked": False,
        "compensations_needed": 0,      # Set when entering compensation
        "compensations_completed": 0,    # Barrier counter (atomic increment)
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    checkout_table.put_item(Item=to_dynamo(record))
    return record


def update_step(checkout_id: str, step_index: int, updates: dict) -> dict:
    """Update a specific step in the saga."""
    response = checkout_table.get_item(Key={"checkout_id": checkout_id})
    saga = from_dynamo(response.get("Item"))
    saga["steps"][step_index].update(updates)
    saga["updated_at"] = datetime.now(timezone.utc).isoformat()
    checkout_table.put_item(Item=to_dynamo(saga))
    return saga


def acquire_lock(checkout_id: str) -> bool:
    """Acquire distributed lock before compensation."""
    try:
        checkout_table.update_item(
            Key={"checkout_id": checkout_id},
            UpdateExpression="SET locked = :true_val",
            ConditionExpression="locked = :false_val",
            ExpressionAttributeValues={":true_val": True, ":false_val": False},
        )
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            print(f"      [Lock] Failed to acquire lock for {checkout_id}")
            return False
        raise


def release_lock(checkout_id: str):
    """Release lock after compensation completes."""
    checkout_table.update_item(
        Key={"checkout_id": checkout_id},
        UpdateExpression="SET locked = :false_val",
        ExpressionAttributeValues={":false_val": False},
    )


def increment_barrier(checkout_id: str) -> tuple[int, int]:
    """Increment barrier counter. Returns (completed, needed). Saga resolves 'failed' when completed==needed."""
    response = checkout_table.update_item(
        Key={"checkout_id": checkout_id},
        UpdateExpression="ADD compensations_completed :one",
        ExpressionAttributeValues={":one": 1},
        ReturnValues="ALL_NEW",
    )
    item = from_dynamo(response["Attributes"])
    completed = int(item["compensations_completed"])
    needed = int(item["compensations_needed"])
    return completed, needed


def get_saga(checkout_id: str) -> dict | None:
    """Read current saga state."""
    response = checkout_table.get_item(Key={"checkout_id": checkout_id})
    item = response.get("Item")
    return from_dynamo(item) if item else None

# ═══════════════════════════════════════════════════════
#  CHECKOUT AGENTS — Each has forward + compensating action
#
#  InventoryAgent:  reserve_items   / release_items
#  PaymentAgent:    charge_card     / refund_card
#  ShippingAgent:   schedule_delivery / cancel_delivery
# ═══════════════════════════════════════════════════════

def build_inventory_agent(items: list, checkout_id: str,
                          cancel_mode: bool = False) -> Agent:
    """Agent for inventory reservation / release."""

    model = BedrockModel(model_id=NOVA_LITE_MODEL, region_name=AWS_REGION, temperature=0.0)

    if cancel_mode:
        system_prompt = f"""You are an inventory release agent. Your ONLY job:
1. Call release_items with checkout_id '{checkout_id}'
2. Report: Inventory released for {checkout_id}
Do NOT add any other commentary."""

        @tool
        def release_items(checkout_id: str) -> str:
            """Release reserved inventory (compensating transaction).

            Args:
                checkout_id: The checkout ID

            Returns:
                JSON with release confirmation
            """
            comp_ref = f"REL-{checkout_id.split('-')[1]}"
            update_step(checkout_id, 0, {
                "status": "compensated",
                "compensation_ref": comp_ref,
            })

            # Increment barrier
            completed, needed = increment_barrier(checkout_id)
            print(f"      [Barrier] {completed}/{needed} compensations done")

            released = [{"sku": i["sku"], "qty": i["qty"]} for i in items]
            return json.dumps({
                "checkout_id": checkout_id,
                "action": "release_items",
                "released": released,
                "comp_ref": comp_ref,
            }, indent=2)

        return Agent(model=model, system_prompt=system_prompt, tools=[release_items])

    else:
        system_prompt = f"""You are an inventory reservation agent. Your ONLY job:
1. Call reserve_items with checkout_id '{checkout_id}'
2. Report: Items reserved for {checkout_id}
Do NOT add any other commentary."""

        @tool
        def reserve_items(checkout_id: str) -> str:
            """Reserve inventory for the checkout.

            Args:
                checkout_id: The checkout ID

            Returns:
                JSON with reservation confirmation
            """
            forward_ref = f"RSV-{checkout_id.split('-')[1]}-{int(time.time()) % 10000}"
            reserved = [{"sku": i["sku"], "name": i["name"], "qty": i["qty"]} for i in items]

            update_step(checkout_id, 0, {
                "status": "completed",
                "forward_ref": forward_ref,
            })

            return json.dumps({
                "checkout_id": checkout_id,
                "action": "reserve_items",
                "reserved": reserved,
                "forward_ref": forward_ref,
                "status": "confirmed",
            }, indent=2)

        return Agent(model=model, system_prompt=system_prompt, tools=[reserve_items])


def build_payment_agent(payment_data: dict, total: float, checkout_id: str,
                        simulate_failure: bool = False,
                        cancel_mode: bool = False) -> Agent:
    """Agent for payment processing / refund."""

    model = BedrockModel(model_id=NOVA_LITE_MODEL, region_name=AWS_REGION, temperature=0.0)

    if cancel_mode:
        system_prompt = f"""You are a payment refund agent. Your ONLY job:
1. Call refund_card with checkout_id '{checkout_id}'
2. Report: Payment refunded for {checkout_id}
Do NOT add any other commentary."""

        @tool
        def refund_card(checkout_id: str) -> str:
            """Refund a previously charged card (compensating transaction).

            Args:
                checkout_id: The checkout ID

            Returns:
                JSON with refund confirmation
            """
            comp_ref = f"RFND-{checkout_id.split('-')[1]}"
            update_step(checkout_id, 1, {
                "status": "compensated",
                "compensation_ref": comp_ref,
            })

            # Increment barrier
            completed, needed = increment_barrier(checkout_id)
            print(f"      [Barrier] {completed}/{needed} compensations done")

            return json.dumps({
                "checkout_id": checkout_id,
                "action": "refund_card",
                "amount": total,
                "last4": payment_data["last4"],
                "comp_ref": comp_ref,
            }, indent=2)

        return Agent(model=model, system_prompt=system_prompt, tools=[refund_card])

    else:
        system_prompt = f"""You are a payment processing agent. Your ONLY job:
1. Call charge_card with checkout_id '{checkout_id}'
2. Report: Payment charged for {checkout_id} OR Payment failed for {checkout_id}
Do NOT add any other commentary."""

        @tool
        def charge_card(checkout_id: str) -> str:
            """Charge the customer's card.

            Args:
                checkout_id: The checkout ID

            Returns:
                JSON with payment result
            """
            if simulate_failure:
                update_step(checkout_id, 1, {"status": "failed"})
                return json.dumps({
                    "checkout_id": checkout_id,
                    "action": "charge_card",
                    "status": "failed",
                    "reason": "Insufficient funds",
                    "last4": payment_data["last4"],
                }, indent=2)

            forward_ref = f"PAY-{checkout_id.split('-')[1]}-{int(time.time()) % 10000}"
            update_step(checkout_id, 1, {
                "status": "completed",
                "forward_ref": forward_ref,
            })

            return json.dumps({
                "checkout_id": checkout_id,
                "action": "charge_card",
                "amount": total,
                "last4": payment_data["last4"],
                "forward_ref": forward_ref,
                "status": "confirmed",
            }, indent=2)

        return Agent(model=model, system_prompt=system_prompt, tools=[charge_card])


def build_shipping_agent(shipping_data: dict, checkout_id: str,
                         simulate_failure: bool = False,
                         cancel_mode: bool = False) -> Agent:
    """Agent for shipping scheduling / cancellation."""

    model = BedrockModel(model_id=NOVA_LITE_MODEL, region_name=AWS_REGION, temperature=0.0)

    if cancel_mode:
        system_prompt = f"""You are a shipping cancellation agent. Your ONLY job:
1. Call cancel_delivery with checkout_id '{checkout_id}'
2. Report: Delivery cancelled for {checkout_id}
Do NOT add any other commentary."""

        @tool
        def cancel_delivery(checkout_id: str) -> str:
            """Cancel a scheduled delivery (compensating transaction).

            Args:
                checkout_id: The checkout ID

            Returns:
                JSON with cancellation confirmation
            """
            comp_ref = f"CXDEL-{checkout_id.split('-')[1]}"
            update_step(checkout_id, 2, {
                "status": "compensated",
                "compensation_ref": comp_ref,
            })

            # Increment barrier
            completed, needed = increment_barrier(checkout_id)
            print(f"      [Barrier] {completed}/{needed} compensations done")

            return json.dumps({
                "checkout_id": checkout_id,
                "action": "cancel_delivery",
                "comp_ref": comp_ref,
            }, indent=2)

        return Agent(model=model, system_prompt=system_prompt, tools=[cancel_delivery])

    else:
        system_prompt = f"""You are a shipping scheduling agent. Your ONLY job:
1. Call schedule_delivery with checkout_id '{checkout_id}'
2. Report: Delivery scheduled for {checkout_id} OR Delivery failed for {checkout_id}
Do NOT add any other commentary."""

        @tool
        def schedule_delivery(checkout_id: str) -> str:
            """Schedule delivery for the order.

            Args:
                checkout_id: The checkout ID

            Returns:
                JSON with delivery scheduling result
            """
            if simulate_failure:
                update_step(checkout_id, 2, {"status": "failed"})
                return json.dumps({
                    "checkout_id": checkout_id,
                    "action": "schedule_delivery",
                    "status": "failed",
                    "reason": "Address undeliverable",
                    "address": shipping_data["address"],
                }, indent=2)

            forward_ref = f"SHIP-{checkout_id.split('-')[1]}-{int(time.time()) % 10000}"
            update_step(checkout_id, 2, {
                "status": "completed",
                "forward_ref": forward_ref,
            })

            return json.dumps({
                "checkout_id": checkout_id,
                "action": "schedule_delivery",
                "address": shipping_data["address"],
                "method": shipping_data["method"],
                "forward_ref": forward_ref,
                "status": "confirmed",
            }, indent=2)

        return Agent(model=model, system_prompt=system_prompt, tools=[schedule_delivery])


# ═══════════════════════════════════════════════════════
#  SAGA ORCHESTRATOR — Forward execution + compensation + barrier
# ═══════════════════════════════════════════════════════

def run_checkout_saga(checkout: dict):
    """
    Execute a full saga for an e-commerce checkout.

    Forward execution:
        Inventory → Payment → Shipping (sequential)
    Compensation on failure:
        Reverse order — compensate completed steps only
    Barrier:
        Saga resolves to 'failed' only when all compensations complete
    """
    checkout_id = checkout["checkout_id"]
    fail_at = checkout.get("simulate_failure")

    # Calculate total
    subtotal = sum(i["price"] * i["qty"] for i in checkout["items"])
    tax = round(subtotal * 0.08, 2)
    total = round(subtotal + tax, 2)

    print(f"\n  Creating saga state machine...")
    saga = create_saga(checkout_id, ["inventory", "payment", "shipping"])
    print(f"    State: {[s['name'] + '=' + s['status'] for s in saga['steps']]}")
    print(f"    Subtotal: ${subtotal:.2f}, Tax: ${tax:.2f}, Total: ${total:.2f}")

    # ── Forward Execution ────────────────────────────
    agents_config = [
        {
            "name": "inventory",
            "index": 0,
            "builder": lambda: build_inventory_agent(checkout["items"], checkout_id),
            "prompt": f"Reserve items for checkout {checkout_id}",
        },
        {
            "name": "payment",
            "index": 1,
            "builder": lambda: build_payment_agent(
                checkout["payment"], total, checkout_id,
                simulate_failure=(fail_at == "payment")
            ),
            "prompt": f"Charge card for checkout {checkout_id}",
        },
        {
            "name": "shipping",
            "index": 2,
            "builder": lambda: build_shipping_agent(
                checkout["shipping"], checkout_id,
                simulate_failure=(fail_at == "shipping")
            ),
            "prompt": f"Schedule delivery for checkout {checkout_id}",
        },
    ]

    failed_step = None

    for agent_config in agents_config:
        name = agent_config["name"]
        idx = agent_config["index"]

        update_step(checkout_id, idx, {"status": "executing"})
        checkout_table.update_item(
            Key={"checkout_id": checkout_id},
            UpdateExpression="SET current_phase = :val",
            ExpressionAttributeValues={":val": idx},
        )

        print(f"\n  [{idx + 1}/3] {name.title()}Agent (forward)...")
        try:
            t = run_agent_with_retry(agent_config["builder"], agent_config["prompt"])
        except Exception as e:
            print(f"    AGENT ERROR: {e}")
            update_step(checkout_id, idx, {"status": "failed"})
            failed_step = idx
            break

        saga = get_saga(checkout_id)
        step = saga["steps"][idx]

        if step["status"] == "failed":
            print(f"    FAILED: {name} step failed")
            failed_step = idx
            break
        else:
            print(f"    OK: {step.get('forward_ref', '?')} ({t:.1f}s)")

    # ── Check Result ─────────────────────────────────
    saga = get_saga(checkout_id)

    if failed_step is None:
        checkout_table.update_item(
            Key={"checkout_id": checkout_id},
            UpdateExpression="SET overall_status = :val",
            ExpressionAttributeValues={":val": "completed"},
        )
        print(f"\n  ✓ Checkout {checkout_id} COMPLETED — order confirmed!")
        return get_saga(checkout_id)

    # ── Compensation Phase with Barrier ──────────────
    print(f"\n  ✗ Step '{agents_config[failed_step]['name']}' failed — starting compensation...")
    checkout_table.update_item(
        Key={"checkout_id": checkout_id},
        UpdateExpression="SET overall_status = :val",
        ExpressionAttributeValues={":val": "compensating"},
    )

    # Acquire distributed lock
    print(f"  Acquiring compensation lock...")
    if not acquire_lock(checkout_id):
        print(f"  ERROR: Could not acquire lock")
        return get_saga(checkout_id)
    print(f"    Lock acquired")

    # Find completed steps
    completed_steps = [
        (i, s) for i, s in enumerate(saga["steps"])
        if s["status"] == "completed"
    ]
    completed_steps.reverse()

    # Set barrier target
    checkout_table.update_item(
        Key={"checkout_id": checkout_id},
        UpdateExpression="SET compensations_needed = :val",
        ExpressionAttributeValues={":val": len(completed_steps)},
    )
    print(f"  Barrier set: need {len(completed_steps)} compensation(s) to resolve")
    print(f"  Compensating {len(completed_steps)} completed step(s) in reverse order...")

    compensation_builders = {
        "inventory": lambda: build_inventory_agent(checkout["items"], checkout_id, cancel_mode=True),
        "payment": lambda: build_payment_agent(checkout["payment"], total, checkout_id, cancel_mode=True),
        "shipping": lambda: build_shipping_agent(checkout["shipping"], checkout_id, cancel_mode=True),
    }

    # Prompts must match the actual tool names so the LLM calls the right tool
    compensation_prompts = {
        "inventory": f"Release items for checkout {checkout_id}",
        "payment": f"Refund card for checkout {checkout_id}",
        "shipping": f"Cancel delivery for checkout {checkout_id}",
    }

    total_refund = 0.0
    for idx, step in completed_steps:
        name = step["name"]
        update_step(checkout_id, idx, {"status": "compensating"})

        print(f"\n  [COMPENSATE] {name.title()}Agent (cancel)...")
        builder = compensation_builders[name]
        prompt = compensation_prompts[name]

        try:
            t = run_agent_with_retry(builder, prompt)
            saga_after = get_saga(checkout_id)
            comp_step = saga_after["steps"][idx]
            print(f"    Compensated: {comp_step.get('compensation_ref', '?')} ({t:.1f}s)")

            if name == "payment":
                total_refund += total

        except Exception as e:
            print(f"    COMPENSATION FAILED: {e}")

    # Release lock
    release_lock(checkout_id)
    print(f"\n  Lock released")

    # Check barrier — did all compensations complete?
    saga_final = get_saga(checkout_id)
    barrier_done = saga_final["compensations_completed"]
    barrier_needed = saga_final["compensations_needed"]

    if barrier_done >= barrier_needed:
        checkout_table.update_item(
            Key={"checkout_id": checkout_id},
            UpdateExpression="SET overall_status = :val",
            ExpressionAttributeValues={":val": "failed"},
        )
        print(f"  Barrier reached ({barrier_done}/{barrier_needed}) — saga resolved to 'failed'")
    else:
        print(f"  WARNING: Barrier NOT reached ({barrier_done}/{barrier_needed}) — "
              f"some compensations may be incomplete")

    if total_refund > 0:
        print(f"  Total refund: ${total_refund:.2f}")

    return get_saga(checkout_id)


# ═══════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("  E-Commerce Checkout Saga — Module 7 Exercise")
    print("  Saga Pattern with Compensating Transactions + Barrier")
    print("  3 Checkout Agents: Inventory → Payment → Shipping")
    print("=" * 70)

    results = []

    for checkout in CHECKOUTS:
        print(f"\n{'━' * 70}")
        subtotal = sum(i["price"] * i["qty"] for i in checkout["items"])
        items_str = ", ".join(f"{i['name']} x{i['qty']}" for i in checkout["items"])
        print(f"  {checkout['checkout_id']} — {checkout['customer']}")
        print(f"    Items: {items_str} | Subtotal: ${subtotal:.2f}")
        print(f"    Payment: ****{checkout['payment']['last4']} | Shipping: {checkout['shipping']['method']}")
        if checkout['simulate_failure']:
            print(f"    ⚠ Failure scenario: {checkout['simulate_failure']} will fail")
        print(f"{'━' * 70}")

        result = run_checkout_saga(checkout)
        results.append(result)

        # Print state machine
        print(f"\n  {result['checkout_id']} | Status: {result['overall_status']}")
        for step in result["steps"]:
            fwd = step.get("forward_ref") or "—"
            comp = step.get("compensation_ref") or "—"
            print(f"    {step['name']:<12} {step['status']:<14} fwd={fwd:<18} comp={comp}")
        barrier_c = result.get("compensations_completed", 0)
        barrier_n = result.get("compensations_needed", 0)
        if barrier_n > 0:
            print(f"    Barrier: {barrier_c}/{barrier_n} compensations")

    # ── Summary ──────────────────────────────────────────
    print(f"\n{'═' * 70}")
    print("  SAGA PATTERN SUMMARY")
    print(f"{'═' * 70}")

    for result in results:
        status_icon = "✓" if result["overall_status"] == "completed" else "✗"
        compensated = sum(1 for s in result["steps"] if s["status"] == "compensated")
        barrier = f" (barrier: {result['compensations_completed']}/{result['compensations_needed']})" if result['compensations_needed'] > 0 else ""
        print(f"  {status_icon} {result['checkout_id']}: {result['overall_status']}"
              f" ({compensated} step(s) compensated){barrier}")

    print(f"\n  Key Insights (exercise adds BARRIER to demo's saga pattern):")
    print(f"  1. SAGA PATTERN — sequence of local transactions, each reversible (same as demo)")
    print(f"  2. COMPENSATING TRANSACTIONS — undo completed steps on failure (same as demo)")
    print(f"  3. REVERSE ORDER — compensate last-completed first (same as demo)")
    print(f"  4. DISTRIBUTED LOCK — prevent concurrent compensation (same as demo)")
    print(f"  5. BARRIER COORDINATION — atomic counter ensures saga doesn't resolve")
    print(f"     prematurely while compensations are still running (NEW)")
    print(f"     Production: DynamoDB ADD expression for atomic counter\n")


if __name__ == "__main__":
    main()
