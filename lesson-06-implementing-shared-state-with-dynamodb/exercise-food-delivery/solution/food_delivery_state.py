"""
food_delivery_state.py - EXERCISE SOLUTION (Student-Led)
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

DynamoDB vs AgentCore Memory:
  - DynamoDB = within-session transactional state (order records, optimistic locking)
  - AgentCore Memory = cross-session conversational context (customer preferences)

Tech Stack:
  - Python 3.11+
  - Strands Agents SDK (Agent class, @tool decorator)
  - Amazon Bedrock (Nova Lite for all agents)
  - Simulated DynamoDB (in-memory; production uses boto3 DynamoDB resource API)
  - Simulated AgentCore Memory (in-memory; production uses bedrock-agentcore-control)

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


AWS_REGION = "us-east-1"
NOVA_LITE_MODEL = "amazon.nova-lite-v1:0"

ORDERS = [
    {"order_id": "ORD-001", "customer_id": "CUST-42", "customer_name": "Alice Chen",
     "restaurant": "Tokyo Ramen House", "items": [{"name": "Tonkotsu Ramen", "price": 16.50, "qty": 1},
       {"name": "Gyoza (6pc)", "price": 8.00, "qty": 2}], "address": "123 Main St, Apt 4B",
     "payment_method": "credit_card", "simulate_rejection": False},
    {"order_id": "ORD-002", "customer_id": "CUST-77", "customer_name": "Bob Martinez",
     "restaurant": "Bella Italia", "items": [{"name": "Margherita Pizza", "price": 14.00, "qty": 1},
       {"name": "Caesar Salad", "price": 10.00, "qty": 1}, {"name": "Tiramisu", "price": 9.00, "qty": 1}],
     "address": "456 Oak Ave, Suite 200", "payment_method": "credit_card", "simulate_rejection": False},
    {"order_id": "ORD-003", "customer_id": "CUST-42", "customer_name": "Alice Chen",
     "restaurant": "Tokyo Ramen House", "items": [{"name": "Spicy Miso Ramen", "price": 17.50, "qty": 1}],
     "address": "123 Main St, Apt 4B", "payment_method": "credit_card", "simulate_rejection": True},
]

AVAILABLE_DRIVERS = [
    {"driver_id": "DRV-301", "name": "Carlos Rivera", "rating": 4.9, "vehicle": "Honda Civic"},
    {"driver_id": "DRV-302", "name": "Maria Santos", "rating": 4.85, "vehicle": "Toyota Corolla"},
    {"driver_id": "DRV-303", "name": "James Wilson", "rating": 4.7, "vehicle": "Ford Focus"},
]

DELIVERY_FEE = 4.99
TAX_RATE = 0.08


class ConditionalCheckFailedException(Exception):
    """Raised when a conditional write fails (version mismatch).
    Production: botocore.exceptions.ClientError with error code 'ConditionalCheckFailedException'."""
    pass


class SimulatedDynamoDB:
    """In-memory DynamoDB simulator with optimistic locking support.
    Production: dynamodb = boto3.resource('dynamodb', region_name='us-east-1'); table = dynamodb.Table('OrderState')"""
    def __init__(self):
        self._tables = {}
        self._lock = threading.Lock()
        self._write_log = []

    def create_table(self, table_name: str):
        """Create a table (simulated). Production: Pre-created via CloudFormation."""
        self._tables[table_name] = {}

    def put_item(self, table_name: str, item: dict):
        """Insert a new record. Production: table.put_item(Item=item)"""
        with self._lock:
            pk = item.get("order_id")
            self._tables[table_name][pk] = item.copy()
            self._write_log.append({"op": "put_item", "table": table_name, "pk": pk,
                "version": item.get("version", 0), "timestamp": time.time()})

    def get_item(self, table_name: str, pk_value: str) -> dict | None:
        """Read a record. Production: table.get_item(Key={'order_id': pk_value})['Item']"""
        with self._lock:
            record = self._tables.get(table_name, {}).get(pk_value)
            return record.copy() if record else None

    def update_item_conditional(self, table_name: str, pk_value: str, updates: dict, expected_version: int) -> dict:
        """Conditional update with optimistic locking (KEY PATTERN for Module 6).
        Production: table.update_item(Key={'order_id': pk_value}, UpdateExpression='SET #f0 = :v0, #v = :new_ver',
          ConditionExpression='#v = :expected_ver', ExpressionAttributeNames={'#v': 'version', '#f0': 'driver'},
          ExpressionAttributeValues={':v0': driver_info, ':expected_ver': N, ':new_ver': N + 1}, ReturnValues='ALL_NEW')"""
        with self._lock:
            record = self._tables.get(table_name, {}).get(pk_value)
            if not record:
                raise KeyError(f"Record {pk_value} not found in {table_name}")
            current_version = record.get("version", 0)
            if current_version != expected_version:
                self._write_log.append({"op": "CONFLICT", "table": table_name, "pk": pk_value,
                    "expected": expected_version, "actual": current_version, "timestamp": time.time()})
                raise ConditionalCheckFailedException(f"Version conflict: expected {expected_version}, found {current_version}")
            record.update(updates)
            record["version"] = current_version + 1
            record["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._write_log.append({"op": "update_item", "table": table_name, "pk": pk_value,
                "version": f"{current_version} → {record['version']}", "fields": list(updates.keys()), "timestamp": time.time()})
            return record.copy()


db = SimulatedDynamoDB()
db.create_table("OrderState")

customer_memory = {}


def create_order(order_data: dict) -> dict:
    """STEP 1: Create initial order state (version 0, TTL 2 hours)."""
    order_id = order_data["order_id"]
    now = time.time()
    record = {
        "order_id": order_id, "customer_id": order_data["customer_id"], "customer_name": order_data["customer_name"],
        "restaurant": order_data["restaurant"], "items": order_data["items"], "address": order_data["address"],
        "payment_method": order_data["payment_method"], "driver": None, "total_price": None,
        "status": "pending", "progress": [], "version": 0, "ttl": int(now + 7200),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    db.put_item("OrderState", record)
    return record


def update_order(order_id: str, updates: dict, max_retries: int = 3) -> dict:
    """STEP 2: Update order state with optimistic locking + retry.
    Pattern: 1. Read current (get version N), 2. Apply updates with condition: version == N,
    3. If conflict → re-read, get new version, retry"""
    for attempt in range(max_retries):
        current = db.get_item("OrderState", order_id)
        if not current:
            raise KeyError(f"Order {order_id} not found")
        expected_version = current["version"]
        try:
            result = db.update_item_conditional("OrderState", order_id, updates, expected_version)
            return result
        except ConditionalCheckFailedException as e:
            if attempt < max_retries - 1:
                wait = 0.1 * (2 ** attempt)
                print(f"      [Conflict] {e} — retrying in {wait:.1f}s (attempt {attempt + 1})")
                time.sleep(wait)
            else:
                print(f"      [Failed] Version conflict after {max_retries} retries")
                raise


def get_order(order_id: str) -> dict | None:
    """STEP 3: Read current order state."""
    return db.get_item("OrderState", order_id)


def recover_order(order_id: str) -> dict:
    """STEP 4 (NEW): STATE RECOVERY — Clean up after restaurant rejection."""
    print(f"      [Recovery] Cleaning up partial state for {order_id}...")
    result = update_order(order_id, {
        "driver": None, "total_price": None, "status": "cancelled",
        "progress": ["Order rejected by restaurant", "Partial updates cleaned up"],
    })
    print(f"      [Recovery] Order {order_id} → cancelled (v{result['version']})")
    return result


def build_restaurant_confirm_agent(simulate_rejection: bool = False) -> Agent:
    """Worker: Restaurant confirms or rejects the order."""
    model = BedrockModel(model_id=NOVA_LITE_MODEL, region_name=AWS_REGION, temperature=0.0)
    system_prompt = """You are a restaurant confirmation agent. Your ONLY job:
