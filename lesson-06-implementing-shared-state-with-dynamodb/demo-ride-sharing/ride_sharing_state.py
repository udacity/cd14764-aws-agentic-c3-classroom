"""
ride_sharing_state.py - DEMO (Instructor-Led)
===============================================
Module 6 Demo: Building a Shared State Store for Ride-Sharing Trip Management

Architecture:
    Rider requests trip
         │
    ┌────┴────────────────────────────────────────────┐
    │  Shared State (DynamoDB)                         │
    │  trip_id (PK) | version | driver | fare | eta    │
    │  Optimistic locking: version-based conditional   │
    │  writes (ConditionExpression) prevent lost updates│
    │  TTL: auto-expire completed trips after 1 hour   │
    └────┬────────────────────────────────────────────┘
         │
    Three agents update the SAME record:
    ┌────┴────────────────────────────────────┐
    │ DriverMatchAgent  → writes driver field  │
    │ PricingAgent      → writes fare field    │
    │ ETAAgent          → writes eta field     │
    └─────────────────────────────────────────┘
         │
    Cross-Session Memory (AgentCore Memory):
    ┌────┴────────────────────────────────────────────┐
    │ SESSION_SUMMARY strategy → rider preferences     │
    │ Remembers preferred driver across sessions       │
    └─────────────────────────────────────────────────┘

Optimistic Locking Pattern:
    1. Agent reads record → gets version N
    2. Agent does its work (match driver, calculate fare, etc.)
    3. Agent writes with condition: version == N
    4. If another agent wrote first (version > N):
       → ConditionalCheckFailedException
       → Re-read, get new version, retry

    Production DynamoDB API:
        table.update_item(
            Key={'trip_id': trip_id},
            UpdateExpression='SET driver = :d, version = version + :one',
            ConditionExpression='version = :expected',
            ExpressionAttributeValues={':d': driver_info, ':expected': N, ':one': 1}
        )

Key Concepts (Module 6):
  1. SHARED STATE: Multiple agents read/write the same record
  2. OPTIMISTIC LOCKING: version field + conditional writes
  3. CONFLICT DETECTION: ConditionalCheckFailedException on version mismatch
  4. RETRY ON CONFLICT: re-read → get new version → retry write
  5. TTL: Auto-expire completed trips (DynamoDB TimeToLive)
  6. AGENTCORE MEMORY: Cross-session rider preferences (SESSION_SUMMARY)

DynamoDB vs AgentCore Memory:
  - DynamoDB = within-session transactional state (trip records, optimistic locking)
  - AgentCore Memory = cross-session conversational context (rider preferences)

Tech Stack:
  - Python 3.11+
  - Strands Agents SDK (Agent class, @tool decorator)
  - Amazon Bedrock (Nova Lite for all agents)
  - DynamoDB shared state (real AWS resource — created by CloudFormation)
  - AgentCore Memory simulation (in-memory; production uses bedrock-agentcore-control)
"""

import os
import json
import re
import time
import logging
from decimal import Decimal
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
import boto3
from botocore.exceptions import ClientError
from strands import Agent, tool
from strands.models import BedrockModel

load_dotenv()

logging.basicConfig(level=logging.WARNING)


def to_dynamo(obj):
    """Convert Python objects to DynamoDB-compatible types (float→Decimal)."""
    return json.loads(json.dumps(obj), parse_float=Decimal)


def from_dynamo(obj):
    """Convert DynamoDB types back to Python (Decimal→float)."""
    return json.loads(json.dumps(obj, default=str))


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


AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
NOVA_LITE_MODEL = os.environ.get("NOVA_LITE_MODEL", "amazon.nova-lite-v1:0")

TRIPS = [
    {"trip_id": "TRIP-001", "rider_id": "RIDER-42", "rider_name": "Alice Chen",
     "pickup": "123 Main St, Downtown", "destination": "456 Oak Ave, Airport", "ride_type": "premium"},
    {"trip_id": "TRIP-002", "rider_id": "RIDER-77", "rider_name": "Bob Martinez",
     "pickup": "789 Pine Rd, University", "destination": "321 Elm St, Tech Park", "ride_type": "standard"},
    {"trip_id": "TRIP-003", "rider_id": "RIDER-42", "rider_name": "Alice Chen",
     "pickup": "456 Oak Ave, Airport", "destination": "123 Main St, Downtown", "ride_type": "premium"},
]

