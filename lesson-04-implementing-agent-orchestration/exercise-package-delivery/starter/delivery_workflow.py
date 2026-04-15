"""
delivery_workflow.py - EXERCISE STARTER (Student-Led)
=====================================================
Module 4 Exercise: Build an Orchestrated Package Delivery Workflow

Architecture:
    New Delivery Request
         │
    ┌────┴────┐
    │ SEQUENTIAL │  (gate — must pass before continuing)
    │  Phase 1   │
    │ AddressValidator → valid? If NO → halt workflow
    └────┬────┘
         │ (only if valid)
    ┌────┴────────────────────────┐
    │ PARALLEL                    │  (independent, run simultaneously)
    │  Phase 2                    │
    │ LabelGenerator              │
    │ InsuranceCalculator         │
    │ CarrierSelector             │
    └────┬────────────────────────┘
         │
    ┌────┴────┐
    │ CONDITIONAL │  (route based on destination country)
    │  Phase 3    │
    │ if same country  → DomesticShipping
    │ if diff country  → InternationalShipping
    └────┬────┘
         │
    Delivery Processed

Your Task:
  Complete 9 TODOs total to build the full orchestrated workflow:

  PART A — Agent system prompts (TODOs 1-6, one per worker)
    For each build_*() function, the BedrockModel and Agent construction are
    already written for you. You only need to fill in the system_prompt —
    the thing that actually distinguishes one worker from another. Keep each
    prompt focused and single-purpose.

  PART B — Orchestrator phases (TODOs 7-9, in orchestrate_delivery)
    The orchestrator is the control plane — it decides WHEN each agent runs,
    handles failures, and routes between branches. You implement three phases:
      - TODO 7: Sequential GATE (validate → halt on failure)
      - TODO 8: Parallel dispatch with ThreadPoolExecutor
      - TODO 9: Conditional routing (domestic vs international)

  This lesson is about orchestration patterns, not agent wiring. Most of the
  scaffolding is pre-built so you can focus on the control-flow primitives.
"""

import json
import os
import re
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from strands import Agent, tool
from strands.models import BedrockModel

load_dotenv()

logging.basicConfig(level=logging.WARNING)


def clean_response(text: str) -> str:
    """Strip <thinking>...</thinking> tags from Nova model outputs."""
    return re.sub(r"<thinking>.*?</thinking>\s*", "", str(text), flags=re.DOTALL).strip()


# NOTE: In production, extract shared helpers like run_agent_with_retry() and
# clean_response() to a common utils.py module to avoid code duplication.
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
NOVA_LITE_MODEL = os.environ.get("NOVA_LITE_MODEL", "amazon.nova-lite-v1:0")   # All workers use Nova Lite (fast execution)

# ─────────────────────────────────────────────────────
# SAMPLE DELIVERY REQUESTS
# ─────────────────────────────────────────────────────
DELIVERIES = [
    {
        "id": "PKG-001",
        "sender": "Alice Chen",
        "sender_country": "US",
        "recipient": "Bob Martinez",
        "address": "742 Evergreen Terrace, Springfield, IL 62704",
        "country": "US",
        "weight_lbs": 5.2,
        "declared_value": 150.00,
        "contents": "Electronics — wireless keyboard and mouse",
    },
    {
        "id": "PKG-002",
        "sender": "Carol Johnson",
        "sender_country": "US",
        "recipient": "Hans Mueller",
        "address": "Friedrichstraße 43, 10117 Berlin",
        "country": "DE",
        "weight_lbs": 12.8,
        "declared_value": 2500.00,
        "contents": "Industrial equipment — precision calibration tools",
    },
    {
        "id": "PKG-003",
        "sender": "David Kim",
        "sender_country": "US",
        "recipient": "Sarah Lee",
        "address": "",  # Invalid — empty address triggers validation failure
        "country": "US",
        "weight_lbs": 3.0,
        "declared_value": 75.00,
        "contents": "Books — software engineering textbooks",
    },
]

# ── Pre-defined data for deterministic output ──
CARRIER_RATES = {
    "US": [
        {"carrier": "USPS Priority", "rate": 12.50, "est_days": 3},
        {"carrier": "FedEx Ground", "rate": 15.75, "est_days": 2},
        {"carrier": "UPS Standard", "rate": 14.00, "est_days": 2},
    ],
    "DE": [
        {"carrier": "DHL International", "rate": 45.00, "est_days": 7},
        {"carrier": "FedEx International", "rate": 52.00, "est_days": 5},
        {"carrier": "UPS Worldwide", "rate": 48.50, "est_days": 6},
    ],
}

