"""
food_delivery_state.py - EXERCISE STARTER (Student-Led)
=========================================================
Module 6 Exercise: Build Shared State for a Food Delivery Order System

Architecture:
    Customer places order
         │
    ┌────┴──────────────────────────────────────────────┐
    │  Shared State (DynamoDB)                           │
    │  order_id (PK) | version | restaurant | driver |   │
    │  total_price | status | ttl                        │
    │  Optimistic locking: version-based conditional     │
    │  writes (ConditionExpression) prevent lost updates  │
    │  TTL: auto-expire completed orders after 2 hours   │
    └────┬──────────────────────────────────────────────┘
         │
    Four agents update the SAME record:
    ┌────┴──────────────────────────────────────────┐
    │ RestaurantConfirmAgent → writes status (accept/reject) │
    │ DriverAssignAgent     → writes driver field    │
    │ PriceCalculatorAgent  → writes total_price     │
    │ StatusTrackerAgent    → writes progress updates│
    └───────────────────────────────────────────────┘
         │
    Cross-Session Memory (AgentCore Memory):
    ┌────┴──────────────────────────────────────────┐
    │ SESSION_SUMMARY strategy → customer preferences │
    │ Remembers preferred driver across orders        │
    └─────────────────────────────────────────────────┘

Same shared state pattern as the demo (ride_sharing_state.py),
with two additions:
  1. STATE RECOVERY: If restaurant rejects, cleanup partial updates
  2. FOUR agents instead of three (more concurrent conflicts)

Instructions:
  - Follow the demo pattern (ride_sharing_state.py)
  - Look for TODO 1-18 below
  - State management functions: create/update/get + recovery
  - Each build_*_agent function needs: model, system_prompt, Agent()
  - SimulatedDynamoDB and customer_memory are provided

Note: This lesson uses in-memory simulations to keep the exercise self-contained.
The simulations preserve the exact same API patterns and behaviors you'll use
with real DynamoDB and AgentCore Memory in the capstone project.
"""

import json
import re
import time
import threading
import logging
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from strands import Agent, tool
from strands.models import BedrockModel

logging.basicConfig(level=logging.WARNING)


# ─────────────────────────────────────────────────────
# HELPERS (provided)
# ─────────────────────────────────────────────────────

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
# SAMPLE ORDERS
# ─────────────────────────────────────────────────────
ORDERS = [
    {
        "order_id": "ORD-001",
        "customer_id": "CUST-42",
        "customer_name": "Alice Chen",
        "restaurant": "Tokyo Ramen House",
        "items": [
            {"name": "Tonkotsu Ramen", "price": 16.50, "qty": 1},
            {"name": "Gyoza (6pc)", "price": 8.00, "qty": 2},
        ],
        "address": "123 Main St, Apt 4B",
        "payment_method": "credit_card",
        "simulate_rejection": False,
    },
    {
        "order_id": "ORD-002",
        "customer_id": "CUST-77",
        "customer_name": "Bob Martinez",
        "restaurant": "Bella Italia",
        "items": [
            {"name": "Margherita Pizza", "price": 14.00, "qty": 1},
            {"name": "Caesar Salad", "price": 10.00, "qty": 1},
            {"name": "Tiramisu", "price": 9.00, "qty": 1},
        ],
        "address": "456 Oak Ave, Suite 200",
        "payment_method": "credit_card",
        "simulate_rejection": False,
    },
    {
        "order_id": "ORD-003",
        "customer_id": "CUST-42",  # Same customer — tests cross-session memory
        "customer_name": "Alice Chen",
        "restaurant": "Tokyo Ramen House",
        "items": [
            {"name": "Spicy Miso Ramen", "price": 17.50, "qty": 1},
        ],
        "address": "123 Main St, Apt 4B",
        "payment_method": "credit_card",
        "simulate_rejection": True,  # Restaurant rejects — triggers state recovery
    },
]

AVAILABLE_DRIVERS = [
    {"driver_id": "DRV-301", "name": "Carlos Rivera", "rating": 4.9, "vehicle": "Honda Civic"},
    {"driver_id": "DRV-302", "name": "Maria Santos", "rating": 4.85, "vehicle": "Toyota Corolla"},
    {"driver_id": "DRV-303", "name": "James Wilson", "rating": 4.7, "vehicle": "Ford Focus"},
]

