"""
document_analysis.py - DEMO (Instructor-Led)
==============================================
Module 3 Demo: Parallel Document Analysis with Specialist Agents

Architecture:
    System Design Document
              │
    ┌─────────┼─────────────┐
    │         │             │       ← ThreadPoolExecutor (parallel)
  Security  Scalability    Cost
  Reviewer  Reviewer     Reviewer
(Nova Lite) (Claude)    (Nova Pro)
    │         │             │
    └────┬────┴─────────────┘
         │
    Synthesizer Agent (Claude)       ← Combines all 3 reviews
         │
    Launch-Readiness Assessment

Key Concept:
  The 3 specialist agents analyze the SAME document from different angles.
  Since they are INDEPENDENT (no specialist needs another's output),
  we run them in PARALLEL using ThreadPoolExecutor.
  Then a SynthesizerAgent COMBINES their findings into one report.
  This gives us ~3x speedup on the specialist phase.

Tech Stack:
  - Python 3.11+
  - Strands Agents SDK (Agent class, @tool decorator)
  - Amazon Bedrock (Nova Lite, Claude 3 Sonnet, Nova Pro)
  - concurrent.futures.ThreadPoolExecutor (parallel execution)
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
                wait = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                print(f"    [Retry {attempt + 1}/{max_retries}] {e.__class__.__name__}, waiting {wait}s...")
                time.sleep(wait)
            else:
                print(f"    [Failed] {e.__class__.__name__} after {max_retries} attempts")
                raise


# Configuration — Models for specialist and synthesizer agents
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
NOVA_LITE_MODEL = os.environ.get("NOVA_LITE_MODEL", "amazon.nova-lite-v1:0")                    # Security review (fast)
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "anthropic.claude-3-sonnet-20240229-v1:0")     # Scalability + Synthesis (deep)
NOVA_PRO_MODEL = os.environ.get("NOVA_PRO_MODEL", "amazon.nova-pro-v1:0")                      # Cost review (balanced)

# Sample system design documents (for launch review)
DOCUMENTS = [
    {
        "id": "DOC-001",
        "title": "E-Commerce Platform v2.0 — Launch Review",
        "description": "Major platform upgrade with new payment gateway, user authentication overhaul, and product recommendation engine.",
        "components": [
            "React frontend with SSR on AWS CloudFront",
            "Node.js API Gateway with JWT authentication",
            "PostgreSQL RDS (db.r5.2xlarge) with read replicas",
            "Redis ElastiCache for session management",
            "S3 + CloudFront for static assets",
            "Stripe payment integration (PCI DSS scope)",
            "ML recommendation service on SageMaker endpoint",
        ],
        "expected_load": "50,000 concurrent users, 500 req/sec peak",
        "launch_date": "2025-04-01",
    },
    {
        "id": "DOC-002",
        "title": "Internal HR Portal — Launch Review",
        "description": "Employee self-service portal for benefits enrollment, PTO tracking, and org chart. Internal-only access via VPN.",
        "components": [
            "Angular frontend behind AWS ALB",
            "Python Flask API on ECS Fargate",
            "MySQL RDS (db.t3.medium) single instance",
            "Cognito for SSO with corporate Active Directory",
            "S3 for employee document uploads",
        ],
        "expected_load": "500 concurrent users, 20 req/sec peak",
        "launch_date": "2025-04-15",
    },
]

# ── Pre-analyzed specialist findings (deterministic output) ──
SECURITY_FINDINGS = {
    "DOC-001": {
        "risk_level": "HIGH",
        "findings": [
            "JWT tokens stored in localStorage — vulnerable to XSS attacks. Recommend HttpOnly cookies.",
            "Stripe integration brings PCI DSS scope — ensure all cardholder data flows are encrypted end-to-end.",
            "No WAF configured on CloudFront — exposed to OWASP Top 10 attacks (SQLi, XSS).",
            "Redis ElastiCache lacks encryption at rest — session tokens could be exposed if instance compromised.",
        ],
        "critical_count": 2,
        "recommendation": "Block launch until JWT storage and WAF issues are resolved. PCI DSS audit required.",
    },
    "DOC-002": {
        "risk_level": "LOW",
        "findings": [
            "VPN-only access significantly reduces attack surface.",
            "Cognito SSO with AD integration follows security best practices.",
            "S3 bucket for employee documents should have server-side encryption enabled.",
        ],
        "critical_count": 0,
        "recommendation": "Approve with minor condition: enable S3 server-side encryption before launch.",
    },
}

SCALABILITY_FINDINGS = {
    "DOC-001": {
        "risk_level": "MEDIUM",
        "findings": [
            "db.r5.2xlarge with read replicas can handle 500 req/sec — adequate for launch.",
            "SageMaker endpoint auto-scaling not configured — recommendation service will bottleneck at 200 req/sec.",
            "No CDN cache invalidation strategy — stale product data risk during flash sales.",
            "Redis cluster mode disabled — single node is a SPOF for session management.",
        ],
        "max_throughput": "500 req/sec (bottleneck: SageMaker at 200 req/sec)",
        "recommendation": "Configure SageMaker auto-scaling and Redis cluster mode before launch.",
    },
    "DOC-002": {
        "risk_level": "LOW",
        "findings": [
            "db.t3.medium is sufficient for 500 concurrent users and 20 req/sec.",
            "ECS Fargate auto-scaling will handle load spikes during open enrollment.",
            "No caching layer needed at this scale — direct DB queries are fast enough.",
        ],
        "max_throughput": "200 req/sec (well above 20 req/sec requirement)",
        "recommendation": "Approve — architecture is appropriately sized for internal workload.",
    },
}

COST_FINDINGS = {
    "DOC-001": {
        "monthly_estimate": 12_500,
        "breakdown": {
            "RDS (db.r5.2xlarge + replicas)": 3200,
            "ECS/Fargate (API)": 1800,
            "CloudFront + S3": 800,
            "ElastiCache (Redis)": 1200,
            "SageMaker endpoint": 4000,
            "Stripe fees (~2.9%)": 1500,
        },
        "risk_level": "MEDIUM",
        "findings": [
            "SageMaker endpoint is 32% of total cost — consider Savings Plans or spot instances.",
            "Redis single-node is cheap but cluster mode (recommended for HA) adds ~$600/mo.",
            "CloudFront costs will spike during flash sales — set billing alerts at $1,000.",
        ],
        "recommendation": "Optimize SageMaker with auto-scaling and Savings Plans. Total is reasonable for revenue-generating platform.",
    },
    "DOC-002": {
        "monthly_estimate": 450,
        "breakdown": {
            "RDS (db.t3.medium)": 120,
            "ECS Fargate": 150,
            "ALB": 80,
            "S3": 20,
            "Cognito": 80,
        },
        "risk_level": "LOW",
        "findings": [
            "Total cost is well within internal tooling budget.",
            "Consider Reserved Instances for RDS to save 30% over 1 year.",
        ],
        "recommendation": "Approve — cost is minimal for an internal tool.",
    },
}

# Shared caches — each specialist writes its findings here
security_cache = {}
scalability_cache = {}
cost_cache = {}


# ═══════════════════════════════════════════════════════
#  SPECIALIST 1: SECURITY REVIEWER  (Nova Lite — fast)
# ═══════════════════════════════════════════════════════

def build_security_agent() -> Agent:
    """Build the Security Reviewer agent using Nova Lite."""
    # STEP 1: BedrockModel (Nova Lite for fast security pattern-matching, temperature 0.0)
    model = BedrockModel(model_id=NOVA_LITE_MODEL, region_name=AWS_REGION, temperature=0.0)

    # STEP 2: System prompt — one tool, structured output
    system_prompt = """You are a security reviewer. Your ONLY job:
1. Call review_security with the document_id
2. Report in exactly 3 lines:
   Risk Level: <HIGH|MEDIUM|LOW>
   Critical Issues: <count>
   Recommendation: <one-sentence>
Do NOT add any other commentary."""

    @tool
    def review_security(document_id: str) -> str:
        """Review document security (auth, encryption, exposure, compliance)."""
        doc = next((d for d in DOCUMENTS if d["id"] == document_id), None)
        if not doc:
            return json.dumps({"error": f"Document {document_id} not found"})

        findings = SECURITY_FINDINGS.get(document_id, {})
        result = {
            "document_id": document_id,
            "domain": "security",
            "risk_level": findings.get("risk_level", "UNKNOWN"),
            "findings": findings.get("findings", []),
            "critical_count": findings.get("critical_count", 0),
            "recommendation": findings.get("recommendation", ""),
        }
        security_cache[document_id] = result
        return json.dumps(result, indent=2)

    # STEP 3: Build Agent
    return Agent(model=model, system_prompt=system_prompt, tools=[review_security])


# Specialist 2: Scalability Reviewer (Claude — deep)

def build_scalability_agent() -> Agent:
    """Build the Scalability Reviewer agent using Claude."""
    # STEP 1: BedrockModel (Claude for deep performance reasoning, temperature 0.1)
    model = BedrockModel(model_id=CLAUDE_MODEL, region_name=AWS_REGION, temperature=0.1)

    # STEP 2: System prompt — one tool, structured output
    system_prompt = """You are a scalability reviewer. Your ONLY job:
1. Call review_scalability with the document_id
2. Report in exactly 3 lines:
   Risk Level: <HIGH|MEDIUM|LOW>
   Max Throughput: <estimate>
   Recommendation: <one-sentence>
Do NOT add any other commentary."""

    @tool
    def review_scalability(document_id: str) -> str:
        """Review document scalability (DB capacity, caching, bottlenecks, SPOFs)."""
        doc = next((d for d in DOCUMENTS if d["id"] == document_id), None)
        if not doc:
            return json.dumps({"error": f"Document {document_id} not found"})

        findings = SCALABILITY_FINDINGS.get(document_id, {})
        result = {
            "document_id": document_id,
            "domain": "scalability",
            "risk_level": findings.get("risk_level", "UNKNOWN"),
            "findings": findings.get("findings", []),
            "max_throughput": findings.get("max_throughput", "Unknown"),
            "recommendation": findings.get("recommendation", ""),
        }
        scalability_cache[document_id] = result
        return json.dumps(result, indent=2)

    # STEP 3: Build Agent — bind model + prompt + tool
    return Agent(model=model, system_prompt=system_prompt, tools=[review_scalability])


# Specialist 3: Cost Reviewer (Nova Pro — balanced)

def build_cost_agent() -> Agent:
    """Build the Cost Reviewer agent using Nova Pro."""
    # STEP 1: BedrockModel (Nova Pro for balanced cost analysis, temperature 0.1)
    model = BedrockModel(model_id=NOVA_PRO_MODEL, region_name=AWS_REGION, temperature=0.1)

    # STEP 2: System prompt — one tool, structured output
    system_prompt = """You are a cost reviewer. Your ONLY job:
1. Call review_cost with the document_id
2. Report in exactly 3 lines:
   Monthly Estimate: $<amount>
   Risk Level: <HIGH|MEDIUM|LOW>
   Recommendation: <one-sentence>
Do NOT add any other commentary."""

    @tool
    def review_cost(document_id: str) -> str:
        """Review document costs (compute, storage, data transfer, third-party fees)."""
        doc = next((d for d in DOCUMENTS if d["id"] == document_id), None)
        if not doc:
            return json.dumps({"error": f"Document {document_id} not found"})

        findings = COST_FINDINGS.get(document_id, {})
        result = {
            "document_id": document_id,
            "domain": "cost",
            "monthly_estimate": findings.get("monthly_estimate", 0),
            "breakdown": findings.get("breakdown", {}),
            "risk_level": findings.get("risk_level", "UNKNOWN"),
            "findings": findings.get("findings", []),
            "recommendation": findings.get("recommendation", ""),
        }
        cost_cache[document_id] = result
        return json.dumps(result, indent=2)

    # STEP 3: Build Agent — bind model + prompt + tool
    return Agent(model=model, system_prompt=system_prompt, tools=[review_cost])


# Synthesizer Agent (Claude — combines all reviews into unified assessment)

def build_synthesizer_agent() -> Agent:
    """Build Synthesizer Agent — combines specialist findings (not re-analyzing)."""
    # STEP 1: BedrockModel (Claude for multi-specialist synthesis, temperature 0.2)
    model = BedrockModel(model_id=CLAUDE_MODEL, region_name=AWS_REGION, temperature=0.2)

    # STEP 2: System prompt — synthesize, don't re-analyze
    system_prompt = """You are a launch-readiness synthesizer. Your ONLY job:
1. Call synthesize_reviews with the document_id
2. Report a unified assessment in exactly 5 lines:
   Overall Risk: <HIGH|MEDIUM|LOW>
   Launch Decision: <APPROVE|APPROVE-WITH-CONDITIONS|BLOCK>
   Security: <one-line summary>
   Scalability: <one-line summary>
   Cost: <one-line summary>