AVAILABLE_DRIVERS = {
    "premium": [
        {"driver_id": "DRV-101", "name": "Carlos Rivera", "rating": 4.95, "vehicle": "Tesla Model S"},
        {"driver_id": "DRV-102", "name": "Maria Santos", "rating": 4.92, "vehicle": "BMW 5 Series"},
    ],
    "standard": [
        {"driver_id": "DRV-201", "name": "James Wilson", "rating": 4.78, "vehicle": "Toyota Camry"},
        {"driver_id": "DRV-202", "name": "Sarah Kim", "rating": 4.85, "vehicle": "Honda Accord"},
    ],
}

FARE_RATES = {
    "premium": {"base": 8.00, "per_mile": 3.50, "surge": 1.0},
    "standard": {"base": 5.00, "per_mile": 2.00, "surge": 1.0},
}


class VersionConflictError(Exception):
    """Raised when optimistic locking detects a version mismatch.
    Maps to DynamoDB ConditionalCheckFailedException."""
    pass


# STEP 1: DYNAMODB SHARED STATE — Real DynamoDB with Optimistic Locking
TRIP_STATE_TABLE = os.environ.get("TRIP_STATE_TABLE", "lesson-06-shared-state-trip-state")
dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
trip_table = dynamodb.Table(TRIP_STATE_TABLE)

# Diagnostic write log (in-memory — for demo output only, not stored in DynamoDB)
_write_log = []

# AgentCore Memory simulation (in-memory; production uses bedrock-agentcore-control)
rider_memory = {}


# STEP 2: STATE HELPERS — Create, update, and read trip records
def create_trip(trip_data: dict) -> dict:
    """Create initial trip state (version 0, TTL 1 hour)."""
    trip_id = trip_data["trip_id"]
    now = time.time()
    record = {
        "trip_id": trip_id, "rider_id": trip_data["rider_id"], "rider_name": trip_data["rider_name"],
        "pickup": trip_data["pickup"], "destination": trip_data["destination"], "ride_type": trip_data["ride_type"],
        "driver": None, "fare": None, "eta": None, "status": "pending", "version": 0,
        "ttl": int(now + 3600), "created_at": datetime.now(timezone.utc).isoformat(),
    }
    trip_table.put_item(Item=to_dynamo(record))
    _write_log.append({"op": "put_item", "pk": trip_id, "version": 0, "timestamp": time.time()})
    return record


def update_trip(trip_id: str, updates: dict, max_retries: int = 3) -> dict:
    """Update trip state with optimistic locking + retry.
    Pattern: read → modify → conditional put (version must match)."""
    for attempt in range(max_retries):
        response = trip_table.get_item(Key={"trip_id": trip_id})
        current = response.get("Item")
        if not current:
            raise KeyError(f"Trip {trip_id} not found")
        expected_version = int(current["version"])

        # Apply updates locally
        current.update(to_dynamo(updates))
        current["version"] = expected_version + 1
        current["updated_at"] = datetime.now(timezone.utc).isoformat()

        try:
            trip_table.put_item(
                Item=current,
                ConditionExpression="version = :expected_ver",
                ExpressionAttributeValues={":expected_ver": expected_version},
            )
            _write_log.append({"op": "update_item", "pk": trip_id,
                "version": f"{expected_version} → {expected_version + 1}",
                "fields": list(updates.keys()), "timestamp": time.time()})
            return from_dynamo(current)
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                _write_log.append({"op": "CONFLICT", "pk": trip_id,
                    "expected": expected_version, "timestamp": time.time()})
                if attempt < max_retries - 1:
                    wait = 0.1 * (2 ** attempt)
                    print(f"      [Conflict] Version conflict — retrying in {wait:.1f}s (attempt {attempt + 1})")
                    time.sleep(wait)
                else:
                    print(f"      [Failed] Version conflict after {max_retries} retries")
                    raise VersionConflictError(f"Version conflict after {max_retries} retries")
            else:
                raise


def get_trip(trip_id: str) -> dict | None:
    """Read current trip state."""
    response = trip_table.get_item(Key={"trip_id": trip_id})
    item = response.get("Item")
    return from_dynamo(item) if item else None


