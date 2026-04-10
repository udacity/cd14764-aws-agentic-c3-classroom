"""
telecom_router.py - EXERCISE STARTER (Student-Led)
====================================================
Module 5 Exercise: Build a Multi-Strategy Router for Telecom Customer Tickets

Architecture:
    Incoming Ticket
         │
    ┌────┴────┐
    │ PRIORITY │  Cancellation intent detected?
    │  Check   │  YES → RetentionAgent
    └────┬────┘
         │ NO
    ┌────┴────┐
    │ RULE-   │  Keyword matching
    │ BASED   │  bill/charge/payment/invoice → BillingAgent
    │ ROUTER  │  outage/no signal/slow/drop  → TechnicalAgent
    └────┬────┘
         │ NO MATCH
    ┌────┴────┐
    │  LLM    │  Bedrock classification (Nova Lite)
    │ CLASSIFY│  confidence ≥ 0.6 → route to classified agent
    └────┬────┘
         │ LOW CONFIDENCE
    ┌────┴────┐
    │FALLBACK │  GeneralSupportAgent
    └─────────┘

Your Task:
  Follow the SAME pattern from the demo (financial_router.py):
  - Routing strategies: Priority → Rules → LLM → Fallback
  - Worker agents: STEP 1 (model) → STEP 2 (prompt) → STEP 3 (agent)
  - Classifier agent: same STEP 1/2/3 pattern

  Complete ALL 18 TODOs:
    - 3 routing strategy TODOs (priority, rules, LLM classifier)
    - 3 TODOs per worker agent × 4 agents = 12 TODOs
    - 3 TODOs for the classifier agent
"""

import json
import re
import time
import logging
import os
import boto3
from datetime import datetime, timezone
from dotenv import load_dotenv
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
# SAMPLE TELECOM TICKETS (20 total)
# ─────────────────────────────────────────────────────
TICKETS = [
    # ── Billing (8 tickets — 40%) ──
    {"id": "TKT-001", "text": "My bill is way too high this month, I was charged $200 extra",
     "expected_agent": "BillingAgent", "expected_method": "rule"},
    {"id": "TKT-002", "text": "I see a charge for a service I never signed up for",
     "expected_agent": "BillingAgent", "expected_method": "rule"},
    {"id": "TKT-003", "text": "My payment didn't go through but the money left my bank",
     "expected_agent": "BillingAgent", "expected_method": "rule"},
    {"id": "TKT-004", "text": "Can I get an invoice for my business account for tax purposes?",
     "expected_agent": "BillingAgent", "expected_method": "rule"},
    {"id": "TKT-005", "text": "I was double-billed for my monthly subscription",
     "expected_agent": "BillingAgent", "expected_method": "rule"},
    {"id": "TKT-006", "text": "The promotional rate on my bill expired without notice",
     "expected_agent": "BillingAgent", "expected_method": "rule"},
    {"id": "TKT-007", "text": "I need to update my payment method to a new credit card",
     "expected_agent": "BillingAgent", "expected_method": "rule"},
    {"id": "TKT-008", "text": "There's a roaming charge on my bill but I didn't leave the country",
     "expected_agent": "BillingAgent", "expected_method": "rule"},
    # ── Technical (6 tickets — 30%) ──
    {"id": "TKT-009", "text": "There's a complete outage in my area, no one has service",
     "expected_agent": "TechnicalAgent", "expected_method": "rule"},
    {"id": "TKT-010", "text": "I have no signal at all since yesterday morning",
     "expected_agent": "TechnicalAgent", "expected_method": "rule"},
    {"id": "TKT-011", "text": "My internet is extremely slow, barely loading any pages",
     "expected_agent": "TechnicalAgent", "expected_method": "rule"},
    {"id": "TKT-012", "text": "Calls keep getting dropped after 30 seconds of talking",
     "expected_agent": "TechnicalAgent", "expected_method": "rule"},
    {"id": "TKT-013", "text": "The WiFi router you sent keeps disconnecting every hour",
     "expected_agent": "TechnicalAgent", "expected_method": "rule"},
    {"id": "TKT-014", "text": "I'm getting no signal in my basement office since the tower update",
     "expected_agent": "TechnicalAgent", "expected_method": "rule"},
    # ── Cancellation (2 tickets — 10%) ──
    {"id": "TKT-015", "text": "I want to cancel my service and switch to another provider",
     "expected_agent": "RetentionAgent", "expected_method": "priority"},
    {"id": "TKT-016", "text": "I'm done with this company, please cancel everything immediately",
     "expected_agent": "RetentionAgent", "expected_method": "priority"},
    # ── Ambiguous (4 tickets — 20%) ──
    {"id": "TKT-017", "text": "My phone isn't working right, something is definitely wrong",
     "expected_agent": "LLM-classified", "expected_method": "llm"},
    {"id": "TKT-018", "text": "I've been having problems ever since I upgraded my plan last week",
     "expected_agent": "LLM-classified", "expected_method": "llm"},
    {"id": "TKT-019", "text": "Nothing works and I'm very frustrated with everything",
     "expected_agent": "LLM-classified", "expected_method": "llm"},
    {"id": "TKT-020", "text": "purple elephant moonbeam random gibberish xkcd 42",
     "expected_agent": "GeneralSupportAgent", "expected_method": "fallback"},
]