DELIVERY_FEE = 4.99
TAX_RATE = 0.08


# ═══════════════════════════════════════════════════════
#  SIMULATED DYNAMODB — Shared State Store (provided)
#
#  This in-memory simulation preserves the key DynamoDB behaviors:
#    - Atomic conditional writes (version check)
#    - ConditionalCheckFailedException on conflict
#    - Thread-safe operations via threading.Lock
#    - TTL field support
#
#  Production equivalent (boto3):
#    dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
#    table = dynamodb.Table('OrderState')
#    # Table created via CloudFormation with:
#    #   KeySchema: [{AttributeName: order_id, KeyType: HASH}]
#    #   BillingMode: PAY_PER_REQUEST
#    #   TimeToLiveSpecification: {Enabled: true, AttributeName: ttl}
# ═══════════════════════════════════════════════════════

class ConditionalCheckFailedException(Exception):
    """Raised when a conditional write fails (version mismatch).

    Production: This is botocore.exceptions.ClientError with
    error code 'ConditionalCheckFailedException'.
    """
    pass


class SimulatedDynamoDB:
    """
    In-memory DynamoDB simulator with optimistic locking support.

    Production equivalent:
        dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
        table = dynamodb.Table('OrderState')
    """

    def __init__(self):
        self._tables = {}       # table_name -> {pk_value -> record}
        self._lock = threading.Lock()  # Simulates DynamoDB's atomic writes
        self._write_log = []    # Audit trail of all writes

    def create_table(self, table_name: str):
        """Create a table (simulated).

        Production: Table is pre-created via CloudFormation stack.
        """
        self._tables[table_name] = {}

    def put_item(self, table_name: str, item: dict):
        """Insert a new record.

        Production: table.put_item(Item=item)
        """
        with self._lock:
            pk = item.get("order_id")
            self._tables[table_name][pk] = item.copy()
            self._write_log.append({
                "op": "put_item", "table": table_name, "pk": pk,
                "version": item.get("version", 0), "timestamp": time.time(),
            })

    def get_item(self, table_name: str, pk_value: str) -> dict | None:
        """Read a record.

        Production: table.get_item(Key={'order_id': pk_value})['Item']
        """
        with self._lock:
            record = self._tables.get(table_name, {}).get(pk_value)
            return record.copy() if record else None

    def update_item_conditional(self, table_name: str, pk_value: str,
                                 updates: dict, expected_version: int) -> dict:
        """Conditional update with optimistic locking.

        This is the KEY PATTERN for Module 6:
        - Checks that version == expected_version
        - If YES: applies updates, increments version
        - If NO: raises ConditionalCheckFailedException

        Production equivalent:
            table.update_item(
                Key={'order_id': pk_value},
                UpdateExpression='SET #f0 = :v0, #v = :new_ver, #ua = :ts',
                ConditionExpression='#v = :expected_ver',
                ExpressionAttributeNames={'#v': 'version', '#f0': 'driver', '#ua': 'updated_at'},
                ExpressionAttributeValues={
                    ':v0': driver_info, ':expected_ver': N,
                    ':new_ver': N + 1, ':ts': timestamp
                },
                ReturnValues='ALL_NEW',
            )
        """
        with self._lock:
            record = self._tables.get(table_name, {}).get(pk_value)
            if not record:
                raise KeyError(f"Record {pk_value} not found in {table_name}")

            current_version = record.get("version", 0)
            if current_version != expected_version:
                self._write_log.append({
                    "op": "CONFLICT", "table": table_name, "pk": pk_value,
                    "expected": expected_version, "actual": current_version,
                    "timestamp": time.time(),
                })
                raise ConditionalCheckFailedException(
                    f"Version conflict: expected {expected_version}, "
                    f"found {current_version}"
                )

            # Apply updates and increment version
            record.update(updates)
            record["version"] = current_version + 1
            record["updated_at"] = datetime.now(timezone.utc).isoformat()

            self._write_log.append({
                "op": "update_item", "table": table_name, "pk": pk_value,
                "version": f"{current_version} → {record['version']}",
                "fields": list(updates.keys()), "timestamp": time.time(),
            })

            return record.copy()


# Global shared state store
db = SimulatedDynamoDB()
db.create_table("OrderState")