Do NOT re-analyze the document. Base your assessment ONLY on the specialist findings."""

    @tool
    def synthesize_reviews(document_id: str) -> str:
        """Combine specialist findings into unified launch-readiness assessment."""
        sec = security_cache.get(document_id, {})
        scale = scalability_cache.get(document_id, {})
        cost = cost_cache.get(document_id, {})

        # Determine overall risk (highest of the three)
        risk_levels = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "UNKNOWN": 0}
        risks = [
            risk_levels.get(sec.get("risk_level", "UNKNOWN"), 0),
            risk_levels.get(scale.get("risk_level", "UNKNOWN"), 0),
            risk_levels.get(cost.get("risk_level", "UNKNOWN"), 0),
        ]
        max_risk = max(risks)
        overall_risk = {3: "HIGH", 2: "MEDIUM", 1: "LOW"}.get(max_risk, "UNKNOWN")

        # Determine launch decision
        critical_issues = sec.get("critical_count", 0)
        if critical_issues >= 2 or max_risk == 3:
            decision = "BLOCK"
        elif critical_issues >= 1 or max_risk == 2:
            decision = "APPROVE-WITH-CONDITIONS"
        else:
            decision = "APPROVE"

        result = {
            "document_id": document_id,
            "overall_risk": overall_risk,
            "launch_decision": decision,
            "security_summary": sec.get("recommendation", "No data"),
            "scalability_summary": scale.get("recommendation", "No data"),
            "cost_summary": cost.get("recommendation", "No data"),
            "total_findings": (
                len(sec.get("findings", []))
                + len(scale.get("findings", []))
                + len(cost.get("findings", []))
            ),
        }
        return json.dumps(result, indent=2)

    # STEP 3: Build Agent
    return Agent(model=model, system_prompt=system_prompt, tools=[synthesize_reviews])


# Parallel execution engine (ThreadPoolExecutor runs specialists independently)

def run_specialists_parallel(doc_id: str) -> dict:
    """Run all 3 specialist agents in PARALLEL (independent reviews)."""
    timings = {}

    def run_security():
        return run_agent_with_retry(
            build_security_agent,
            f"Review security for document {doc_id}",
        )

    def run_scalability():
        return run_agent_with_retry(
            build_scalability_agent,
            f"Review scalability for document {doc_id}",
        )

    def run_cost():
        return run_agent_with_retry(
            build_cost_agent,
            f"Review cost for document {doc_id}",
        )

    # ── PARALLEL: Submit all 3 specialists to thread pool ──
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(run_security): "security",
            executor.submit(run_scalability): "scalability",
            executor.submit(run_cost): "cost",
        }
        for future in as_completed(futures):
            timings[futures[future]] = future.result()
    return timings


def run_specialists_sequential(doc_id: str) -> dict:
    """Run all 3 specialists SEQUENTIALLY for comparison."""
    timings = {}
    timings["security"] = run_agent_with_retry(
        build_security_agent,
        f"Review security for document {doc_id}",
    )
    timings["scalability"] = run_agent_with_retry(
        build_scalability_agent,
        f"Review scalability for document {doc_id}",
    )
    timings["cost"] = run_agent_with_retry(
        build_cost_agent,
        f"Review cost for document {doc_id}",
    )

    return timings


# Main — Analyze documents and compare parallel vs sequential

def main():
    print("=" * 70)
    print("  Parallel Document Analysis — Module 3 Demo")
    print("  3 Specialist Agents (parallel) + 1 Synthesizer Agent")
    print("  ThreadPoolExecutor for concurrent execution")
    print("=" * 70)

    comparison = []

    for doc in DOCUMENTS:
        doc_id = doc["id"]
        print(f"\n{'━' * 70}")
        print(f"  Document: {doc_id} — {doc['title']}")
        print(f"  {doc['description'][:70]}...")
        print(f"  Expected Load: {doc['expected_load']}")
        print(f"{'━' * 70}")

        security_cache.clear()
        scalability_cache.clear()
        cost_cache.clear()

        print(f"\n  >>> Running 3 specialists in PARALLEL...")
        t_parallel_start = time.time()
        parallel_timings = run_specialists_parallel(doc_id)
        t_specialists = time.time() - t_parallel_start
        print(f"  Specialists complete: {t_specialists:.1f}s (parallel)")

        print(f"\n  >>> Synthesizer combining findings...")
        t_synth = run_agent_with_retry(build_synthesizer_agent, f"Synthesize reviews for document {doc_id}")
        t_parallel_total = t_specialists + t_synth

        sec = security_cache.get(doc_id, {})
        scale = scalability_cache.get(doc_id, {})
        cost_data = cost_cache.get(doc_id, {})

        # Display unified launch-readiness report
        print(f"\n  ┌─── Launch-Readiness Assessment ─────────────────┐")
        print(f"  │ Security:    {sec.get('risk_level', '?')} risk — {sec.get('critical_count', '?')} critical issues")
        print(f"  │ Scalability: {scale.get('risk_level', '?')} risk — {scale.get('max_throughput', '?')}")
        print(f"  │ Cost:        ${cost_data.get('monthly_estimate', '?'):,}/mo — {cost_data.get('risk_level', '?')} risk")
        # Determine decision from synthesizer output
        risks = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
        max_risk = max(
            risks.get(sec.get("risk_level", "LOW"), 1),
            risks.get(scale.get("risk_level", "LOW"), 1),
            risks.get(cost_data.get("risk_level", "LOW"), 1),
        )
        critical = sec.get("critical_count", 0)
        if critical >= 2 or max_risk == 3:
            decision = "BLOCK"
        elif critical >= 1 or max_risk == 2:
            decision = "APPROVE-WITH-CONDITIONS"
        else:
            decision = "APPROVE"
        print(f"  │")
        print(f"  │ Decision:    {decision}")
        print(f"  └────────────────────────────────────────────────┘")
        print(f"  Parallel total: {t_parallel_total:.1f}s (specialists: {t_specialists:.1f}s + synthesizer: {t_synth:.1f}s)")

        # ── SEQUENTIAL RUN (for comparison) ───────────────
        security_cache.clear()
        scalability_cache.clear()
        cost_cache.clear()

        print(f"\n  >>> Running 3 specialists SEQUENTIALLY (for comparison)...")
        t_seq_start = time.time()
        sequential_timings = run_specialists_sequential(doc_id)
        t_seq_specialists = time.time() - t_seq_start

        # Re-run synthesizer for fair comparison
        t_synth2 = run_agent_with_retry(
            build_synthesizer_agent,
            f"Synthesize reviews for document {doc_id}",
        )
        t_seq_total = t_seq_specialists + t_synth2
        print(f"  Sequential total: {t_seq_total:.1f}s (specialists: {t_seq_specialists:.1f}s + synthesizer: {t_synth2:.1f}s)")

        if t_parallel_total > 0:
            speedup = t_seq_total / t_parallel_total
            print(f"\n  Speedup: {speedup:.1f}x faster with parallel specialists")

        comparison.append({
            "doc": doc_id,
            "decision": decision,
            "parallel_s": round(t_parallel_total, 1),
            "sequential_s": round(t_seq_total, 1),
            "speedup": round(t_seq_total / t_parallel_total, 1) if t_parallel_total > 0 else 0,
            "specialists_parallel_s": round(t_specialists, 1),
            "specialists_sequential_s": round(t_seq_specialists, 1),
        })

    # ── Performance Comparison ───────────────────────────
    print(f"\n{'═' * 70}")
    print("  PARALLEL vs SEQUENTIAL — PERFORMANCE COMPARISON")
    print(f"{'═' * 70}")
    print(f"  {'Document':<10} {'Decision':<28} {'Parallel':<11} {'Sequential':<13} {'Speedup':<8}")
    print(f"  {'─' * 66}")
    for r in comparison:
        print(f"  {r['doc']:<10} {r['decision']:<28} {r['parallel_s']:<11.1f} {r['sequential_s']:<13.1f} {r['speedup']:.1f}x")

    avg_parallel = sum(r["parallel_s"] for r in comparison) / len(comparison)
    avg_sequential = sum(r["sequential_s"] for r in comparison) / len(comparison)
    avg_speedup = avg_sequential / avg_parallel if avg_parallel > 0 else 0
    print(f"\n  Average: Parallel={avg_parallel:.1f}s | Sequential={avg_sequential:.1f}s | Speedup={avg_speedup:.1f}x")

    print(f"\n  Key Insight: The specialist + synthesizer pattern separates")
    print(f"  ANALYSIS (parallel, independent) from SYNTHESIS (sequential,")
    print(f"  dependent). ThreadPoolExecutor handles the parallel phase;")
    print(f"  the synthesizer runs after all specialists complete because")
    print(f"  it needs their combined findings.\n")


if __name__ == "__main__":
    main()
