"""
financial_router.py - DEMO (Instructor-Led)
=============================================
Module 5 Demo: Building a Hybrid Router for Financial Transaction Processing

Architecture:
    Incoming Request
         │
    ┌────┴────┐
    │ PRIORITY │  Check first: amount > $10,000?
    │  Check   │  YES → SeniorReviewAgent (bypass all other routing)
    └────┬────┘
         │ NO
    ┌────┴────┐
    │ RULE-   │  Keyword/regex matching
    │ BASED   │  wire/transfer → PaymentsAgent
    │ ROUTER  │  fraud/stolen  → FraudAgent
    │         │  balance/stmt  → AccountAgent
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

Key Concepts (NEW in Module 5):
  1. RULE-BASED ROUTING: Fast, free, deterministic — handles 70% of requests
  2. LLM CLASSIFICATION: Flexible, handles ambiguity — handles remaining 30%
  3. PRIORITY ROUTING: Business-critical override (high-value transactions)
  4. FALLBACK: Safety net when both rules and LLM are uncertain
  5. AUDIT LOGGING: Every routing decision logged to DynamoDB

Tech Stack:
  - Python 3.11+
  - Strands Agents SDK (Agent class, @tool decorator)
  - Amazon Bedrock (Nova Lite for all agents — routing needs speed, not depth)
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
NOVA_LITE_MODEL = os.environ.get("NOVA_LITE_MODEL", "amazon.nova-lite-v1:0")   # All agents use Nova Lite (routing needs speed)

# Sample financial requests (10 total — covers rule/priority/LLM/fallback)
REQUESTS = [
    # ── Rule-based routing (4 requests) ──
    {"id": "TXN-001", "text": "I need to wire $5,000 to account 12345",
     "amount": 5000, "expected_agent": "PaymentsAgent", "expected_method": "rule"},
    {"id": "TXN-002", "text": "Please transfer $2,000 from checking to savings",
     "amount": 2000, "expected_agent": "PaymentsAgent", "expected_method": "rule"},
    {"id": "TXN-003", "text": "My credit card was stolen and someone made unauthorized charges",
     "amount": 0, "expected_agent": "FraudAgent", "expected_method": "rule"},
    {"id": "TXN-004", "text": "I see a fraudulent charge of $500 on my account",
     "amount": 500, "expected_agent": "FraudAgent", "expected_method": "rule"},
    # ── Rule-based routing (2 more — AccountAgent) ──
    {"id": "TXN-005", "text": "What is my current account balance?",
     "amount": 0, "expected_agent": "AccountAgent", "expected_method": "rule"},
    {"id": "TXN-006", "text": "Can you send me my monthly statement for March?",
     "amount": 0, "expected_agent": "AccountAgent", "expected_method": "rule"},
    # ── Priority routing (2 requests — amount > $10,000) ──
    {"id": "TXN-007", "text": "Wire $50,000 to an overseas account for property purchase",
     "amount": 50000, "expected_agent": "SeniorReviewAgent", "expected_method": "priority"},
    {"id": "TXN-008", "text": "I need to transfer $25,000 for a real estate closing",
     "amount": 25000, "expected_agent": "SeniorReviewAgent", "expected_method": "priority"},
    # ── LLM-classified (1 ambiguous request) ──
    {"id": "TXN-009", "text": "I need some help with my money situation, things are complicated",
     "amount": 0, "expected_agent": "LLM-classified", "expected_method": "llm"},
    # ── Fallback (1 nonsensical request) ──
    {"id": "TXN-010", "text": "purple elephant moonlight dancing xkcd random words",
     "amount": 0, "expected_agent": "GeneralSupportAgent", "expected_method": "fallback"},
]

# DynamoDB audit table (real AWS resource — created by CloudFormation)
ROUTING_AUDIT_TABLE = os.environ.get("ROUTING_AUDIT_TABLE", "lesson-05-routing-routing-audit")
dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
audit_table = dynamodb.Table(ROUTING_AUDIT_TABLE)


def log_routing_decision(request_id: str, input_text: str, method: str,
                         target_agent: str, confidence: float, latency_ms: float):
    """
    Log a routing decision to DynamoDB.

    Table schema (from CloudFormation):
      PK: request_id (S)  |  SK: timestamp (S)
      Attributes: input_text, routing_method, target_agent, confidence, latency_ms
    """
    entry = {
        "request_id": request_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "input_text": input_text[:80],
        "routing_method": method,
        "target_agent": target_agent,
        "confidence": str(confidence),
        "latency_ms": str(round(latency_ms, 1)),
        "ttl": int(time.time()) + 86400,  # Auto-delete after 24 hours
    }
    audit_table.put_item(Item=entry)


# Shared state for LLM classifier results
classification_result = {}
# Shared state for worker agent responses
worker_response = {}


# Routing strategies (Python code — deterministic, debuggable)
# Order: Priority → Rules → LLM → Fallback

# STEP 1: Priority routing (high-value override)

def priority_route(request: dict) -> str | None:
    """Check if request is high-priority (amount > $10,000)."""
    if request.get("amount", 0) > 10000:
        return "SeniorReviewAgent"
    return None


# STEP 2: Rule-based routing (keyword/regex — 70% of requests, fast/free)

ROUTING_RULES = [
    # (pattern, target_agent)
    (r"\b(wire|transfer|send money|payment)\b", "PaymentsAgent"),
    (r"\b(fraud\w*|stolen|unauthorized|suspicious)\b", "FraudAgent"),
    (r"\b(balance|statement|account info|account history)\b", "AccountAgent"),
]


def rule_based_route(text: str) -> str | None:
    """
    Match request text against keyword rules.
    Returns target agent name or None if no rule matches.
    """
    text_lower = text.lower()
    for pattern, agent_name in ROUTING_RULES:
        if re.search(pattern, text_lower):
            return agent_name
    return None


# STEP 3: LLM classification (ambiguous requests, confidence >= 0.6)

def build_classifier_agent() -> Agent:
    """LLM-powered intent classifier for ambiguous requests."""

    # STEP 1: BedrockModel — Nova Lite for fast classification
    model = BedrockModel(model_id=NOVA_LITE_MODEL, region_name=AWS_REGION, temperature=0.0)

    # STEP 2: System prompt — structured classification output
    system_prompt = """You are an intent classifier for a financial services platform.