# ─────────────────────────────────────────────────────
# DYNAMODB AUDIT LOG
# ─────────────────────────────────────────────────────
ROUTING_AUDIT_TABLE = os.environ.get("ROUTING_AUDIT_TABLE", "lesson-05-routing-routing-audit")
dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
audit_table = dynamodb.Table(ROUTING_AUDIT_TABLE)


def log_routing_decision(ticket_id: str, input_text: str, method: str,
                         target_agent: str, confidence: float, latency_ms: float):
    """
    Log a routing decision to DynamoDB.

    Table schema (from CloudFormation):
      PK: request_id (S)  |  SK: timestamp (S)
      Attributes: input_text, routing_method, target_agent, confidence, latency_ms
    """
    entry = {
        "request_id": ticket_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "input_text": input_text[:80],
        "routing_method": method,
        "target_agent": target_agent,
        "confidence": str(confidence),
        "latency_ms": str(round(latency_ms, 1)),
        "ttl": int(time.time()) + 86400,  # Auto-delete after 24 hours
    }
    audit_table.put_item(Item=entry)


# Shared state
classification_result = {}
worker_response = {}


# ═══════════════════════════════════════════════════════
#  ROUTING STRATEGIES
#  Follow the same pattern from the demo:
#    Priority → Rules → LLM → Fallback
# ═══════════════════════════════════════════════════════

# TODO 1: Implement priority_route(text) — Cancellation Detection
#   Check if the ticket text contains cancellation keywords:
#   cancel (and variants like cancelling), switch provider, terminate, discontinue,
#   "done with this company", or "leave" followed by provider/service/company/carrier/plan.
#   Be careful: "leave" alone is too broad — "didn't leave the country" is NOT cancellation.
#   Return "RetentionAgent" if found, None otherwise.
#   Hint: Use re.search() with patterns. Look at the demo's priority_route() for structure.

def priority_route(text: str) -> str | None:
    """Check if ticket contains cancellation intent."""
    pass


# TODO 2: Implement rule_based_route(text) — Billing & Technical Keywords
#   Define ROUTING_RULES as a list of (pattern, agent_name) tuples:
#     - Billing keywords: bill, charge, payment, invoice, billed, subscription, rate, roaming
#       → "BillingAgent"
#     - Technical keywords: outage, no signal, slow, dropped, disconnect, no service, tower
#       → "TechnicalAgent"
#   Match against text.lower() and return the first matching agent, or None.
#   Hint: Same structure as the demo's ROUTING_RULES + rule_based_route()

ROUTING_RULES = []  # Fill this in as part of TODO 2