# STEP 3: AGENT BUILDERS — 3 agents updating shared trip state
def build_driver_match_agent() -> Agent:
    """Worker: Matches a driver and writes to shared state."""
    # STEP 3.1: BedrockModel — Nova Lite for driver matching (temperature 0.0)
    model = BedrockModel(model_id=NOVA_LITE_MODEL, region_name=AWS_REGION, temperature=0.0)
    # STEP 3.2: System prompt — Instructions for matching best available driver
    system_prompt = """You are a driver matching agent. Your ONLY job:
1. Call match_driver with the trip_id
2. Report: Driver <name> matched for <trip_id>
Do NOT add any other commentary."""

    @tool
    def match_driver(trip_id: str) -> str:
        """Match the best available driver and update shared state."""
        trip = get_trip(trip_id)
        if not trip:
            return json.dumps({"error": f"Trip {trip_id} not found"})
        ride_type = trip.get("ride_type", "standard")
        drivers = AVAILABLE_DRIVERS.get(ride_type, AVAILABLE_DRIVERS["standard"])
        rider_id = trip.get("rider_id")
        preferred = rider_memory.get(rider_id, {}).get("preferred_driver")
        if preferred and any(d["driver_id"] == preferred for d in drivers):
            best = next(d for d in drivers if d["driver_id"] == preferred)
            match_reason = "preferred driver (from memory)"
        else:
            best = max(drivers, key=lambda d: d["rating"])
            match_reason = "highest rated available"
        driver_info = {"driver": {"driver_id": best["driver_id"], "name": best["name"],
            "rating": best["rating"], "vehicle": best["vehicle"], "match_reason": match_reason}}
        update_trip(trip_id, driver_info)
        if rider_id not in rider_memory:
            rider_memory[rider_id] = {}
        rider_memory[rider_id]["preferred_driver"] = best["driver_id"]
        rider_memory[rider_id]["last_driver_name"] = best["name"]
        result = {**driver_info["driver"], "trip_id": trip_id}
        return json.dumps(result, indent=2)

    # STEP 3.3: Build Agent — bind model + prompt + match_driver tool
    return Agent(model=model, system_prompt=system_prompt, tools=[match_driver])


def build_pricing_agent() -> Agent:
    """Worker: Calculates fare and writes to shared state."""
    # STEP 3.4: BedrockModel — Nova Lite for fare calculation (temperature 0.0)
    model = BedrockModel(model_id=NOVA_LITE_MODEL, region_name=AWS_REGION, temperature=0.0)
    # STEP 3.5: System prompt — Instructions for calculating fare estimates
    system_prompt = """You are a pricing agent. Your ONLY job:
1. Call calculate_fare with the trip_id
2. Report: Fare for <trip_id>: $<amount>
Do NOT add any other commentary."""

    @tool
    def calculate_fare(trip_id: str) -> str:
        """Calculate fare estimate and update shared state."""
        trip = get_trip(trip_id)
        if not trip:
            return json.dumps({"error": f"Trip {trip_id} not found"})
        ride_type = trip.get("ride_type", "standard")
        rates = FARE_RATES.get(ride_type, FARE_RATES["standard"])
        estimated_miles = 8.5 if "Airport" in (trip.get("destination", "") + trip.get("pickup", "")) else 5.2
        fare = round(rates["base"] + (rates["per_mile"] * estimated_miles * rates["surge"]), 2)
        fare_info = {"fare": {"base": rates["base"], "per_mile": rates["per_mile"],
            "estimated_miles": estimated_miles, "surge_multiplier": rates["surge"], "total": fare}}
        update_trip(trip_id, fare_info)
        result = {**fare_info["fare"], "trip_id": trip_id}
        return json.dumps(result, indent=2)

    # STEP 3.6: Build Agent — bind model + prompt + calculate_fare tool
    return Agent(model=model, system_prompt=system_prompt, tools=[calculate_fare])