Classify the customer request into ONE of these intents:
- payments: wire transfers, fund transfers, payment processing
- fraud: suspicious activity, stolen cards, unauthorized charges
- account: balance inquiries, statements, account information
- general: unclear, off-topic, or doesn't fit other categories

Call classify_intent with:
- intent: one of [payments, fraud, account, general]
- confidence: your confidence from 0.0 to 1.0

Rules:
- If the request clearly fits a category, confidence should be 0.8-1.0
- If it's ambiguous but you can guess, confidence should be 0.5-0.7
- If it's nonsensical or unrelated to finance, use intent='general' with low confidence

Call the tool ONCE with your classification. Do NOT add commentary."""

    @tool
    def classify_intent(intent: str, confidence: float) -> str:
        """
        Record the classified intent and confidence score.

        Args:
            intent: One of: payments, fraud, account, general
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
    "payments": "PaymentsAgent",
    "fraud": "FraudAgent",
    "account": "AccountAgent",
    "general": "GeneralSupportAgent",
}

CONFIDENCE_THRESHOLD = 0.6


def llm_classify(request_text: str) -> tuple:
    """
    Use LLM to classify ambiguous request.
    Returns (agent_name, confidence, latency_s).
    """
    classification_result.clear()

    agent = build_classifier_agent()
    t = time.time()
    agent(f"Classify this customer request: '{request_text}'")
    latency = time.time() - t

    intent = classification_result.get("intent", "general")
    confidence = classification_result.get("confidence", 0.0)
    agent_name = INTENT_TO_AGENT.get(intent, "GeneralSupportAgent")

    return agent_name, confidence, latency


# Hybrid router — combines all strategies