def rule_based_route(text: str) -> str | None:
    """Match ticket text against keyword rules."""
    pass


# TODO 3: Build the LLM classifier agent (STEP 1/2/3)
#   Follow the EXACT same pattern as the demo's build_classifier_agent():
#   STEP 1: BedrockModel with Nova Lite, temperature 0.0
#   STEP 2: System prompt that classifies into: billing, technical, cancellation, general
#           with a confidence score from 0.0 to 1.0
#   STEP 3: Return Agent with the classify_intent tool
#   The classify_intent tool is provided below — just wire the agent.

def build_classifier_agent() -> Agent:
    """LLM-powered intent classifier for ambiguous telecom tickets."""

    @tool
    def classify_intent(intent: str, confidence: float) -> str:
        """
        Record the classified intent and confidence score.

        Args:
            intent: One of: billing, technical, cancellation, general
            confidence: Confidence score from 0.0 to 1.0

        Returns:
            JSON confirmation of classification
        """
        classification_result["intent"] = intent.lower().strip()
        classification_result["confidence"] = min(max(float(confidence), 0.0), 1.0)
        return json.dumps(classification_result, indent=2)

    # TODO 3a: Create BedrockModel (STEP 1)
    # TODO 3b: Write system prompt (STEP 2)
    # TODO 3c: Return Agent (STEP 3)
    pass


INTENT_TO_AGENT = {
    "billing": "BillingAgent",
    "technical": "TechnicalAgent",
    "cancellation": "RetentionAgent",
    "general": "GeneralSupportAgent",
}

CONFIDENCE_THRESHOLD = 0.6


def llm_classify(ticket_text: str) -> tuple:
    """Use LLM to classify ambiguous ticket."""
    classification_result.clear()

    agent = build_classifier_agent()
    t = time.time()
    agent(f"Classify this customer ticket: '{ticket_text}'")
    latency = time.time() - t

    intent = classification_result.get("intent", "general")
    confidence = classification_result.get("confidence", 0.0)
    agent_name = INTENT_TO_AGENT.get(intent, "GeneralSupportAgent")

    return agent_name, confidence, latency


# ═══════════════════════════════════════════════════════
#  HYBRID ROUTER — Already implemented (same as demo)
# ═══════════════════════════════════════════════════════

def hybrid_route(ticket: dict) -> dict:
    """Route a ticket: Priority → Rules → LLM → Fallback"""
    text = ticket["text"]
    t_start = time.time()

    # 1. Priority check
    target = priority_route(text)
    if target:
        latency_ms = (time.time() - t_start) * 1000
        return {
            "target_agent": target, "method": "priority", "confidence": 1.0,
            "latency_ms": latency_ms, "reason": "Cancellation intent detected",
        }

    # 2. Rule-based
    target = rule_based_route(text)
    if target:
        latency_ms = (time.time() - t_start) * 1000
        return {
            "target_agent": target, "method": "rule", "confidence": 1.0,
            "latency_ms": latency_ms, "reason": "Keyword match in ticket text",
        }

    # 3. LLM classification
    agent_name, confidence, llm_latency = llm_classify(text)
    latency_ms = (time.time() - t_start) * 1000

    if confidence >= CONFIDENCE_THRESHOLD:
        return {
            "target_agent": agent_name, "method": "llm", "confidence": confidence,
            "latency_ms": latency_ms,
            "reason": f"LLM classified as '{classification_result.get('intent', '?')}' ({confidence:.2f})",
        }

    # 4. Fallback
    return {
        "target_agent": "GeneralSupportAgent", "method": "fallback",
        "confidence": confidence, "latency_ms": latency_ms,
        "reason": f"Low confidence ({confidence:.2f}) — flagged for human review",
    }


# ═══════════════════════════════════════════════════════
#  WORKER AGENTS — Build each using STEP 1/2/3 from demo
# ═══════════════════════════════════════════════════════