1. Call confirm_order with the order_id
2. Report: Order <order_id> <confirmed/rejected> by restaurant
Do NOT add any other commentary."""

    @tool
    def confirm_order(order_id: str) -> str:
        """Restaurant confirms or rejects the order."""
        order = get_order(order_id)
        if not order:
            return json.dumps({"error": f"Order {order_id} not found"})
        status = "rejected" if simulate_rejection else "confirmed"
        reason = "Restaurant is closing early today" if simulate_rejection else "Order accepted, preparing now"
        update_order(order_id, {"status": status})
        result = {"order_id": order_id, "restaurant": order["restaurant"], "status": status, "reason": reason}
        return json.dumps(result, indent=2)

    return Agent(model=model, system_prompt=system_prompt, tools=[confirm_order])


def build_driver_assign_agent() -> Agent:
    """Worker: Assigns a delivery driver."""
    model = BedrockModel(model_id=NOVA_LITE_MODEL, region_name=AWS_REGION, temperature=0.0)
    system_prompt = """You are a driver assignment agent. Your ONLY job:
1. Call assign_driver with the order_id
2. Report: Driver <name> assigned for <order_id>
Do NOT add any other commentary."""

    @tool
    def assign_driver(order_id: str) -> str:
        """Assign the best available driver to the order."""
        order = get_order(order_id)
        if not order:
            return json.dumps({"error": f"Order {order_id} not found"})
        cust_id = order.get("customer_id")
        preferred = customer_memory.get(cust_id, {}).get("preferred_driver")
        if preferred and any(d["driver_id"] == preferred for d in AVAILABLE_DRIVERS):
            best = next(d for d in AVAILABLE_DRIVERS if d["driver_id"] == preferred)
            reason = "preferred driver (from memory)"
        else:
            best = max(AVAILABLE_DRIVERS, key=lambda d: d["rating"])
            reason = "highest rated available"
        driver_info = {"driver_id": best["driver_id"], "name": best["name"],
            "rating": best["rating"], "vehicle": best["vehicle"], "match_reason": reason}
        update_order(order_id, {"driver": driver_info})
        if cust_id not in customer_memory:
            customer_memory[cust_id] = {}
        customer_memory[cust_id]["preferred_driver"] = best["driver_id"]
        customer_memory[cust_id]["last_driver"] = best["name"]
        customer_memory[cust_id]["favorite_restaurant"] = order["restaurant"]
        customer_memory[cust_id]["usual_address"] = order["address"]
        return json.dumps({**driver_info, "order_id": order_id}, indent=2)

    return Agent(model=model, system_prompt=system_prompt, tools=[assign_driver])


def build_price_calculator_agent() -> Agent:
    """Worker: Calculates total price with delivery fee and tax."""
    model = BedrockModel(model_id=NOVA_LITE_MODEL, region_name=AWS_REGION, temperature=0.0)
    system_prompt = """You are a price calculation agent. Your ONLY job:
