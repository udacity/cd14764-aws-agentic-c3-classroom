"""
telecom_router.py - EXERCISE SOLUTION (Student-Led)
====================================================
Module 5 Exercise: Build a Multi-Strategy Router for Telecom Customer Tickets

Architecture:
    Incoming Ticket
         │
    ┌────┴────┐
    │ PRIORITY │  Cancellation intent detected?
    │  Check   │  YES → RetentionAgent (bypass all other routing)
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
    │ CLASSIFY│  Returns {intent, confidence}
    │         │  confidence ≥ 0.6 → route to classified agent
    └────┬────┘
         │ LOW CONFIDENCE
    ┌────┴────┐
    │FALLBACK │  GeneralSupportAgent
    │         │  (flag for human review)
    └─────────┘

Same hybrid routing pattern as the demo (financial_router.py),
applied to a different domain:
  - Demo: Financial transactions (payments/fraud/account)
  - Exercise: Telecom support tickets (billing/technical/cancellation)

Tech Stack:
  - Python 3.11+
  - Strands Agents SDK (Agent class, @tool decorator)
  - Amazon Bedrock (Nova Lite for all agents)
  - DynamoDB audit log (real AWS resource — created by CloudFormation)
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


# Configuration
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
NOVA_LITE_MODEL = os.environ.get("NOVA_LITE_MODEL", "amazon.nova-lite-v1:0")

# Sample telecom tickets (20 total — 8 billing 40%, 6 technical 30%, 2 cancel 10%, 4 ambiguous 20%)
TICKETS = [
    # ── Billing (8 tickets — 40%) → Rule-based → BillingAgent ──
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

    # ── Technical (6 tickets — 30%) → Rule-based → TechnicalAgent ──
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

    # ── Cancellation (2 tickets — 10%) → Priority → RetentionAgent ──
    {"id": "TKT-015", "text": "I want to cancel my service and switch to another provider",
     "expected_agent": "RetentionAgent", "expected_method": "priority"},
    {"id": "TKT-016", "text": "I'm done with this company, please cancel everything immediately",
     "expected_agent": "RetentionAgent", "expected_method": "priority"},

    # ── Ambiguous (4 tickets — 20%) → LLM or Fallback ──
    {"id": "TKT-017", "text": "My phone isn't working right, something is definitely wrong",
     "expected_agent": "LLM-classified", "expected_method": "llm"},
    {"id": "TKT-018", "text": "I've been having problems ever since I upgraded my plan last week",
     "expected_agent": "LLM-classified", "expected_method": "llm"},
    {"id": "TKT-019", "text": "Nothing works and I'm very frustrated with everything",
     "expected_agent": "LLM-classified", "expected_method": "llm"},
    {"id": "TKT-020", "text": "purple elephant moonbeam random gibberish xkcd 42",
     "expected_agent": "GeneralSupportAgent", "expected_method": "fallback"},
]

# DynamoDB audit table (real AWS resource — created by CloudFormation)
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


# Routing strategies (same hybrid pattern as demo)

# STEP 1: Priority routing (cancellation detection → RetentionAgent)

PRIORITY_PATTERNS = [
    r"\b(cancel\w*|switch provider|terminate|discontinue|done with this company)\b",
    r"\bleave\b.*\b(provider|service|company|carrier|plan)\b",
]


def priority_route(text: str) -> str | None:
    """
    Check if ticket contains cancellation intent.
    Returns 'RetentionAgent' or None.
    """
    text_lower = text.lower()
    for pattern in PRIORITY_PATTERNS:
        if re.search(pattern, text_lower):
            return "RetentionAgent"
    return None


# STEP 2: Rule-based routing (billing/technical keywords)

ROUTING_RULES = [
    (r"\b(bill\w*|charg\w*|payment\w*|invoice\w*|subscription\w*|rate\b|roaming)\b", "BillingAgent"),
    (r"\b(outage|no signal|slow\w*|drop\w*|disconnect\w*|no service|tower)\b", "TechnicalAgent"),
]


def rule_based_route(text: str) -> str | None:
    """
    Match ticket text against keyword rules.
    Returns agent name or None.
    """
    text_lower = text.lower()
    for pattern, agent_name in ROUTING_RULES:
        if re.search(pattern, text_lower):
            return agent_name
    return None


# STEP 3: LLM classification (ambiguous tickets)

def build_classifier_agent() -> Agent:
    """LLM-powered intent classifier for ambiguous telecom tickets."""

    # STEP 1: BedrockModel — Nova Lite for fast classification
    model = BedrockModel(model_id=NOVA_LITE_MODEL, region_name=AWS_REGION, temperature=0.0)

    # STEP 2: System prompt — structured classification
    system_prompt = """You are an intent classifier for a telecom support system.