# ═══════════════════════════════════════════════════════
#  SIMULATED AGENTCORE MEMORY — Cross-Session Customer Preferences (provided)
#
#  In production, AgentCore Memory is a managed service:
#    agentcore_control = boto3.client('bedrock-agentcore-control')
#    agentcore_control.create_memory(
#        name='food-delivery-memory',
#        memoryStrategies=[{
#            'summaryMemoryStrategy': {
#                'name': 'session_summary',
#                'description': 'Summarize customer preferences across orders'
#            }
#        }],
#        eventExpiryDuration=7,  # 7-day retention
#    )
#
#  The SESSION_SUMMARY strategy automatically extracts customer
#  preferences (favorite restaurant, preferred driver, usual address)
#  from conversation events and makes them available in future sessions.
#
#  Here we simulate this with a simple dict for determinism.
# ═══════════════════════════════════════════════════════
customer_memory = {}


# ═══════════════════════════════════════════════════════
#  ORDER STATE MANAGEMENT — CRUD with Optimistic Locking + Recovery
#  Follow the same create/update/get pattern from the demo,
#  then add recover_order() for state recovery (NEW).
# ═══════════════════════════════════════════════════════

# TODO 1: Implement create_order(order_data)
#   - Build a record dict with: order_id, customer_id, customer_name,
#     restaurant, items, address, payment_method, driver=None,
#     total_price=None, status="pending", progress=[], version=0,
#     ttl (2 hours from now), created_at (UTC ISO)
#   - Call db.put_item("OrderState", record)
#   - Return the record
#   Hint: Same pattern as demo's create_trip(), but with order fields
def create_order(order_data: dict) -> dict:
    pass


# TODO 2: Implement update_order(order_id, updates, max_retries=3)
#   - Loop up to max_retries times:
#     a) Read current: db.get_item("OrderState", order_id)
#     b) Get expected_version from current["version"]
#     c) Try: db.update_item_conditional("OrderState", order_id, updates, expected_version)
#     d) On ConditionalCheckFailedException: wait and retry (0.1 * 2^attempt)
#   - Return the updated record
#   Hint: Same as demo's update_trip() — the KEY pattern
def update_order(order_id: str, updates: dict, max_retries: int = 3) -> dict:
    pass


# TODO 3: Implement get_order(order_id)
#   - Return db.get_item("OrderState", order_id)
#   Hint: Same as demo's get_trip()
def get_order(order_id: str) -> dict | None:
    pass


# TODO 4: Implement recover_order(order_id)
#   - This is the NEW pattern (not in the demo!)
#   - Call update_order to set: driver=None, total_price=None,
#     status="cancelled", progress=["Order rejected by restaurant",
#     "Partial updates cleaned up"]
#   - Print recovery messages
#   - Return the cleaned-up record
#   Hint: This handles the case where some agents wrote partial data
#         before the restaurant rejected the order
def recover_order(order_id: str) -> dict:
    pass


# ═══════════════════════════════════════════════════════
#  WORKER AGENTS — 4 agents, each updates different fields
#  Each agent needs: BedrockModel, system_prompt, @tool, Agent()
#  Follow the same pattern as the demo's worker agents.
# ═══════════════════════════════════════════════════════

# TODO 5-7: Build RestaurantConfirmAgent
def build_restaurant_confirm_agent(simulate_rejection: bool = False) -> Agent:
    """Worker: Restaurant confirms or rejects the order."""

    # TODO 5: Create BedrockModel with NOVA_LITE_MODEL, temperature=0.0
    model = None  # Replace with BedrockModel(...)

    # TODO 6: Write system prompt — agent should call confirm_order with order_id,
    #   then report "<order_id> confirmed/rejected by restaurant"
    system_prompt = ""  # Replace with system prompt

    @tool
    def confirm_order(order_id: str) -> str:
        """
        Restaurant confirms or rejects the order.

        Args:
            order_id: The order ID

        Returns:
            JSON with confirmation result
        """
        order = get_order(order_id)
        if not order:
            return json.dumps({"error": f"Order {order_id} not found"})

        if simulate_rejection:
            status = "rejected"
            reason = "Restaurant is closing early today"
        else:
            status = "confirmed"
            reason = "Order accepted, preparing now"

        update_order(order_id, {"status": status})

        result = {
            "order_id": order_id,
            "restaurant": order["restaurant"],
            "status": status,
            "reason": reason,
        }
        return json.dumps(result, indent=2)

    # TODO 7: Build and return Agent with model, system_prompt, tools=[confirm_order]
    return None  # Replace with Agent(...)