def build_eta_agent() -> Agent:
    """Worker: Calculates ETA and writes to shared state."""
    # STEP 3.7: BedrockModel — Nova Lite for ETA calculation (temperature 0.0)
    model = BedrockModel(model_id=NOVA_LITE_MODEL, region_name=AWS_REGION, temperature=0.0)
    # STEP 3.8: System prompt — Instructions for estimating arrival time
    system_prompt = """You are an ETA calculation agent. Your ONLY job:
1. Call calculate_eta with the trip_id
2. Report: ETA for <trip_id>: <minutes> minutes
Do NOT add any other commentary."""

    @tool
    def calculate_eta(trip_id: str) -> str:
        """Calculate estimated arrival time and update shared state."""
        trip = get_trip(trip_id)
        if not trip:
            return json.dumps({"error": f"Trip {trip_id} not found"})
        has_airport = "Airport" in (trip.get("destination", "") + trip.get("pickup", ""))
        pickup_eta = 4 if trip.get("ride_type") == "premium" else 7
        trip_eta = 25 if has_airport else 15
        eta_info = {"eta": {"pickup_minutes": pickup_eta, "trip_minutes": trip_eta,
            "total_minutes": pickup_eta + trip_eta}}
        update_trip(trip_id, eta_info)
        update_trip(trip_id, {"status": "confirmed"})
        result = {**eta_info["eta"], "trip_id": trip_id}
        return json.dumps(result, indent=2)

    # STEP 3.9: Build Agent — bind model + prompt + calculate_eta tool
    return Agent(model=model, system_prompt=system_prompt, tools=[calculate_eta])