INSURANCE_RATES = {
    "basic": {"threshold": 100, "rate": 0.02, "coverage": "loss only"},
    "standard": {"threshold": 500, "rate": 0.035, "coverage": "loss + damage"},
    "premium": {"threshold": 1000, "rate": 0.05, "coverage": "loss + damage + delay"},
}

# Shared workflow state — orchestrator writes, main() reads
workflow_state = {}


# ═══════════════════════════════════════════════════════
#  WORKER AGENTS — Build each agent following the STEP 1/2/3 pattern
#  from the demo (hr_onboarding.py):
#    STEP 1: BedrockModel (Nova Lite, temperature 0.0)
#    STEP 2: System prompt (focused, single responsibility)
#    STEP 3: Agent(model=model, system_prompt=system_prompt, tools=[...])
# ═══════════════════════════════════════════════════════

# ── Phase 1: Sequential Gate Worker ───────────────────

def build_address_validator() -> Agent:
    """Worker: Validates the delivery address (must pass BEFORE anything else)."""

    # Nova Lite for fast, deterministic validation (pre-filled — see Module 1 for pattern).
    model = BedrockModel(
        model_id=os.environ.get("NOVA_LITE_MODEL", "amazon.nova-lite-v1:0"),
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        temperature=0.0,
    )

    # TODO 1: Write a focused system prompt for this worker.
    #   The agent should:
    #     1. Call validate_address with the package_id
    #     2. Report: "Address <valid/invalid> for <package_id>: <reason>"
    #   Single responsibility — no extra commentary.
    system_prompt = ""  # ← your prompt here

    @tool
    def validate_address(package_id: str) -> str:
        """
        Validate the delivery address for a package.

        Args:
            package_id: The package ID (e.g., "PKG-001")

        Returns:
            JSON with validation result (valid/invalid + reason)
        """
        pkg = next((p for p in DELIVERIES if p["id"] == package_id), None)
        if not pkg:
            return json.dumps({"error": f"Package {package_id} not found"})

        address = pkg["address"].strip()

        if not address:
            result = {
                "package_id": package_id,
                "status": "invalid",
                "reason": "Address is empty",
                "address": "(none)",
            }
        elif len(address) < 10:
            result = {
                "package_id": package_id,
                "status": "invalid",
                "reason": "Address too short — missing street or city",
                "address": address,
            }
        else:
            result = {
                "package_id": package_id,
                "status": "valid",
                "reason": "Address format verified",
                "address": address,
                "country": pkg["country"],
            }

        workflow_state["validation"] = result
        return json.dumps(result, indent=2)

    return Agent(model=model, system_prompt=system_prompt, tools=[validate_address])


# ── Phase 2: Parallel Workers ─────────────────────────

def build_label_generator() -> Agent:
    """Worker: Generates shipping label (can run in PARALLEL with insurance/carrier)."""

    model = BedrockModel(
        model_id=os.environ.get("NOVA_LITE_MODEL", "amazon.nova-lite-v1:0"),
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        temperature=0.0,
    )

    # TODO 2: Write a focused system prompt for this worker.
    #   The agent should:
    #     1. Call generate_label with the package_id
    #     2. Report: "Label generated for <package_id>: tracking <tracking_number>"
    system_prompt = ""  # ← your prompt here

    @tool
    def generate_label(package_id: str) -> str:
        """
        Generate a shipping label with tracking number.

        Args:
            package_id: The package ID

        Returns:
            JSON with label details (tracking number, dimensions, etc.)
        """
        pkg = next((p for p in DELIVERIES if p["id"] == package_id), None)
        if not pkg:
            return json.dumps({"error": f"Package {package_id} not found"})

        tracking = f"TRK-{package_id[-3:]}-{pkg['country']}-{int(time.time()) % 100000}"
        result = {
            "package_id": package_id,
            "tracking_number": tracking,
            "sender": pkg["sender"],
            "recipient": pkg["recipient"],
            "address": pkg["address"],
            "country": pkg["country"],
            "weight_lbs": pkg["weight_lbs"],
            "contents": pkg["contents"],
            "status": "label_created",
        }
        workflow_state["label"] = result
        return json.dumps(result, indent=2)

    return Agent(model=model, system_prompt=system_prompt, tools=[generate_label])