Classify the customer ticket into ONE of these intents:
- billing: charges, invoices, payment issues, plan pricing
- technical: outages, signal problems, slow internet, dropped calls, device issues
- cancellation: wants to cancel, switch providers, leave
- general: unclear, off-topic, or doesn't fit other categories

Call classify_intent with:
- intent: one of [billing, technical, cancellation, general]
- confidence: your confidence from 0.0 to 1.0

Rules:
- If the ticket clearly fits a category, confidence should be 0.8-1.0
- If it's ambiguous but you can guess, confidence should be 0.5-0.7
- If it's nonsensical or unrelated to telecom, use intent='general' with low confidence

Call the tool ONCE. Do NOT add commentary."""

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

    # STEP 3: Build Agent
    return Agent(model=model, system_prompt=system_prompt, tools=[classify_intent])


# Map LLM intents to agent names
INTENT_TO_AGENT = {
    "billing": "BillingAgent",
    "technical": "TechnicalAgent",
    "cancellation": "RetentionAgent",
    "general": "GeneralSupportAgent",
}

CONFIDENCE_THRESHOLD = 0.6


def llm_classify(ticket_text: str) -> tuple:
    """
    Use LLM to classify ambiguous ticket.
    Returns (agent_name, confidence, latency_s).
    """
    classification_result.clear()

    agent = build_classifier_agent()
    t = time.time()
    agent(f"Classify this customer ticket: '{ticket_text}'")
    latency = time.time() - t

    intent = classification_result.get("intent", "general")
    confidence = classification_result.get("confidence", 0.0)
    agent_name = INTENT_TO_AGENT.get(intent, "GeneralSupportAgent")

    return agent_name, confidence, latency


# Hybrid router

def hybrid_route(ticket: dict) -> dict:
    """
    Route a ticket using the hybrid strategy.
    Order: Priority → Rules → LLM → Fallback
    """
    text = ticket["text"]
    t_start = time.time()

    # 1. Priority check (cancellation → RetentionAgent)
    target = priority_route(text)
    if target:
        latency_ms = (time.time() - t_start) * 1000
        return {
            "target_agent": target,
            "method": "priority",
            "confidence": 1.0,
            "latency_ms": latency_ms,
            "reason": "Cancellation intent detected — routed to retention",
        }

    # 2. Rule-based matching
    target = rule_based_route(text)
    if target:
        latency_ms = (time.time() - t_start) * 1000
        return {
            "target_agent": target,
            "method": "rule",
            "confidence": 1.0,
            "latency_ms": latency_ms,
            "reason": "Keyword match in ticket text",
        }

    # 3. LLM classification
    agent_name, confidence, llm_latency = llm_classify(text)
    latency_ms = (time.time() - t_start) * 1000

    if confidence >= CONFIDENCE_THRESHOLD:
        return {
            "target_agent": agent_name,
            "method": "llm",
            "confidence": confidence,
            "latency_ms": latency_ms,
            "reason": f"LLM classified as '{classification_result.get('intent', '?')}' "
                      f"(confidence: {confidence:.2f})",
        }

    # 4. Fallback
    return {
        "target_agent": "GeneralSupportAgent",
        "method": "fallback",
        "confidence": confidence,
        "latency_ms": latency_ms,
        "reason": f"LLM confidence {confidence:.2f} below {CONFIDENCE_THRESHOLD} "
                  f"— flagged for human review",
    }


# Worker agents

def build_billing_agent() -> Agent:
    """Worker: Handles billing-related tickets."""

    # STEP 1: BedrockModel
    model = BedrockModel(model_id=NOVA_LITE_MODEL, region_name=AWS_REGION, temperature=0.0)

    # STEP 2: System prompt
    system_prompt = """You are a billing support agent. Your ONLY job:
1. Call handle_billing with the ticket_id
2. Report: Billing issue handled for <ticket_id>
Do NOT add any other commentary."""

    @tool
    def handle_billing(ticket_id: str) -> str:
        """
        Handle a billing-related support ticket.

        Args:
            ticket_id: The ticket ID (e.g., "TKT-001")

        Returns:
            JSON with billing resolution details
        """
        ticket = next((t for t in TICKETS if t["id"] == ticket_id), None)
        if not ticket:
            return json.dumps({"error": f"Ticket {ticket_id} not found"})

        result = {
            "ticket_id": ticket_id,
            "action": "billing_resolved",
            "resolution": "Account reviewed — adjustments applied if applicable",
            "case_id": f"BILL-{ticket_id[-3:]}-{int(time.time()) % 10000}",
            "status": "resolved",
        }
        worker_response["result"] = result
        return json.dumps(result, indent=2)

    # STEP 3: Build Agent
    return Agent(model=model, system_prompt=system_prompt, tools=[handle_billing])


def build_technical_agent() -> Agent:
    """Worker: Handles technical support tickets."""

    model = BedrockModel(model_id=NOVA_LITE_MODEL, region_name=AWS_REGION, temperature=0.0)

    system_prompt = """You are a technical support agent. Your ONLY job:
1. Call handle_technical with the ticket_id
2. Report: Technical issue handled for <ticket_id>
Do NOT add any other commentary."""

    @tool
    def handle_technical(ticket_id: str) -> str:
        """
        Handle a technical support ticket.

        Args:
            ticket_id: The ticket ID

        Returns:
            JSON with technical resolution details
        """
        ticket = next((t for t in TICKETS if t["id"] == ticket_id), None)
        if not ticket:
            return json.dumps({"error": f"Ticket {ticket_id} not found"})

        result = {
            "ticket_id": ticket_id,
            "action": "technical_diagnosed",
            "resolution": "Issue diagnosed — troubleshooting steps applied",
            "case_id": f"TECH-{ticket_id[-3:]}-{int(time.time()) % 10000}",
            "status": "in_progress",
        }
        worker_response["result"] = result
        return json.dumps(result, indent=2)

    return Agent(model=model, system_prompt=system_prompt, tools=[handle_technical])


def build_retention_agent() -> Agent:
    """Worker: Handles cancellation requests (retention specialist)."""

    model = BedrockModel(model_id=NOVA_LITE_MODEL, region_name=AWS_REGION, temperature=0.0)

    system_prompt = """You are a customer retention agent. Your ONLY job:
1. Call handle_retention with the ticket_id
2. Report: Retention case opened for <ticket_id>
Do NOT add any other commentary."""

    @tool
    def handle_retention(ticket_id: str) -> str:
        """
        Handle a cancellation request with retention offer.

        Args:
            ticket_id: The ticket ID

        Returns:
            JSON with retention offer details
        """
        result = {
            "ticket_id": ticket_id,
            "action": "retention_offer",
            "offer": "20% discount for 6 months + free premium channel package",
            "escalation": "Retention specialist assigned",
            "case_id": f"RET-{ticket_id[-3:]}-{int(time.time()) % 10000}",
            "status": "pending_customer_response",
        }
        worker_response["result"] = result
        return json.dumps(result, indent=2)

    return Agent(model=model, system_prompt=system_prompt, tools=[handle_retention])


def build_general_support_agent() -> Agent:
    """Worker: Fallback for unclassifiable tickets."""

    model = BedrockModel(model_id=NOVA_LITE_MODEL, region_name=AWS_REGION, temperature=0.0)

    system_prompt = """You are a general support agent. Your ONLY job:
1. Call handle_general with the ticket_id
2. Report: Support ticket created for <ticket_id>
Do NOT add any other commentary."""

    @tool
    def handle_general(ticket_id: str) -> str:
        """
        Create a general support ticket (flagged for human review).

        Args:
            ticket_id: The ticket ID

        Returns:
            JSON with support ticket details
        """
        result = {
            "ticket_id": ticket_id,
            "action": "general_support",
            "ticket_ref": f"GEN-{ticket_id[-3:]}-{int(time.time()) % 10000}",
            "status": "awaiting_human_review",
            "priority": "normal",
        }
        worker_response["result"] = result
        return json.dumps(result, indent=2)

    return Agent(model=model, system_prompt=system_prompt, tools=[handle_general])


AGENT_BUILDERS = {
    "BillingAgent": build_billing_agent,
    "TechnicalAgent": build_technical_agent,
    "RetentionAgent": build_retention_agent,
    "GeneralSupportAgent": build_general_support_agent,
}


# Main — Process all 20 tickets

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

        # Route
        routing = hybrid_route(ticket)
        target = routing["target_agent"]
        method = routing["method"]

        print(f"  → Routed to: {target} ({method}, conf: {routing['confidence']:.2f})")

        # Execute
        builder = AGENT_BUILDERS[target]
        exec_time = run_agent_with_retry(
            builder,
            f"Process ticket {tkt_id}: {ticket['text']}",
        )

        total_time = time.time() - t_total_start
        result_data = worker_response.get("result", {})
        print(f"    {result_data.get('action', '?')} — {result_data.get('status', '?')} ({total_time:.1f}s)")

        # Log
        log_routing_decision(
            ticket_id=tkt_id,
            input_text=ticket["text"],
            method=method,
            target_agent=target,
            confidence=routing["confidence"],
            latency_ms=routing["latency_ms"],
        )

        expected = ticket["expected_agent"]
        correct = (expected in ("LLM-classified",) or target == expected)

        results.append({
            "id": tkt_id,
            "target": target,
            "method": method,
            "confidence": routing["confidence"],
            "expected": expected,
            "correct": correct,
            "total_s": round(total_time, 1),
        })

    # ── Routing Summary ──────────────────────────────────
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

    # ── Method Distribution ──────────────────────────────
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

    # ── Agent Distribution ───────────────────────────────
    agents = {}
    for r in results:
        a = r["target"]
        agents[a] = agents.get(a, 0) + 1

    print(f"\n  Agent Distribution:")
    for a in ["BillingAgent", "TechnicalAgent", "RetentionAgent", "GeneralSupportAgent"]:
        if a in agents:
            print(f"    {a:<22} {agents[a]} tickets")

    # ── Audit Log Summary (DynamoDB) ─────────────────────
    scan_result = audit_table.scan()
    audit_entries = scan_result.get("Items", [])
    print(f"\n  Audit Log: {len(audit_entries)} entries logged (DynamoDB: {ROUTING_AUDIT_TABLE})")
    rule_count = sum(1 for e in audit_entries if e.get("routing_method") == "rule")
    llm_count = sum(1 for e in audit_entries if e.get("routing_method") == "llm")
    priority_count = sum(1 for e in audit_entries if e.get("routing_method") == "priority")
    fallback_count = sum(1 for e in audit_entries if e.get("routing_method") == "fallback")
    print(f"    Rule: {rule_count} | LLM: {llm_count} | Priority: {priority_count} | Fallback: {fallback_count}")

    print(f"\n  Key Insight: Same hybrid routing pattern as demo, different domain:")
    print(f"  - Rules handle billing (40%) + technical (30%) = 70% of volume")
    print(f"  - Priority catches cancellations (10%) for retention")
    print(f"  - LLM classifies the ambiguous 20% that rules miss")
    print(f"  - Fallback ensures nothing gets dropped")
    print(f"  Rules first, LLM second saves 70-80% of classification costs.\n")


if __name__ == "__main__":
    main()