def build_billing_agent() -> Agent:
    """Worker: Handles billing-related tickets."""

    # TODO 4: Create BedrockModel (STEP 1)
    # TODO 5: Write system prompt (STEP 2) — call handle_billing, report result
    # TODO 6: Return Agent (STEP 3)

    @tool
    def handle_billing(ticket_id: str) -> str:
        """Handle a billing-related support ticket."""
        ticket = next((t for t in TICKETS if t["id"] == ticket_id), None)
        if not ticket:
            return json.dumps({"error": f"Ticket {ticket_id} not found"})
        result = {
            "ticket_id": ticket_id, "action": "billing_resolved",
            "resolution": "Account reviewed — adjustments applied if applicable",
            "case_id": f"BILL-{ticket_id[-3:]}-{int(time.time()) % 10000}",
            "status": "resolved",
        }
        worker_response["result"] = result
        return json.dumps(result, indent=2)

    pass


def build_technical_agent() -> Agent:
    """Worker: Handles technical support tickets."""

    # TODO 7: Create BedrockModel (STEP 1)
    # TODO 8: Write system prompt (STEP 2) — call handle_technical, report result
    # TODO 9: Return Agent (STEP 3)

    @tool
    def handle_technical(ticket_id: str) -> str:
        """Handle a technical support ticket."""
        ticket = next((t for t in TICKETS if t["id"] == ticket_id), None)
        if not ticket:
            return json.dumps({"error": f"Ticket {ticket_id} not found"})
        result = {
            "ticket_id": ticket_id, "action": "technical_diagnosed",
            "resolution": "Issue diagnosed — troubleshooting steps applied",
            "case_id": f"TECH-{ticket_id[-3:]}-{int(time.time()) % 10000}",
            "status": "in_progress",
        }
        worker_response["result"] = result
        return json.dumps(result, indent=2)

    pass


def build_retention_agent() -> Agent:
    """Worker: Handles cancellation requests (retention specialist)."""

    # TODO 10: Create BedrockModel (STEP 1)
    # TODO 11: Write system prompt (STEP 2) — call handle_retention, report result
    # TODO 12: Return Agent (STEP 3)

    @tool
    def handle_retention(ticket_id: str) -> str:
        """Handle a cancellation request with retention offer."""
        result = {
            "ticket_id": ticket_id, "action": "retention_offer",
            "offer": "20% discount for 6 months + free premium channel package",
            "escalation": "Retention specialist assigned",
            "case_id": f"RET-{ticket_id[-3:]}-{int(time.time()) % 10000}",
            "status": "pending_customer_response",
        }
        worker_response["result"] = result
        return json.dumps(result, indent=2)

    pass


def build_general_support_agent() -> Agent:
    """Worker: Fallback for unclassifiable tickets."""

    # TODO 13: Create BedrockModel (STEP 1)
    # TODO 14: Write system prompt (STEP 2) — call handle_general, report result
    # TODO 15: Return Agent (STEP 3)

    @tool
    def handle_general(ticket_id: str) -> str:
        """Create a general support ticket (flagged for human review)."""
        result = {
            "ticket_id": ticket_id, "action": "general_support",
            "ticket_ref": f"GEN-{ticket_id[-3:]}-{int(time.time()) % 10000}",
            "status": "awaiting_human_review", "priority": "normal",
        }
        worker_response["result"] = result
        return json.dumps(result, indent=2)

    pass


AGENT_BUILDERS = {
    "BillingAgent": build_billing_agent,
    "TechnicalAgent": build_technical_agent,
    "RetentionAgent": build_retention_agent,
    "GeneralSupportAgent": build_general_support_agent,
}