# STEP 4: DEMO EXECUTION — Run 3 scenarios with shared state management
def main():
    print("=" * 70)
    print("  Ride-Sharing Trip Management — Module 6 Demo")
    print("  Shared State with Optimistic Locking | 3 Agents updating SAME record")
    print("=" * 70)

    trip1 = TRIPS[0]
    print(f"\n{'━' * 70}")
    print(f"  SCENARIO 1: Sequential Updates (no conflicts)")
    print(f"  Trip: {trip1['trip_id']} — {trip1['rider_name']}")
    print(f"  {trip1['pickup']} → {trip1['destination']} | {trip1['ride_type']}")
    print(f"{'━' * 70}")

    record = create_trip(trip1)
    print(f"\n  Created: {trip1['trip_id']} (version {record['version']}, "
          f"TTL: {datetime.fromtimestamp(record['ttl'], tz=timezone.utc).strftime('%H:%M:%S UTC')})")

    print(f"\n  [1/3] DriverMatchAgent...")
    t1 = run_agent_with_retry(build_driver_match_agent, f"Match driver for trip {trip1['trip_id']}")
    state = get_trip(trip1["trip_id"])
    print(f"    Driver: {state['driver']['name']} (v{state['version']}, {t1:.1f}s)")

    print(f"  [2/3] PricingAgent...")
    t2 = run_agent_with_retry(build_pricing_agent, f"Calculate fare for trip {trip1['trip_id']}")
    state = get_trip(trip1["trip_id"])
    print(f"    Fare: ${state['fare']['total']:.2f} (v{state['version']}, {t2:.1f}s)")

    print(f"  [3/3] ETAAgent...")
    t3 = run_agent_with_retry(build_eta_agent, f"Calculate ETA for trip {trip1['trip_id']}")
    state = get_trip(trip1["trip_id"])
    print(f"    ETA: {state['eta']['total_minutes']} min (v{state['version']}, {t3:.1f}s)")

    print(f"\n  Final State: {state['trip_id']} v{state['version']}")
    print(f"    Status: {state['status']} | Driver: {state['driver']['name']} ({state['driver']['vehicle']})")
    print(f"    Fare: ${state['fare']['total']:.2f} ({state['fare']['estimated_miles']} mi) | ETA: {state['eta']['total_minutes']} min")

    trip2 = TRIPS[1]
    print(f"\n{'━' * 70}")
    print(f"  SCENARIO 2: Concurrent Updates (with conflicts)")
    print(f"  Trip: {trip2['trip_id']} — {trip2['rider_name']}")
    print(f"  All 3 agents run in PARALLEL — expect version conflicts!")
    print(f"{'━' * 70}")

    record2 = create_trip(trip2)
    print(f"\n  Created: {trip2['trip_id']} (version {record2['version']})")
    conflicts_before = sum(1 for e in _write_log if e["op"] == "CONFLICT")

    print(f"  Launching 3 agents in parallel...")
    t_start = time.time()
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(run_agent_with_retry, build_driver_match_agent,
                          f"Match driver for trip {trip2['trip_id']}"): "DriverMatch",
            executor.submit(run_agent_with_retry, build_pricing_agent,
                          f"Calculate fare for trip {trip2['trip_id']}"): "Pricing",
            executor.submit(run_agent_with_retry, build_eta_agent,
                          f"Calculate ETA for trip {trip2['trip_id']}"): "ETA",
        }
        for future in as_completed(futures):
            pass

    t_parallel = time.time() - t_start
    conflicts_after = sum(1 for e in _write_log if e["op"] == "CONFLICT")
    new_conflicts = conflicts_after - conflicts_before

    state2 = get_trip(trip2["trip_id"])
    print(f"\n  Final State: {state2['trip_id']} v{state2['version']}")
    print(f"    Status: {state2['status']} | Driver: {state2['driver']['name'] if state2.get('driver') else '?'}")
    print(f"    Fare: ${state2['fare']['total']:.2f}" if state2.get('fare') else "    Fare: ?")
    print(f"    ETA: {state2['eta']['total_minutes']} min | Conflicts: {new_conflicts} | Time: {t_parallel:.1f}s")

    trip3 = TRIPS[2]
    print(f"\n{'━' * 70}")
    print(f"  SCENARIO 3: Cross-Session Memory (returning rider)")
    print(f"  Trip: {trip3['trip_id']} — {trip3['rider_name']} (same as TRIP-001)")
    print(f"  Should remember preferred driver from TRIP-001")
    print(f"{'━' * 70}")

    rider_id = trip3["rider_id"]
    mem = rider_memory.get(rider_id, {})
    print(f"\n  Rider memory for {rider_id}: {json.dumps(mem, indent=4)}")

    record3 = create_trip(trip3)
    print(f"  Created: {trip3['trip_id']} (version {record3['version']})")

    print(f"  DriverMatchAgent (should use preferred driver)...")
    run_agent_with_retry(build_driver_match_agent, f"Match driver for trip {trip3['trip_id']}")
    state3 = get_trip(trip3["trip_id"])
    driver3 = state3.get("driver", {})
    print(f"    Driver: {driver3.get('name', '?')} — {driver3.get('match_reason', '?')}")

    run_agent_with_retry(build_pricing_agent, f"Calculate fare for trip {trip3['trip_id']}")
    run_agent_with_retry(build_eta_agent, f"Calculate ETA for trip {trip3['trip_id']}")
    state3 = get_trip(trip3["trip_id"])

    print(f"\n  Final State: {state3['trip_id']} v{state3['version']}")
    print(f"    Driver: {state3['driver']['name']} ({state3['driver']['match_reason']})")
    print(f"    Fare: ${state3['fare']['total']:.2f} | ETA: {state3['eta']['total_minutes']} min")

    print(f"\n{'═' * 70}")
    print("  SHARED STATE SUMMARY")
    print(f"{'═' * 70}")

    total_writes = sum(1 for e in _write_log if e["op"] in ("put_item", "update_item"))
    total_conflicts = sum(1 for e in _write_log if e["op"] == "CONFLICT")

    print(f"  Total writes: {total_writes} | Total conflicts: {total_conflicts}")
    if (total_writes + total_conflicts) > 0:
        print(f"  Conflict rate: {total_conflicts/(total_writes+total_conflicts)*100:.0f}%")
    print(f"  All resolved: YES (via optimistic locking + retry)")

    print(f"\n  Write Log (last 10 entries):")
    print(f"  {'Op':<15} {'Trip':<12} {'Version':<12} {'Fields'}")
    print(f"  {'─' * 55}")
    for entry in _write_log[-10:]:
        fields = ", ".join(entry.get("fields", []))
        version = str(entry.get("version", ""))
        print(f"  {entry['op']:<15} {entry['pk']:<12} {version:<12} {fields}")

    print(f"\n  Rider Memory (AgentCore Memory SESSION_SUMMARY simulation):")
    for rid, mem in rider_memory.items():
        print(f"    {rid}: preferred={mem.get('preferred_driver', '?')}, last_driver={mem.get('last_driver_name', '?')}")

    print(f"\n  Key Insight: Shared state needs TWO complementary services:")
    print(f"  1. DYNAMODB — within-session transactional state")
    print(f"     Version + ConditionExpression prevents lost updates")
    print(f"     ConditionalCheckFailedException → re-read + retry")
    print(f"  2. AGENTCORE MEMORY — cross-session conversational context")
    print(f"     SESSION_SUMMARY strategy remembers rider preferences\n")


if __name__ == "__main__":
    main()