def build_insurance_calculator() -> Agent:
    """Worker: Calculates insurance premium (can run in PARALLEL with label/carrier)."""

    model = BedrockModel(
        model_id=os.environ.get("NOVA_LITE_MODEL", "amazon.nova-lite-v1:0"),
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        temperature=0.0,
    )

    # TODO 3: Write a focused system prompt for this worker.
    #   The agent should:
    #     1. Call calculate_insurance with the package_id
    #     2. Report: "Insurance for <package_id>: $<premium> (<tier> coverage)"
    system_prompt = ""  # ← your prompt here

    @tool
    def calculate_insurance(package_id: str) -> str:
        """
        Calculate shipping insurance based on declared value.

        Args:
            package_id: The package ID

        Returns:
            JSON with insurance tier, premium, and coverage details
        """
        pkg = next((p for p in DELIVERIES if p["id"] == package_id), None)
        if not pkg:
            return json.dumps({"error": f"Package {package_id} not found"})

        value = pkg["declared_value"]

        if value > INSURANCE_RATES["premium"]["threshold"]:
            tier = "premium"
        elif value > INSURANCE_RATES["standard"]["threshold"]:
            tier = "standard"
        else:
            tier = "basic"

        rate_info = INSURANCE_RATES[tier]
        premium = round(value * rate_info["rate"], 2)

        result = {
            "package_id": package_id,
            "declared_value": value,
            "tier": tier,
            "rate": rate_info["rate"],
            "premium": premium,
            "coverage": rate_info["coverage"],
        }
        workflow_state["insurance"] = result
        return json.dumps(result, indent=2)

    return Agent(model=model, system_prompt=system_prompt, tools=[calculate_insurance])


def build_carrier_selector() -> Agent:
    """Worker: Selects optimal carrier (can run in PARALLEL with label/insurance)."""

    model = BedrockModel(
        model_id=os.environ.get("NOVA_LITE_MODEL", "amazon.nova-lite-v1:0"),
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        temperature=0.0,
    )

    # TODO 4: Write a focused system prompt for this worker.
    #   The agent should:
    #     1. Call select_carrier with the package_id
    #     2. Report: "Carrier for <package_id>: <carrier_name> ($<rate>, <days> days)"
    system_prompt = ""  # ← your prompt here

    @tool
    def select_carrier(package_id: str) -> str:
        """
        Select the optimal shipping carrier based on destination and weight.

        Args:
            package_id: The package ID

        Returns:
            JSON with selected carrier, rate, and estimated delivery time
        """
        pkg = next((p for p in DELIVERIES if p["id"] == package_id), None)
        if not pkg:
            return json.dumps({"error": f"Package {package_id} not found"})

        country = pkg["country"]
        carriers = CARRIER_RATES.get(country, CARRIER_RATES["US"])

        best = min(carriers, key=lambda c: c["rate"])

        result = {
            "package_id": package_id,
            "country": country,
            "weight_lbs": pkg["weight_lbs"],
            "selected_carrier": best["carrier"],
            "rate": best["rate"],
            "est_days": best["est_days"],
            "alternatives": [c["carrier"] for c in carriers if c["carrier"] != best["carrier"]],
        }
        workflow_state["carrier"] = result
        return json.dumps(result, indent=2)

    return Agent(model=model, system_prompt=system_prompt, tools=[select_carrier])


# ── Phase 3: Conditional Workers ──────────────────────

def build_domestic_shipping() -> Agent:
    """Worker: Processes domestic shipment (conditional — same country only)."""

    model = BedrockModel(
        model_id=os.environ.get("NOVA_LITE_MODEL", "amazon.nova-lite-v1:0"),
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        temperature=0.0,
    )

    # TODO 5: Write a focused system prompt for this worker.
    #   The agent should:
    #     1. Call process_domestic with the package_id
    #     2. Report: "Domestic shipment processed for <package_id>"
    system_prompt = ""  # ← your prompt here

    @tool
    def process_domestic(package_id: str) -> str:
        """
        Process a domestic shipment — standard ground shipping within the same country.

        Args:
            package_id: The package ID

        Returns:
            JSON with domestic shipping details
        """
        pkg = next((p for p in DELIVERIES if p["id"] == package_id), None)
        if not pkg:
            return json.dumps({"error": f"Package {package_id} not found"})

        carrier = workflow_state.get("carrier", {})
        result = {
            "package_id": package_id,
            "shipping_type": "domestic",
            "carrier": carrier.get("selected_carrier", "USPS Priority"),
            "customs_required": False,
            "est_delivery": f"{carrier.get('est_days', 3)} business days",
            "total_cost": round(carrier.get("rate", 12.50) + workflow_state.get("insurance", {}).get("premium", 3.00), 2),
            "status": "dispatched",
        }
        workflow_state["shipping"] = result
        return json.dumps(result, indent=2)

    return Agent(model=model, system_prompt=system_prompt, tools=[process_domestic])