# TODO 8-10: Build DriverAssignAgent
def build_driver_assign_agent() -> Agent:
    """Worker: Assigns a delivery driver."""

    # TODO 8: Create BedrockModel with NOVA_LITE_MODEL, temperature=0.0
    model = None  # Replace with BedrockModel(...)

    # TODO 9: Write system prompt — agent should call assign_driver with order_id,
    #   then report "Driver <name> assigned for <order_id>"
    system_prompt = ""  # Replace with system prompt

    @tool
    def assign_driver(order_id: str) -> str:
        """Assign the best available driver to the order."""
        order = get_order(order_id)
        if not order:
            return json.dumps({"error": f"Order {order_id} not found"})

        # Check customer memory for preferred driver
        # Production: AgentCore Memory SESSION_SUMMARY injects this
        # into the agent's conversation context automatically
        cust_id = order.get("customer_id")
        preferred = customer_memory.get(cust_id, {}).get("preferred_driver")

        if preferred and any(d["driver_id"] == preferred for d in AVAILABLE_DRIVERS):
            best = next(d for d in AVAILABLE_DRIVERS if d["driver_id"] == preferred)
            reason = "preferred driver (from memory)"
        else:
            best = max(AVAILABLE_DRIVERS, key=lambda d: d["rating"])
            reason = "highest rated available"

        driver_info = {
            "driver_id": best["driver_id"],
            "name": best["name"],
            "rating": best["rating"],
            "vehicle": best["vehicle"],
            "match_reason": reason,
        }
        update_order(order_id, {"driver": driver_info})

        # Update customer memory (simulates AgentCore Memory SESSION_SUMMARY)
        if cust_id not in customer_memory:
            customer_memory[cust_id] = {}
        customer_memory[cust_id]["preferred_driver"] = best["driver_id"]
        customer_memory[cust_id]["last_driver"] = best["name"]
        customer_memory[cust_id]["favorite_restaurant"] = order["restaurant"]
        customer_memory[cust_id]["usual_address"] = order["address"]

        return json.dumps({**driver_info, "order_id": order_id}, indent=2)

    # TODO 10: Build and return Agent with model, system_prompt, tools=[assign_driver]
    return None  # Replace with Agent(...)


# TODO 11-13: Build PriceCalculatorAgent
def build_price_calculator_agent() -> Agent:
    """Worker: Calculates total price with delivery fee and tax."""

    # TODO 11: Create BedrockModel with NOVA_LITE_MODEL, temperature=0.0
    model = None  # Replace with BedrockModel(...)

    # TODO 12: Write system prompt — agent should call calculate_price with order_id,
    #   then report "Total for <order_id>: $<amount>"
    system_prompt = ""  # Replace with system prompt

    @tool
    def calculate_price(order_id: str) -> str:
        """Calculate total order price including delivery fee and tax."""
        order = get_order(order_id)
        if not order:
            return json.dumps({"error": f"Order {order_id} not found"})

        subtotal = sum(item["price"] * item["qty"] for item in order["items"])
        tax = round(subtotal * TAX_RATE, 2)
        total = round(subtotal + tax + DELIVERY_FEE, 2)

        price_info = {
            "subtotal": subtotal,
            "tax": tax,
            "delivery_fee": DELIVERY_FEE,
            "total": total,
        }
        update_order(order_id, {"total_price": price_info})

        return json.dumps({**price_info, "order_id": order_id}, indent=2)

    # TODO 13: Build and return Agent with model, system_prompt, tools=[calculate_price]
    return None  # Replace with Agent(...)