def hybrid_route(request: dict) -> dict:
    """
    Route a request using the hybrid strategy.

    Returns dict with routing decision:
        target_agent, method, confidence, latency_ms
    """
    text = request["text"]
    t_start = time.time()

    # 1. Priority check (business-critical override)
    target = priority_route(request)
    if target:
        latency_ms = (time.time() - t_start) * 1000
        return {
            "target_agent": target,
            "method": "priority",
            "confidence": 1.0,
            "latency_ms": latency_ms,
            "reason": f"Amount ${request['amount']:,.0f} exceeds $10,000 threshold",
        }

    # 2. Rule-based matching (fast, free, deterministic)
    target = rule_based_route(text)
    if target:
        latency_ms = (time.time() - t_start) * 1000
        return {
            "target_agent": target,
            "method": "rule",
            "confidence": 1.0,
            "latency_ms": latency_ms,
            "reason": f"Keyword match in request text",
        }

    # 3. LLM classification (flexible, handles ambiguity)
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

    # 4. Fallback (safety net — flag for human review)
    return {
        "target_agent": "GeneralSupportAgent",
        "method": "fallback",
        "confidence": confidence,
        "latency_ms": latency_ms,
        "reason": f"LLM confidence {confidence:.2f} below threshold {CONFIDENCE_THRESHOLD} "
                  f"— flagged for human review",
    }


# Worker agents — Specialist agents (router decides who handles what)

def build_payments_agent() -> Agent:
    """Worker: Processes payment and transfer requests."""

    # STEP 1: BedrockModel — Nova Lite for fast execution
    model = BedrockModel(model_id=NOVA_LITE_MODEL, region_name=AWS_REGION, temperature=0.0)

    # STEP 2: System prompt
    system_prompt = """You are a payments processing agent. Your ONLY job:
1. Call process_payment with the request_id
2. Report: Payment processed for <request_id>: <summary>
Do NOT add any other commentary."""

    @tool
    def process_payment(request_id: str) -> str:
        """
        Process a payment or transfer request.

        Args:
            request_id: The transaction ID (e.g., "TXN-001")

        Returns:
            JSON with payment processing result
        """
        req = next((r for r in REQUESTS if r["id"] == request_id), None)
        if not req:
            return json.dumps({"error": f"Request {request_id} not found"})

        result = {
            "request_id": request_id,
            "action": "payment_processed",
            "amount": req["amount"],
            "status": "completed",
            "reference": f"PAY-{request_id[-3:]}-{int(time.time()) % 10000}",
        }
        worker_response["result"] = result
        return json.dumps(result, indent=2)

    # STEP 3: Build Agent
    return Agent(model=model, system_prompt=system_prompt, tools=[process_payment])


def build_fraud_agent() -> Agent:
    """Worker: Investigates fraud reports."""

    model = BedrockModel(model_id=NOVA_LITE_MODEL, region_name=AWS_REGION, temperature=0.0)

    system_prompt = """You are a fraud investigation agent. Your ONLY job:
1. Call investigate_fraud with the request_id
2. Report: Fraud alert logged for <request_id>: <summary>
Do NOT add any other commentary."""

    @tool
    def investigate_fraud(request_id: str) -> str:
        """
        Investigate a fraud report.

        Args:
            request_id: The transaction ID

        Returns:
            JSON with fraud investigation result
        """
        req = next((r for r in REQUESTS if r["id"] == request_id), None)
        if not req:
            return json.dumps({"error": f"Request {request_id} not found"})

        result = {
            "request_id": request_id,
            "action": "fraud_investigated",
            "risk_level": "high" if req["amount"] > 1000 else "medium",
            "status": "under_review",
            "case_id": f"FRAUD-{request_id[-3:]}-{int(time.time()) % 10000}",
        }
        worker_response["result"] = result
        return json.dumps(result, indent=2)

    return Agent(model=model, system_prompt=system_prompt, tools=[investigate_fraud])