def build_international_shipping() -> Agent:
    """Worker: Processes international shipment (conditional — different country only)."""

    model = BedrockModel(
        model_id=os.environ.get("NOVA_LITE_MODEL", "amazon.nova-lite-v1:0"),
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        temperature=0.0,
    )

    # TODO 6: Write a focused system prompt for this worker.
    #   The agent should:
    #     1. Call process_international with the package_id
    #     2. Report: "International shipment processed for <package_id>"
    system_prompt = ""  # ← your prompt here

    @tool
    def process_international(package_id: str) -> str:
        """
        Process an international shipment — customs declaration, duties, international carrier.

        Args:
            package_id: The package ID

        Returns:
            JSON with international shipping details including customs info
        """
        pkg = next((p for p in DELIVERIES if p["id"] == package_id), None)
        if not pkg:
            return json.dumps({"error": f"Package {package_id} not found"})

        carrier = workflow_state.get("carrier", {})
        insurance = workflow_state.get("insurance", {})

        customs_duty = round(pkg["declared_value"] * 0.05, 2)
        total = round(carrier.get("rate", 45.00) + insurance.get("premium", 125.00) + customs_duty, 2)

        result = {
            "package_id": package_id,
            "shipping_type": "international",
            "carrier": carrier.get("selected_carrier", "DHL International"),
            "customs_required": True,
            "customs_declaration": {
                "contents": pkg["contents"],
                "declared_value": pkg["declared_value"],
                "duty_estimate": customs_duty,
                "hs_code": "8543.70",
            },
            "est_delivery": f"{carrier.get('est_days', 7)} business days",
            "total_cost": total,
            "status": "dispatched",
        }
        workflow_state["shipping"] = result
        return json.dumps(result, indent=2)

    return Agent(model=model, system_prompt=system_prompt, tools=[process_international])


# ═══════════════════════════════════════════════════════
#  ORCHESTRATOR — You implement this
#  The orchestrator is the control plane. It decides WHEN each worker runs,
#  handles failures, and routes between branches. Three phases to implement:
#   - Phase 1: Sequential GATE (halt workflow if validation fails)
#   - Phase 2: Parallel execution via ThreadPoolExecutor
#   - Phase 3: Conditional routing based on data (not LLM)
#
#  Patterns:
#   - run_agent_with_retry(builder, prompt) -> float (elapsed seconds) is
#     already provided above. Use it for every agent invocation so you get
#     free retry + backoff handling.
#   - Reading a worker's output happens via the shared `workflow_state` dict.
#     Each @tool writes its result there (see the tool implementations).
#   - Compare with the Module 3 demo for the ThreadPoolExecutor pattern and
#     the Module 4 demo (hr_onboarding.py) for the full 3-phase flow.
# ═══════════════════════════════════════════════════════