# TODO 14-16: Build StatusTrackerAgent
def build_status_tracker_agent() -> Agent:
    """Worker: Updates order progress/status."""

    # TODO 14: Create BedrockModel with NOVA_LITE_MODEL, temperature=0.0
    model = None  # Replace with BedrockModel(...)

    # TODO 15: Write system prompt — agent should call update_status with order_id,
    #   then report "Status for <order_id>: <status>"
    system_prompt = ""  # Replace with system prompt

    @tool
    def update_status(order_id: str) -> str:
        """Update order progress tracking."""
        order = get_order(order_id)
        if not order:
            return json.dumps({"error": f"Order {order_id} not found"})

        progress = order.get("progress", [])
        progress.append(f"Order processed at {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")

        if order.get("driver") and order.get("total_price"):
            progress.append("All agents completed — ready for pickup")
            new_status = "ready"
        else:
            new_status = order.get("status", "pending")

        update_order(order_id, {"progress": progress, "status": new_status})

        return json.dumps({
            "order_id": order_id, "status": new_status,
            "progress_count": len(progress),
        }, indent=2)

    # TODO 16: Build and return Agent with model, system_prompt, tools=[update_status]
    return None  # Replace with Agent(...)


# ═══════════════════════════════════════════════════════
#  MAIN — 3 scenarios
#  TODO 17: Wire up sequential scenario (Scenario 1)
#  TODO 18: Wire up concurrent scenario (Scenario 2)
#  Scenario 3 (state recovery) is provided for you.
# ═══════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("  Food Delivery Order System — Module 6 Exercise")
    print("  Shared State with Optimistic Locking + State Recovery")
    print("  4 Agents updating the SAME record")
    print("=" * 70)

    # ══════════════════════════════════════════════════
    # SCENARIO 1: Sequential Updates (basic pattern)
    # ══════════════════════════════════════════════════
    order1 = ORDERS[0]
    print(f"\n{'━' * 70}")
    print(f"  SCENARIO 1: Sequential Updates (no conflicts)")
    print(f"  Order: {order1['order_id']} — {order1['restaurant']}")
    items_str = ", ".join(f"{i['name']} x{i['qty']}" for i in order1["items"])
    print(f"  Items: {items_str}")
    print(f"  Customer: {order1['customer_name']}")
    print(f"{'━' * 70}")

    # TODO 17: Sequential scenario — run all 4 agents one at a time
    #   a) Call create_order(order1) and print version + TTL
    #   b) Run RestaurantConfirmAgent: run_agent_with_retry(
    #        lambda: build_restaurant_confirm_agent(False),
    #        f"Confirm order {order1['order_id']}")
    #   c) Run DriverAssignAgent: run_agent_with_retry(build_driver_assign_agent, ...)
    #   d) Run PriceCalculatorAgent: run_agent_with_retry(build_price_calculator_agent, ...)
    #   e) Run StatusTrackerAgent: run_agent_with_retry(build_status_tracker_agent, ...)
    #   f) Print final order state summary using get_order()
    #   Hint: Use get_order() between each step to print intermediate state
    #         Same flow as demo's Scenario 1, but with 4 agents instead of 3
    pass  # Replace with sequential scenario implementation

    # ══════════════════════════════════════════════════
    # SCENARIO 2: Concurrent Updates (optimistic locking)
    # ══════════════════════════════════════════════════
    order2 = ORDERS[1]
    print(f"\n{'━' * 70}")
    print(f"  SCENARIO 2: Concurrent Updates (with conflicts)")
    print(f"  Order: {order2['order_id']} — {order2['restaurant']}")
    print(f"  All 4 agents run in PARALLEL — expect version conflicts!")
    print(f"{'━' * 70}")

    # TODO 18: Concurrent scenario — run all 4 agents in parallel
    #   a) Call create_order(order2) and print version
    #   b) Count conflicts before: sum(1 for e in db._write_log if e["op"] == "CONFLICT")
    #   c) Use ThreadPoolExecutor(max_workers=4) to run all 4 agents at once
    #   d) Count new conflicts (after - before)
    #   e) Print final order state summary with conflict count + parallel time
    #   Hint: Same as demo's concurrent scenario, but with 4 futures instead of 3
    pass  # Replace with concurrent scenario implementation

    # ══════════════════════════════════════════════════
    # SCENARIO 3: State Recovery (restaurant rejection)
    # This is provided for you — study how recover_order() cleans up.
    # Also demonstrates cross-session memory (same customer as ORD-001).
    # ══════════════════════════════════════════════════
    order3 = ORDERS[2]
    print(f"\n{'━' * 70}")
    print(f"  SCENARIO 3: State Recovery (restaurant rejection + returning customer)")
    print(f"  Order: {order3['order_id']} — {order3['restaurant']}")
    print(f"  Restaurant will REJECT — triggers cleanup of partial state")
    print(f"  Customer: {order3['customer_name']} (same as ORD-001 — tests memory)")
    print(f"{'━' * 70}")

    # Show customer memory before
    cust_id = order3["customer_id"]
    mem = customer_memory.get(cust_id, {})
    print(f"\n  Customer memory for {cust_id}: {json.dumps(mem, indent=4)}")

    record3 = create_order(order3)
    print(f"  Created: {order3['order_id']} (version {record3['version']})")

    # Simulate: Driver and Price agents run first (partial updates)
    print(f"\n  [Partial] DriverAssignAgent runs first (should use preferred driver)...")
    run_agent_with_retry(build_driver_assign_agent,
                        f"Assign driver for order {order3['order_id']}")
    state3 = get_order(order3["order_id"])
    driver3 = state3.get("driver", {})
    print(f"    Driver: {driver3.get('name', '?')} — {driver3.get('match_reason', '?')} (v{state3['version']})")

    print(f"  [Partial] PriceCalculatorAgent runs...")
    run_agent_with_retry(build_price_calculator_agent,
                        f"Calculate price for order {order3['order_id']}")
    state3 = get_order(order3["order_id"])
    print(f"    Price: ${state3['total_price']['total']:.2f} (v{state3['version']})")

    # Restaurant rejects!
    print(f"\n  [REJECT] RestaurantConfirmAgent — restaurant rejects order!")
    run_agent_with_retry(
        lambda: build_restaurant_confirm_agent(True),
        f"Confirm order {order3['order_id']}")
    state3 = get_order(order3["order_id"])
    print(f"    Status: {state3['status']} (v{state3['version']})")

    # State recovery — cleanup partial updates
    print(f"\n  [RECOVERY] Cleaning up partial state...")
    recovered = recover_order(order3["order_id"])

    print(f"\n  ┌─── Order State (After Recovery) ───────────────┐")
    print(f"  │ Order:    {recovered['order_id']} (v{recovered['version']})")
    print(f"  │ Status:   {recovered['status']}")
    print(f"  │ Driver:   {recovered['driver']}")
    print(f"  │ Price:    {recovered['total_price']}")
    print(f"  │ Progress: {recovered['progress']}")
    print(f"  └────────────────────────────────────────────────┘")

    # ── Summary ──────────────────────────────────────────
    print(f"\n{'═' * 70}")
    print("  SHARED STATE SUMMARY")
    print(f"{'═' * 70}")

    total_writes = sum(1 for e in db._write_log if e["op"] in ("put_item", "update_item"))
    total_conflicts = sum(1 for e in db._write_log if e["op"] == "CONFLICT")

    print(f"  Total writes:    {total_writes}")
    print(f"  Total conflicts: {total_conflicts}")
    if (total_writes + total_conflicts) > 0:
        print(f"  Conflict rate:   "
              f"{total_conflicts/(total_writes+total_conflicts)*100:.0f}%")
    print(f"  All resolved:    YES (via optimistic locking + retry)")

    print(f"\n  Customer Memory (simulates AgentCore Memory SESSION_SUMMARY):")
    for cid, mem in customer_memory.items():
        print(f"    {cid}: preferred_driver={mem.get('preferred_driver', '?')}, "
              f"last_driver={mem.get('last_driver', '?')}, "
              f"favorite_restaurant={mem.get('favorite_restaurant', '?')}")

    print(f"\n  Key Insight: Exercise adds STATE RECOVERY to the demo's pattern:")
    print(f"  1. OPTIMISTIC LOCKING — version + ConditionExpression (same as demo)")
    print(f"  2. RETRY ON CONFLICT  — re-read → new version → retry (same as demo)")
    print(f"  3. STATE RECOVERY     — reject → cleanup partial updates → cancel (NEW)")
    print(f"  4. TTL                — auto-expire completed orders (2 hours)")
    print(f"  5. AGENTCORE MEMORY   — customer preferences persist across orders")
    print(f"     (SESSION_SUMMARY strategy, 7-day retention)\n")


if __name__ == "__main__":
    main()