def build_account_agent() -> Agent:
    """Worker: Handles account inquiries."""

    model = BedrockModel(model_id=NOVA_LITE_MODEL, region_name=AWS_REGION, temperature=0.0)

    system_prompt = """You are an account services agent. Your ONLY job:
1. Call lookup_account with the request_id
2. Report: Account info for <request_id>: <summary>
Do NOT add any other commentary."""

    @tool
    def lookup_account(request_id: str) -> str:
        """
        Look up account information.

        Args:
            request_id: The transaction ID

        Returns:
            JSON with account information
        """
        result = {
            "request_id": request_id,
            "action": "account_lookup",
            "balance": 15420.50,
            "last_statement": "2025-03-01",
            "status": "active",
        }
        worker_response["result"] = result
        return json.dumps(result, indent=2)

    return Agent(model=model, system_prompt=system_prompt, tools=[lookup_account])


def build_senior_review_agent() -> Agent:
    """Worker: Handles high-value transactions requiring senior review."""

    model = BedrockModel(model_id=NOVA_LITE_MODEL, region_name=AWS_REGION, temperature=0.0)

    system_prompt = """You are a senior transaction review agent. Your ONLY job:
1. Call senior_review with the request_id
2. Report: Senior review for <request_id>: <summary>
Do NOT add any other commentary."""

    @tool
    def senior_review(request_id: str) -> str:
        """
        Perform senior review on a high-value transaction.

        Args:
            request_id: The transaction ID

        Returns:
            JSON with senior review result
        """
        req = next((r for r in REQUESTS if r["id"] == request_id), None)
        if not req:
            return json.dumps({"error": f"Request {request_id} not found"})

        result = {
            "request_id": request_id,
            "action": "senior_review",
            "amount": req["amount"],
            "risk_assessment": "elevated" if req["amount"] > 25000 else "moderate",
            "approval_required": True,
            "reviewer": "Senior Compliance Officer",
            "status": "pending_approval",
        }
        worker_response["result"] = result
        return json.dumps(result, indent=2)

    return Agent(model=model, system_prompt=system_prompt, tools=[senior_review])


def build_general_support_agent() -> Agent:
    """Worker: Fallback agent for unclassifiable requests."""

    model = BedrockModel(model_id=NOVA_LITE_MODEL, region_name=AWS_REGION, temperature=0.0)

    system_prompt = """You are a general support agent. Your ONLY job:
1. Call general_support with the request_id
2. Report: Support ticket created for <request_id>
Do NOT add any other commentary."""

    @tool
    def general_support(request_id: str) -> str:
        """
        Create a general support ticket (flagged for human review).

        Args:
            request_id: The transaction ID

        Returns:
            JSON with support ticket details
        """
        result = {
            "request_id": request_id,
            "action": "support_ticket",
            "ticket_id": f"TICKET-{request_id[-3:]}-{int(time.time()) % 10000}",
            "status": "awaiting_human_review",
            "priority": "normal",
        }
        worker_response["result"] = result
        return json.dumps(result, indent=2)

    return Agent(model=model, system_prompt=system_prompt, tools=[general_support])


# Map agent names to builder functions
AGENT_BUILDERS = {
    "PaymentsAgent": build_payments_agent,
    "FraudAgent": build_fraud_agent,
    "AccountAgent": build_account_agent,
    "SeniorReviewAgent": build_senior_review_agent,
    "GeneralSupportAgent": build_general_support_agent,
}


# Main — Process all requests through hybrid router