# ═══════════════════════════════════════════════════════
#  MAIN — Already implemented
# ═══════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("  Telecom Customer Ticket Router — Module 5 Exercise")
    print("  Hybrid Routing: Priority + Rules + LLM + Fallback")
    print("  4 Specialist Agents + 1 Classifier Agent")
    print("  20 Tickets (8 billing, 6 technical, 2 cancellation, 4 ambiguous)")
    print("=" * 70)

    results = []

    for ticket in TICKETS:
        tkt_id = ticket["id"]
        print(f"\n{'━' * 70}")
        print(f"  Ticket: {tkt_id}")
        print(f"  Text: \"{ticket['text'][:65]}\"")
        print(f"  Expected: {ticket['expected_agent']} ({ticket['expected_method']})")

        worker_response.clear()
        t_total_start = time.time()

        routing = hybrid_route(ticket)
        target = routing["target_agent"]
        method = routing["method"]

        print(f"  → Routed to: {target} ({method}, conf: {routing['confidence']:.2f})")

        builder = AGENT_BUILDERS[target]
        exec_time = run_agent_with_retry(
            builder,
            f"Process ticket {tkt_id}: {ticket['text']}",
        )

        total_time = time.time() - t_total_start
        result_data = worker_response.get("result", {})
        print(f"    {result_data.get('action', '?')} — {result_data.get('status', '?')} ({total_time:.1f}s)")

        log_routing_decision(
            ticket_id=tkt_id, input_text=ticket["text"], method=method,
            target_agent=target, confidence=routing["confidence"],
            latency_ms=routing["latency_ms"],
        )

        expected = ticket["expected_agent"]
        correct = (expected in ("LLM-classified",) or target == expected)

        results.append({
            "id": tkt_id, "target": target, "method": method,
            "confidence": routing["confidence"], "expected": expected,
            "correct": correct, "total_s": round(total_time, 1),
        })

    # ── Routing Effectiveness Report ─────────────────────
    print(f"\n{'═' * 70}")
    print("  ROUTING EFFECTIVENESS REPORT")
    print(f"{'═' * 70}")
    print(f"  {'ID':<10} {'Target':<22} {'Method':<10} {'Conf.':<7} {'Time':<7} {'Match'}")
    print(f"  {'─' * 65}")
    for r in results:
        match_str = "✓" if r["correct"] else "✗"
        print(f"  {r['id']:<10} {r['target']:<22} {r['method']:<10} {r['confidence']:<7.2f} {r['total_s']:<7.1f} {match_str}")

    correct_count = sum(1 for r in results if r["correct"])
    print(f"\n  Routing Accuracy: {correct_count}/{len(results)} ({correct_count/len(results)*100:.0f}%)")

    methods = {}
    for r in results:
        m = r["method"]
        if m not in methods:
            methods[m] = {"count": 0, "total_time": 0}
        methods[m]["count"] += 1
        methods[m]["total_time"] += r["total_s"]

    print(f"\n  Method Distribution:")
    print(f"  {'Method':<12} {'Count':<8} {'Pct':<8} {'Avg Time':<10}")
    print(f"  {'─' * 40}")
    for m in ["priority", "rule", "llm", "fallback"]:
        if m in methods:
            info = methods[m]
            pct = info["count"] / len(results) * 100
            avg = info["total_time"] / info["count"]
            print(f"  {m:<12} {info['count']:<8} {pct:<8.0f}% {avg:<10.1f}s")

    agents = {}
    for r in results:
        a = r["target"]
        agents[a] = agents.get(a, 0) + 1

    print(f"\n  Agent Distribution:")
    for a in ["BillingAgent", "TechnicalAgent", "RetentionAgent", "GeneralSupportAgent"]:
        if a in agents:
            print(f"    {a:<22} {agents[a]} tickets")

    scan_result = audit_table.scan()
    audit_entries = scan_result.get("Items", [])
    print(f"\n  Audit Log: {len(audit_entries)} entries (DynamoDB: {ROUTING_AUDIT_TABLE})")

    print(f"\n  Key Insight: Same hybrid routing pattern, different domain.")
    print(f"  Rules handle 70% cheaply, LLM handles the ambiguous tail,")
    print(f"  priority catches business-critical requests, fallback ensures nothing drops.\n")


if __name__ == "__main__":
    main()