def orchestrate_delivery(package_id: str) -> dict:
    """
    Run the complete delivery workflow for a package.

    Flow:
        Phase 1 (SEQUENTIAL GATE): AddressValidator → valid? If NO → halt
        Phase 2 (PARALLEL):        LabelGenerator + InsuranceCalculator + CarrierSelector
        Phase 3 (CONDITIONAL):     DomesticShipping OR InternationalShipping

    Returns a dict with per-phase timings and a `halted` flag.
    """
    pkg = next((p for p in DELIVERIES if p["id"] == package_id), None)
    if not pkg:
        return {"error": f"Package {package_id} not found"}

    timings: dict = {}
    phase2_time: float = 0.0

    # ══════════════════════════════════════════════════
    # PHASE 1: SEQUENTIAL GATE — Address must be valid
    # ══════════════════════════════════════════════════
    print(f"\n  ── Phase 1: SEQUENTIAL GATE (address validation) ──")

    # TODO 7: Implement the sequential gate.
    #
    #   1. Invoke the address validator with run_agent_with_retry(...) and
    #      store the elapsed time in timings["validation"]. Use a prompt like
    #      f"Validate address for package {package_id}".
    #
    #   2. After the agent runs, read workflow_state["validation"] — the
    #      @tool wrote the result there. If its "status" is not "valid",
    #      print a HALTED message and RETURN EARLY with:
    #        - phase1_gate: timings["validation"]
    #        - phase2_parallel: 0
    #        - phase3_conditional: 0
    #        - total: timings["validation"]
    #        - halted: True
    #        - halt_reason: the validation "reason" field
    #        - timings: timings
    #
    #   3. Otherwise, fall through to Phase 2. Print a "valid" confirmation.
    #
    # Pattern reference: see the Module 4 demo (hr_onboarding.py).
    raise NotImplementedError("TODO 7: implement the sequential gate")

    # ══════════════════════════════════════════════════
    # PHASE 2: PARALLEL — Label, insurance, carrier
    # These three agents are INDEPENDENT — none reads another's output — so
    # they can run at the same time. Expect a ~3× speedup over running them
    # one-after-another.
    # ══════════════════════════════════════════════════
    print(f"\n  ── Phase 2: PARALLEL (label + insurance + carrier) ──")

    # TODO 8: Dispatch the three parallel workers with ThreadPoolExecutor.
    #
    #   The pattern is identical to the Module 3 demo (document_analysis.py):
    #     - For each worker, define a small zero-arg closure that calls
    #       run_agent_with_retry(build_<worker>, "<prompt for that worker>")
    #     - Open a ThreadPoolExecutor(max_workers=3)
    #     - submit() each closure, mapping the Future to a name
    #       ("label" | "insurance" | "carrier")
    #     - Iterate with as_completed(futures) and store each result in
    #       timings[name]
    #     - Measure the WALL-CLOCK time of the whole parallel phase and
    #       assign it to phase2_time (use time.time() before and after)
    #
    # The three worker builders are build_label_generator, build_insurance_calculator,
    # and build_carrier_selector. Use prompts like
    #   f"Generate shipping label for package {package_id}"
    #   f"Calculate insurance for package {package_id}"
    #   f"Select carrier for package {package_id}"
    pass  # ← replace with your implementation

    print(f"    Label: {timings.get('label', 0):.1f}s | Insurance: {timings.get('insurance', 0):.1f}s | Carrier: {timings.get('carrier', 0):.1f}s")
    print(f"    Phase 2 total: {phase2_time:.1f}s (parallel)")

    # ══════════════════════════════════════════════════
    # PHASE 3: CONDITIONAL — Route based on destination country
    # This is a CODE decision (deterministic if/else), not an LLM decision.
    # Routing logic that can be expressed as code should be — it's cheaper,
    # faster, and impossible to hallucinate.
    # ══════════════════════════════════════════════════
    print(f"\n  ── Phase 3: CONDITIONAL (shipping route) ──")

    # TODO 9: Route conditionally based on destination country.
    #
    #   - Read pkg["sender_country"] and pkg["country"].
    #   - If they're the same, invoke build_domestic_shipping via
    #     run_agent_with_retry(...). Otherwise invoke build_international_shipping.
    #   - Store the elapsed time in timings["shipping"].
    #   - Print which branch you took.
    pass  # ← replace with your implementation

    shipping = workflow_state.get("shipping", {})
    print(f"    {shipping.get('shipping_type', '?').title()} shipping processed ({timings.get('shipping', 0):.1f}s)")
    print(f"    Carrier: {shipping.get('carrier', '?')} | Total: ${shipping.get('total_cost', 0):.2f}")

    return {
        "phase1_gate": timings["validation"],
        "phase2_parallel": phase2_time,
        "phase3_conditional": timings.get("shipping", 0),
        "total": timings["validation"] + phase2_time + timings.get("shipping", 0),
        "halted": False,
        "timings": timings,
    }