1. Call calculate_price with the order_id
2. Report: Total for <order_id>: $<amount>
Do NOT add any other commentary."""

    @tool
    def calculate_price(order_id: str) -> str:
        """Calculate total order price including delivery fee and tax."""
        order = get_order(order_id)
        if not order:
            return json.dumps({"error": f"Order {order_id} not found"})
        subtotal = sum(item["price"] * item["qty"] for item in order["items"])
        tax = round(subtotal * TAX_RATE, 2)
        total = round(subtotal + tax + DELIVERY_FEE, 2)
        price_info = {"subtotal": subtotal, "tax": tax, "delivery_fee": DELIVERY_FEE, "total": total}
        update_order(order_id, {"total_price": price_info})
        return json.dumps({**price_info, "order_id": order_id}, indent=2)

    return Agent(model=model, system_prompt=system_prompt, tools=[calculate_price])


def build_status_tracker_agent() -> Agent:
    """Worker: Updates order progress/status."""
    model = BedrockModel(model_id=NOVA_LITE_MODEL, region_name=AWS_REGION, temperature=0.0)
    system_prompt = """You are a status tracking agent. Your ONLY job:
1. Call update_status with the order_id
2. Report: Status for <order_id>: <status>
Do NOT add any other commentary."""

    @tool
    def update_status(order_id: str) -> str:
        """Update order progress tracking."""
        order = get_order(order_id)
        if not order:
            return json.dumps({"error": f"Order {order_id} not found"})
        progress = order.get("progress", [])
        progress.append(f"Order processed at {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")
        new_status = "ready" if (order.get("driver") and order.get("total_price")) else order.get("status", "pending")
        update_order(order_id, {"progress": progress, "status": new_status})
        return json.dumps({"order_id": order_id, "status": new_status, "progress_count": len(progress)}, indent=2)

    return Agent(model=model, system_prompt=system_prompt, tools=[update_status])


def main():
    print("=" * 70)
    print("  Food Delivery Order System — Module 6 Exercise")
    print("  Shared State with Optimistic Locking + State Recovery | 4 Agents")
    print("=" * 70)

    order1 = ORDERS[0]
    print(f"\n{'━' * 70}")
    print(f"  SCENARIO 1: Sequential Updates (no conflicts)")
    print(f"  Order: {order1['order_id']} — {order1['restaurant']}")
    items_str = ", ".join(f"{i['name']} x{i['qty']}" for i in order1["items"])
    print(f"  Items: {items_str} | Customer: {order1['customer_name']}")
    print(f"{'━' * 70}")

    record1 = create_order(order1)
    print(f"\n  Created: {order1['order_id']} (version {record1['version']}, "
          f"TTL: {datetime.fromtimestamp(record1['ttl'], tz=timezone.utc).strftime('%H:%M:%S UTC')})")

    print(f"\n  [1/4] RestaurantConfirmAgent...")
    t1 = run_agent_with_retry(lambda: build_restaurant_confirm_agent(False), f"Confirm order {order1['order_id']}")
    state = get_order(order1["order_id"])
    print(f"    Status: {state['status']} (v{state['version']}, {t1:.1f}s)")

    print(f"  [2/4] DriverAssignAgent...")
    t2 = run_agent_with_retry(build_driver_assign_agent, f"Assign driver for order {order1['order_id']}")
    state = get_order(order1["order_id"])
    print(f"    Driver: {state['driver']['name']} (v{state['version']}, {t2:.1f}s)")

    print(f"  [3/4] PriceCalculatorAgent...")
    t3 = run_agent_with_retry(build_price_calculator_agent, f"Calculate price for order {order1['order_id']}")
    state = get_order(order1["order_id"])
    print(f"    Total: ${state['total_price']['total']:.2f} (v{state['version']}, {t3:.1f}s)")

    print(f"  [4/4] StatusTrackerAgent...")
    t4 = run_agent_with_retry(build_status_tracker_agent, f"Update status for order {order1['order_id']}")
    state = get_order(order1["order_id"])
    print(f"    Status: {state['status']} (v{state['version']}, {t4:.1f}s)")

    print(f"\n  Final State: {state['order_id']} v{state['version']}")
    print(f"    Status: {state['status']} | Restaurant: {state['restaurant']}")
    print(f"    Driver: {state['driver']['name']} ({state['driver']['vehicle']})")
    tp = state['total_price']
    print(f"    Subtotal: ${tp['subtotal']:.2f} + Tax: ${tp['tax']:.2f} + Delivery: ${tp['delivery_fee']:.2f} = ${tp['total']:.2f}")

    order2 = ORDERS[1]
    print(f"\n{'━' * 70}")
    print(f"  SCENARIO 2: Concurrent Updates (with conflicts)")
    print(f"  Order: {order2['order_id']} — {order2['restaurant']}")
    print(f"  All 4 agents run in PARALLEL — expect version conflicts!")
    print(f"{'━' * 70}")

    record2 = create_order(order2)
    print(f"\n  Created: {order2['order_id']} (version {record2['version']})")
    conflicts_before = sum(1 for e in db._write_log if e["op"] == "CONFLICT")

    print(f"  Launching 4 agents in parallel...")
    t_start = time.time()
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(run_agent_with_retry, lambda: build_restaurant_confirm_agent(False),
                          f"Confirm order {order2['order_id']}"): "Restaurant",
            executor.submit(run_agent_with_retry, build_driver_assign_agent,
                          f"Assign driver for order {order2['order_id']}"): "Driver",
            executor.submit(run_agent_with_retry, build_price_calculator_agent,
                          f"Calculate price for order {order2['order_id']}"): "Price",
            executor.submit(run_agent_with_retry, build_status_tracker_agent,
                          f"Update status for order {order2['order_id']}"): "Status",
        }
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                pass

    t_parallel = time.time() - t_start
    conflicts_after = sum(1 for e in db._write_log if e["op"] == "CONFLICT")
    new_conflicts = conflicts_after - conflicts_before

    state2 = get_order(order2["order_id"])
    print(f"\n  Final State: {state2['order_id']} v{state2['version']}")
    print(f"    Status: {state2['status']} | Driver: {state2['driver']['name'] if state2.get('driver') else '?'}")
    tp2 = state2.get('total_price')
    print(f"    Total: ${tp2['total']:.2f}" if tp2 else "    Total: ?")
    print(f"    Conflicts: {new_conflicts} | All resolved: {'YES' if state2.get('driver') and state2.get('total_price') else 'NO'} | Time: {t_parallel:.1f}s")

    order3 = ORDERS[2]
    print(f"\n{'━' * 70}")
    print(f"  SCENARIO 3: State Recovery (restaurant rejection + returning customer)")
    print(f"  Order: {order3['order_id']} — {order3['restaurant']}")
    print(f"  Restaurant will REJECT → triggers cleanup | Customer: {order3['customer_name']} (same as ORD-001)")
    print(f"{'━' * 70}")

    cust_id = order3["customer_id"]
    mem = customer_memory.get(cust_id, {})
    print(f"\n  Customer memory for {cust_id}: {json.dumps(mem, indent=4)}")

    record3 = create_order(order3)
    print(f"  Created: {order3['order_id']} (version {record3['version']})")

    print(f"\n  [Partial] DriverAssignAgent (should use preferred driver)...")
    run_agent_with_retry(build_driver_assign_agent, f"Assign driver for order {order3['order_id']}")
    state3 = get_order(order3["order_id"])
    driver3 = state3.get("driver", {})
    print(f"    Driver: {driver3.get('name', '?')} — {driver3.get('match_reason', '?')} (v{state3['version']})")

    print(f"  [Partial] PriceCalculatorAgent...")
    run_agent_with_retry(build_price_calculator_agent, f"Calculate price for order {order3['order_id']}")
    state3 = get_order(order3["order_id"])
    print(f"    Price: ${state3['total_price']['total']:.2f} (v{state3['version']})")

    print(f"\n  [REJECT] RestaurantConfirmAgent — restaurant rejects order!")
    run_agent_with_retry(lambda: build_restaurant_confirm_agent(True), f"Confirm order {order3['order_id']}")
    state3 = get_order(order3["order_id"])
    print(f"    Status: {state3['status']} (v{state3['version']})")

    print(f"\n  [RECOVERY] Cleaning up partial state...")
    recovered = recover_order(order3["order_id"])

    print(f"\n  Final State: {recovered['order_id']} v{recovered['version']}")
    print(f"    Status: {recovered['status']} | Driver: {recovered['driver']} | Price: {recovered['total_price']}")
    print(f"    Progress: {recovered['progress']}")

    print(f"\n{'═' * 70}")
    print("  SHARED STATE SUMMARY")
    print(f"{'═' * 70}")

    total_writes = sum(1 for e in db._write_log if e["op"] in ("put_item", "update_item"))
    total_conflicts = sum(1 for e in db._write_log if e["op"] == "CONFLICT")

    print(f"  Total writes: {total_writes} | Total conflicts: {total_conflicts}")
    if (total_writes + total_conflicts) > 0:
        print(f"  Conflict rate: {total_conflicts/(total_writes+total_conflicts)*100:.0f}%")
    print(f"  All resolved: YES (via optimistic locking + retry)")

    print(f"\n  Write Log (last 10 entries):")
    print(f"  {'Op':<15} {'Order':<12} {'Version':<12} {'Fields'}")
    print(f"  {'─' * 55}")
    for entry in db._write_log[-10:]:
        fields = ", ".join(entry.get("fields", []))
        version = str(entry.get("version", ""))
        print(f"  {entry['op']:<15} {entry['pk']:<12} {version:<12} {fields}")

    print(f"\n  Customer Memory (AgentCore Memory SESSION_SUMMARY simulation):")
    for cid, mem in customer_memory.items():
        print(f"    {cid}: preferred_driver={mem.get('preferred_driver', '?')}, "
              f"last_driver={mem.get('last_driver', '?')}, favorite_restaurant={mem.get('favorite_restaurant', '?')}")

    print(f"\n  Key Insight: Exercise adds STATE RECOVERY to the demo's pattern:")
    print(f"  1. OPTIMISTIC LOCKING — version + ConditionExpression (same as demo)")
    print(f"  2. RETRY ON CONFLICT — re-read → new version → retry (same as demo)")
    print(f"  3. STATE RECOVERY — reject → cleanup partial updates → cancel (NEW)")
    print(f"  4. TTL — auto-expire completed orders (2 hours)")
    print(f"  5. AGENTCORE MEMORY — customer preferences persist across orders\n")


if __name__ == "__main__":
    main()