def main():
    print("=" * 70)
    print("  Financial Transaction Router — Module 5 Demo")
    print("  Hybrid Routing: Priority + Rules + LLM + Fallback")
    print("  5 Specialist Agents + 1 Classifier Agent")
    print("=" * 70)

    results = []

    for req in REQUESTS:
        req_id = req["id"]
        print(f"\n{'━' * 70}")
        print(f"  Request: {req_id}")
        print(f"  Text: \"{req['text']}\"")
        if req["amount"] > 0:
            print(f"  Amount: ${req['amount']:,.2f}")
        print(f"  Expected: {req['expected_agent']} ({req['expected_method']})")
        print(f"{'━' * 70}")

        # ── Step 1: Route the request ──
        worker_response.clear()
        t_total_start = time.time()

        routing = hybrid_route(req)
        target = routing["target_agent"]
        method = routing["method"]

        print(f"  → Routed to: {target}")
        print(f"    Method: {method} | Confidence: {routing['confidence']:.2f}")
        print(f"    Reason: {routing['reason']}")

        # ── Step 2: Execute the routed request ──
        builder = AGENT_BUILDERS[target]
        exec_time = run_agent_with_retry(
            builder,
            f"Process request {req_id}: {req['text']}",
        )

        total_time = time.time() - t_total_start
        result_data = worker_response.get("result", {})
        print(f"    Result: {result_data.get('action', '?')} — {result_data.get('status', '?')}")
        print(f"    Route: {routing['latency_ms']:.0f}ms | Execute: {exec_time:.1f}s | Total: {total_time:.1f}s")

        # ── Step 3: Log to audit trail (simulated DynamoDB) ──
        log_routing_decision(
            request_id=req_id,
            input_text=req["text"],
            method=method,
            target_agent=target,
            confidence=routing["confidence"],
            latency_ms=routing["latency_ms"],
        )

        # Check if routing was correct
        expected = req["expected_agent"]
        correct = (expected in ("LLM-classified",) or target == expected)

        results.append({
            "id": req_id,
            "target": target,
            "method": method,
            "confidence": routing["confidence"],
            "expected": expected,
            "correct": correct,
            "route_ms": routing["latency_ms"],
            "total_s": round(total_time, 1),
        })

    # ── Routing Summary ──────────────────────────────────
    print(f"\n{'═' * 70}")
    print("  ROUTING SUMMARY")
    print(f"{'═' * 70}")
    print(f"  {'ID':<10} {'Target':<22} {'Method':<10} {'Conf.':<7} {'Time':<7} {'Match':<6}")
    print(f"  {'─' * 65}")
    for r in results:
        match_str = "✓" if r["correct"] else "✗"
        print(f"  {r['id']:<10} {r['target']:<22} {r['method']:<10} {r['confidence']:<7.2f} {r['total_s']:<7.1f} {match_str}")

    correct_count = sum(1 for r in results if r["correct"])
    print(f"\n  Routing Accuracy: {correct_count}/{len(results)}")

    # ── Method Distribution ──────────────────────────────
    methods = {}
    for r in results:
        m = r["method"]
        methods[m] = methods.get(m, 0) + 1

    print(f"\n  Method Distribution:")
    for m, count in sorted(methods.items()):
        pct = count / len(results) * 100
        print(f"    {m:<12} {count} requests ({pct:.0f}%)")

    # ── Agent Distribution ───────────────────────────────
    agents = {}
    for r in results:
        a = r["target"]
        agents[a] = agents.get(a, 0) + 1

    print(f"\n  Agent Distribution:")
    for a, count in sorted(agents.items()):
        print(f"    {a:<22} {count} requests")

    # ── Audit Log (DynamoDB) ─────────────────────────────
    scan_result = audit_table.scan()
    audit_entries = scan_result.get("Items", [])
    audit_entries.sort(key=lambda x: x.get("timestamp", ""))
    print(f"\n  Audit Log ({len(audit_entries)} entries — DynamoDB table: {ROUTING_AUDIT_TABLE}):")
    print(f"  {'ID':<10} {'Method':<10} {'Agent':<22} {'Confidence':<12} {'Latency':<10}")
    print(f"  {'─' * 65}")
    for entry in audit_entries:
        conf = float(entry.get("confidence", 0))
        lat = float(entry.get("latency_ms", 0))
        print(f"  {entry['request_id']:<10} {entry['routing_method']:<10} "
              f"{entry['target_agent']:<22} {conf:<12.2f} "
              f"{lat:<10.1f}ms")

    print(f"\n  Key Insight: Hybrid routing is the production standard:")
    print(f"  1. PRIORITY — business-critical overrides run first (2 requests)")
    print(f"  2. RULES    — keyword matching handles the majority (fast, free)")
    print(f"  3. LLM      — classifies the ambiguous tail (flexible, costs API)")
    print(f"  4. FALLBACK — safety net when confidence is low (human review)")
    print(f"  Rules first, LLM second saves 70-80% of classification API costs.\n")


if __name__ == "__main__":
    main()