# ═══════════════════════════════════════════════════════
#  MAIN — Already implemented
# ═══════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("  Package Delivery Workflow — Module 4 Exercise")
    print("  Sequential Gate + Parallel + Conditional Orchestration")
    print("  6 Worker Agents managed by Python orchestrator")
    print("=" * 70)

    results = []

    for pkg in DELIVERIES:
        pkg_id = pkg["id"]
        is_domestic = pkg["sender_country"] == pkg["country"]
        route = "Domestic" if is_domestic else "International"

        print(f"\n{'━' * 70}")
        print(f"  Package: {pkg_id} — {pkg['contents'][:40]}...")
        print(f"  From: {pkg['sender']} ({pkg['sender_country']}) → To: {pkg['recipient']} ({pkg['country']})")
        print(f"  Address: {pkg['address'] or '(empty)'}")
        print(f"  Weight: {pkg['weight_lbs']} lbs | Value: ${pkg['declared_value']:.2f}")
        print(f"  Expected route: {route}")
        print(f"{'━' * 70}")

        workflow_state.clear()

        result = orchestrate_delivery(pkg_id)

        if result.get("halted"):
            print(f"\n  ┌─── Delivery Summary ───────────────────────────┐")
            print(f"  │ Status:   HALTED")
            print(f"  │ Reason:   {result.get('halt_reason', '?')}")
            print(f"  │ Package:  {pkg_id}")
            print(f"  └────────────────────────────────────────────────┘")
            print(f"  Phase 1 (gate):       {result['phase1_gate']:.1f}s")
            print(f"  Total:                {result['total']:.1f}s")
        else:
            label = workflow_state.get("label", {})
            insurance = workflow_state.get("insurance", {})
            carrier = workflow_state.get("carrier", {})
            shipping = workflow_state.get("shipping", {})

            print(f"\n  ┌─── Delivery Summary ───────────────────────────┐")
            print(f"  │ Tracking: {label.get('tracking_number', '?')}")
            print(f"  │ Carrier:  {carrier.get('selected_carrier', '?')} (${carrier.get('rate', 0):.2f})")
            print(f"  │ Insurance:{insurance.get('tier', '?')} — ${insurance.get('premium', 0):.2f} ({insurance.get('coverage', '?')})")
            print(f"  │ Route:    {shipping.get('shipping_type', '?').title()}")
            print(f"  │ Customs:  {'Yes' if shipping.get('customs_required') else 'No'}")
            print(f"  │ Delivery: {shipping.get('est_delivery', '?')}")
            print(f"  │ Total:    ${shipping.get('total_cost', 0):.2f}")
            print(f"  └────────────────────────────────────────────────┘")
            print(f"  Phase 1 (gate):       {result['phase1_gate']:.1f}s")
            print(f"  Phase 2 (parallel):   {result['phase2_parallel']:.1f}s")
            print(f"  Phase 3 (conditional):{result['phase3_conditional']:.1f}s")
            print(f"  Total:                {result['total']:.1f}s")

        results.append({
            "package": pkg_id,
            "route": "HALTED" if result.get("halted") else ("Domestic" if is_domestic else "International"),
            "halted": result.get("halted", False),
            "total_s": round(result["total"], 1),
            "gate_s": round(result["phase1_gate"], 1),
            "par_s": round(result["phase2_parallel"], 1),
            "cond_s": round(result["phase3_conditional"], 1),
        })

    # ── Summary Table ────────────────────────────────────
    print(f"\n{'═' * 70}")
    print("  ORCHESTRATION SUMMARY")
    print(f"{'═' * 70}")
    print(f"  {'Package':<10} {'Route':<16} {'Gate':<7} {'Par.':<7} {'Cond.':<7} {'Total':<7}")
    print(f"  {'─' * 58}")
    for r in results:
        print(f"  {r['package']:<10} {r['route']:<16} {r['gate_s']:<7.1f} {r['par_s']:<7.1f} {r['cond_s']:<7.1f} {r['total_s']:<7.1f}")

    print(f"\n  Key Insight: This exercise adds a new orchestration pattern — the GATE:")
    print(f"  1. GATE        — a pre-condition that halts the workflow if it fails (PKG-003)")
    print(f"  2. PARALLEL    — independent steps run simultaneously (label + insurance + carrier)")
    print(f"  3. CONDITIONAL — route based on data (domestic vs international)")
    print(f"  Compare with the demo: the demo uses sequential CHAIN (A then B), while")
    print(f"  this exercise uses a sequential GATE (validate or halt). Both are sequential")
    print(f"  patterns, but gates add workflow control flow.\n")


if __name__ == "__main__":
    main()
