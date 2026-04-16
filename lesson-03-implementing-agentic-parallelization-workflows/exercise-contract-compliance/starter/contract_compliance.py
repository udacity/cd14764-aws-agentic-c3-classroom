"""
contract_compliance.py - STARTER
===================================
Module 3 Exercise: Parallel Contract Compliance Analysis

YOUR TASK: Complete 4 build functions (3 TODOs each = 12 TODOs total)

Architecture:
    Legal Contract
         │
    ┌────┴────────────────────────┐
    │           │                 │       ← ThreadPoolExecutor (parallel)
  Regulatory  Financial        IP
  Compliance  Risk           Protection
  Agent       Agent          Agent
(Nova Lite)  (Claude)       (Nova Pro)
    │           │                 │
    └────┬──────┴────────────────┘
         │
    Synthesizer Agent (Claude)       ← Produces compliance report
         │
    Recommendation: APPROVE / APPROVE-WITH-CONDITIONS / REJECT

PATTERN: Follow the same steps shown in the demo (document_analysis.py)
  STEP 1: Create BedrockModel (choose model + temperature)
  STEP 2: Write system prompt (tell agent which tool to call)
  STEP 3: Build Agent (bind model + prompt + tools)
  Then: ThreadPoolExecutor for parallel specialists, Synthesizer after.

What's pre-written for you:
  - All 4 tools (check_regulatory, assess_financial_risk, review_ip_clauses, synthesize_compliance)
  - Sample contract data and pre-analyzed findings
  - Parallel execution engine (ThreadPoolExecutor)
  - Main function with reporting

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


# ─────────────────────────────────────────────────────
# CONFIGURATION — Models for specialist and synthesizer agents
# ─────────────────────────────────────────────────────
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
NOVA_LITE_MODEL = os.environ.get("NOVA_LITE_MODEL", "amazon.nova-lite-v1:0")                    # Regulatory compliance (fast)
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "us.anthropic.claude-sonnet-4-20250514-v1:0")     # Financial risk + Synthesis (deep)
NOVA_PRO_MODEL = os.environ.get("NOVA_PRO_MODEL", "amazon.nova-pro-v1:0")                      # IP protection (balanced)

# ─────────────────────────────────────────────────────
# SAMPLE CONTRACTS (clean vendor agreement + risky outsourcing)
# ─────────────────────────────────────────────────────
CONTRACTS = [
    {
        "id": "CONTRACT-001",
        "title": "Cloud Infrastructure Vendor Agreement — TechCloud Inc.",
        "type": "vendor_agreement",
        "description": "Standard SaaS vendor agreement for cloud hosting services. Well-structured terms, SOC2 certified vendor, US-based data centers.",
        "clauses": [
            "Data processing limited to US-East and US-West regions",
            "SOC2 Type II compliance certification provided annually",
            "99.9% uptime SLA with service credits for violations",
            "Data deletion within 30 days of contract termination",
            "Mutual NDA with standard confidentiality terms",
            "Net-30 payment terms, no auto-renewal without notice",
            "Liability cap at 12 months of fees paid",
            "IP ownership remains with the client for all custom work",
        ],
        "value": 120_000,
        "duration_months": 24,
    },
    {
        "id": "CONTRACT-002",
        "title": "Offshore Development Outsourcing — GlobalDev Solutions",
        "type": "outsourcing",
        "description": "Development outsourcing to offshore team. Contains concerning clauses around data handling, IP ownership, and termination penalties.",
        "clauses": [
            "Data processing in India, Philippines, and 'other locations as needed'",
            "No SOC2 or ISO 27001 certification; 'industry best practices' only",
            "No uptime SLA — 'commercially reasonable efforts' language",
            "Data retention for 5 years after termination (cannot request deletion)",
            "One-way NDA: client's data protected, but vendor's IP broadly defined",
            "Payment: 50% upfront, balance on delivery; auto-renews annually",
            "Unlimited liability for client, vendor liability capped at fees paid in last month",
            "All work product IP jointly owned — vendor retains right to reuse code",
            "Termination penalty: 6 months of remaining contract value",
            "Governing law: vendor's home jurisdiction, not client's",
        ],
        "value": 500_000,
        "duration_months": 36,
    },
]

# ── Pre-analyzed specialist findings (deterministic output) ──
REGULATORY_FINDINGS = {
    "CONTRACT-001": {
        "risk_level": "LOW",
        "frameworks_checked": ["GDPR", "SOX", "HIPAA", "SOC2"],
        "findings": [
            "SOC2 Type II certified — meets data security compliance requirements.",
            "US-only data residency aligns with GDPR adequacy and data sovereignty requirements.",
            "30-day data deletion clause meets GDPR right-to-erasure timeline.",
        ],
        "violations": [],
        "recommendation": "Approve — vendor meets all regulatory compliance requirements.",
    },
    "CONTRACT-002": {
        "risk_level": "HIGH",
        "frameworks_checked": ["GDPR", "SOX", "HIPAA", "SOC2"],
        "findings": [
            "No SOC2/ISO certification — cannot verify data security controls.",
            "'Other locations as needed' violates GDPR data transfer restrictions (no adequacy decision).",
            "5-year data retention with no deletion option violates GDPR Art. 17 (right to erasure).",
            "No data processing agreement (DPA) — required under GDPR Art. 28.",
        ],
        "violations": ["GDPR Art. 17 (Right to Erasure)", "GDPR Art. 28 (Data Processing Agreement)", "GDPR Art. 46 (Data Transfer Safeguards)"],
        "recommendation": "Reject — multiple GDPR violations. Require DPA, data residency restrictions, and deletion rights before reconsidering.",
    },
}

FINANCIAL_FINDINGS = {
    "CONTRACT-001": {
        "risk_level": "LOW",
        "findings": [
            "Net-30 payment terms are standard and favorable.",
            "No auto-renewal trap — requires explicit notice.",
            "Liability cap at 12 months of fees is reasonable and mutual.",
            "Service credits for SLA violations provide financial protection.",
        ],
        "unfavorable_terms": [],
        "recommendation": "Approve — payment terms and liability structure are well-balanced.",
    },
    "CONTRACT-002": {
        "risk_level": "HIGH",
        "findings": [
            "50% upfront payment ($250K) creates massive financial exposure before delivery.",
            "Auto-renewal without opt-out mechanism locks in recurring costs.",
            "Vendor liability capped at last month's fees (~$14K) vs. unlimited client liability — extremely asymmetric.",
            "6-month termination penalty (~$250K) makes exit prohibitively expensive.",
            "Governing law in vendor's jurisdiction increases legal costs for disputes.",
        ],
        "unfavorable_terms": ["50% upfront", "auto-renewal", "asymmetric liability", "termination penalty", "foreign jurisdiction"],
        "recommendation": "Reject — financial terms are heavily skewed toward vendor. Negotiate: reduce upfront to 20%, add opt-out, equalize liability caps, remove termination penalty.",
    },
}

IP_FINDINGS = {
    "CONTRACT-001": {
        "risk_level": "LOW",
        "findings": [
            "Client retains full IP ownership of all custom work — clear and favorable.",
            "Mutual NDA with standard confidentiality protections.",
            "No non-compete clauses restricting client's future vendor choices.",
        ],
        "concerns": [],
        "recommendation": "Approve — IP terms clearly protect client ownership.",
    },
    "CONTRACT-002": {
        "risk_level": "HIGH",
        "findings": [
            "Joint IP ownership is extremely risky — vendor can reuse client's custom code for competitors.",
            "Vendor's 'broadly defined IP' clause could claim ownership of client methodologies discussed during project.",
            "One-way NDA protects vendor but not client's trade secrets adequately.",
            "No work-for-hire provision — code ownership is ambiguous without explicit assignment.",
            "No non-compete: vendor can build identical product for client's competitors using shared codebase.",
        ],
        "concerns": ["joint IP ownership", "broad vendor IP definition", "one-way NDA", "no work-for-hire", "no non-compete"],
        "recommendation": "Reject — IP terms expose client to competitive risk. Require: full IP assignment, mutual NDA, work-for-hire clause, and 2-year non-compete.",
    },
}

# Shared caches — each specialist writes its findings here
regulatory_cache = {}
financial_cache = {}
ip_cache = {}


# ═══════════════════════════════════════════════════════
#  SPECIALIST 1: REGULATORY COMPLIANCE  (Nova Lite — fast)
# ═══════════════════════════════════════════════════════

def build_regulatory_agent() -> Agent:
    """Build the Regulatory Compliance Agent using Nova Lite.

    Follow the same 3 steps shown in the demo (document_analysis.py):
      STEP 1 → TODO 1: Create BedrockModel with Nova Lite
      STEP 2 → TODO 2: Write system prompt
      STEP 3 → TODO 3: Build Agent
    """

    # TODO 1: Create BedrockModel with Nova Lite (same as demo STEP 1)
    # - Use NOVA_LITE_MODEL for fast regulatory checklist verification
    # - Set temperature=0.0 for deterministic compliance assessment
    # model = BedrockModel(...)

    # TODO 2: Write system prompt (same as demo STEP 2)
    # - Tell the agent to call check_regulatory with the contract_id
    # - Request output in exactly 3 lines:
    #   Risk Level: <HIGH|MEDIUM|LOW>
    #   Violations: <count or NONE>
    #   Recommendation: <one-sentence>
    # system_prompt = """..."""

    # ── Tool is pre-written for you ──
    @tool
    def check_regulatory(contract_id: str) -> str:
        """
        Check contract for GDPR, SOX, HIPAA regulatory compliance.

        Examines: data residency, certifications, data processing agreements,
        retention policies, and cross-border transfer safeguards.

        Args:
            contract_id: The contract ID (e.g., "CONTRACT-001")

        Returns:
            JSON with regulatory compliance findings
        """
        contract = next((c for c in CONTRACTS if c["id"] == contract_id), None)
        if not contract:
            return json.dumps({"error": f"Contract {contract_id} not found"})

        findings = REGULATORY_FINDINGS.get(contract_id, {})
        result = {
            "contract_id": contract_id,
            "domain": "regulatory_compliance",
            "risk_level": findings.get("risk_level", "UNKNOWN"),
            "frameworks_checked": findings.get("frameworks_checked", []),
            "findings": findings.get("findings", []),
            "violations": findings.get("violations", []),
            "recommendation": findings.get("recommendation", ""),
        }
        regulatory_cache[contract_id] = result
        return json.dumps(result, indent=2)

    # TODO 3: Build Agent — bind model + prompt + tools (same as demo STEP 3)
    # return Agent(model=model, system_prompt=system_prompt, tools=[check_regulatory])
    pass  # Remove this line when you complete the TODOs


# ═══════════════════════════════════════════════════════
#  SPECIALIST 2: FINANCIAL RISK  (Claude — deep analysis)
# ═══════════════════════════════════════════════════════

def build_financial_agent() -> Agent:
    """Build the Financial Risk Agent using Claude.

    Follow the same 3 steps shown in the demo (document_analysis.py):
      STEP 1 → TODO 4: Create BedrockModel with Claude
      STEP 2 → TODO 5: Write system prompt
      STEP 3 → TODO 6: Build Agent
    """

    # TODO 4: Create BedrockModel with Claude (same as demo STEP 1)
    # - Use CLAUDE_MODEL for deep analysis of complex financial terms
    # - Set temperature=0.1 for analytical precision
    # model = BedrockModel(...)

    # TODO 5: Write system prompt (same as demo STEP 2)
    # - Tell the agent to call assess_financial_risk with the contract_id
    # - Request output in exactly 3 lines:
    #   Risk Level: <HIGH|MEDIUM|LOW>
    #   Unfavorable Terms: <count or NONE>
    #   Recommendation: <one-sentence>
    # system_prompt = """..."""

    # ── Tool is pre-written for you ──
    @tool
    def assess_financial_risk(contract_id: str) -> str:
        """
        Assess financial risk in contract terms.

        Examines: payment terms, liability caps, indemnification,
        penalty structures, and auto-renewal traps.

        Args:
            contract_id: The contract ID (e.g., "CONTRACT-001")

        Returns:
            JSON with financial risk assessment
        """
        contract = next((c for c in CONTRACTS if c["id"] == contract_id), None)
        if not contract:
            return json.dumps({"error": f"Contract {contract_id} not found"})

        findings = FINANCIAL_FINDINGS.get(contract_id, {})
        result = {
            "contract_id": contract_id,
            "domain": "financial_risk",
            "contract_value": contract["value"],
            "risk_level": findings.get("risk_level", "UNKNOWN"),
            "findings": findings.get("findings", []),
            "unfavorable_terms": findings.get("unfavorable_terms", []),
            "recommendation": findings.get("recommendation", ""),
        }
        financial_cache[contract_id] = result
        return json.dumps(result, indent=2)

    # TODO 6: Build Agent — bind model + prompt + tools (same as demo STEP 3)
    # return Agent(model=model, system_prompt=system_prompt, tools=[assess_financial_risk])
    pass  # Remove this line when you complete the TODOs


# ═══════════════════════════════════════════════════════
#  SPECIALIST 3: IP PROTECTION  (Nova Pro — balanced)
# ═══════════════════════════════════════════════════════

def build_ip_agent() -> Agent:
    """Build the IP Protection Agent using Nova Pro.

    Follow the same 3 steps shown in the demo (document_analysis.py):
      STEP 1 → TODO 7: Create BedrockModel with Nova Pro
      STEP 2 → TODO 8: Write system prompt
      STEP 3 → TODO 9: Build Agent
    """

    # TODO 7: Create BedrockModel with Nova Pro (same as demo STEP 1)
    # - Use NOVA_PRO_MODEL for balanced IP clause analysis
    # - Set temperature=0.1 for consistent assessment
    # model = BedrockModel(...)

    # TODO 8: Write system prompt (same as demo STEP 2)
    # - Tell the agent to call review_ip_clauses with the contract_id
    # - Request output in exactly 3 lines:
    #   Risk Level: <HIGH|MEDIUM|LOW>
    #   IP Concerns: <count or NONE>
    #   Recommendation: <one-sentence>
    # system_prompt = """..."""

    # ── Tool is pre-written for you ──
    @tool
    def review_ip_clauses(contract_id: str) -> str:
        """
        Review IP ownership, licensing, and non-compete clauses.

        Examines: IP assignment, work-for-hire provisions, licensing grants,
        NDA reciprocity, and non-compete scope.

        Args:
            contract_id: The contract ID (e.g., "CONTRACT-001")

        Returns:
            JSON with IP protection assessment
        """
        contract = next((c for c in CONTRACTS if c["id"] == contract_id), None)
        if not contract:
            return json.dumps({"error": f"Contract {contract_id} not found"})

        findings = IP_FINDINGS.get(contract_id, {})
        result = {
            "contract_id": contract_id,
            "domain": "ip_protection",
            "risk_level": findings.get("risk_level", "UNKNOWN"),
            "findings": findings.get("findings", []),
            "concerns": findings.get("concerns", []),
            "recommendation": findings.get("recommendation", ""),
        }
        ip_cache[contract_id] = result
        return json.dumps(result, indent=2)

    # TODO 9: Build Agent — bind model + prompt + tools (same as demo STEP 3)
    # return Agent(model=model, system_prompt=system_prompt, tools=[review_ip_clauses])
    pass  # Remove this line when you complete the TODOs


# ═══════════════════════════════════════════════════════
#  SYNTHESIZER AGENT  (Claude — produces compliance report)
#
#  NEW in Module 3: After parallel specialists finish,
#  the Synthesizer combines ALL findings into one report.
#  Same pattern as demo (document_analysis.py).
# ═══════════════════════════════════════════════════════

def build_synthesizer_agent() -> Agent:
    """Build the Synthesizer Agent using Claude.

    Follow the same 3 steps shown in the demo (document_analysis.py):
      STEP 1 → TODO 10: Create BedrockModel with Claude
      STEP 2 → TODO 11: Write system prompt
      STEP 3 → TODO 12: Build Agent
    """

    # TODO 10: Create BedrockModel with Claude (same as demo STEP 1)
    # - Use CLAUDE_MODEL for reasoning across multiple specialist outputs
    # - Set temperature=0.2 for balanced synthesis
    # model = BedrockModel(...)

    # TODO 11: Write system prompt (same as demo STEP 2)
    # - Tell the agent to call synthesize_compliance with the contract_id
    # - Request output in exactly 5 lines:
    #   Overall Risk: <HIGH|MEDIUM|LOW>
    #   Recommendation: <APPROVE|APPROVE-WITH-CONDITIONS|REJECT>
    #   Regulatory: <one-line summary>
    #   Financial: <one-line summary>
    #   IP Protection: <one-line summary>
    # - Tell agent to use ONLY specialist findings, NOT re-analyze the contract
    # system_prompt = """..."""

    # ── Tool is pre-written for you ──
    @tool
    def synthesize_compliance(contract_id: str) -> str:
        """
        Combine findings from all 3 specialists into a compliance recommendation.

        Reads from shared caches populated by the parallel specialist agents.
        Produces: APPROVE, APPROVE-WITH-CONDITIONS, or REJECT.

        Args:
            contract_id: The contract ID (e.g., "CONTRACT-001")

        Returns:
            JSON with unified compliance recommendation
        """
        reg = regulatory_cache.get(contract_id, {})
        fin = financial_cache.get(contract_id, {})
        ip = ip_cache.get(contract_id, {})

        # Determine overall risk (highest of the three)
        risk_levels = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "UNKNOWN": 0}
        risks = [
            risk_levels.get(reg.get("risk_level", "UNKNOWN"), 0),
            risk_levels.get(fin.get("risk_level", "UNKNOWN"), 0),
            risk_levels.get(ip.get("risk_level", "UNKNOWN"), 0),
        ]
        max_risk = max(risks)
        overall_risk = {3: "HIGH", 2: "MEDIUM", 1: "LOW"}.get(max_risk, "UNKNOWN")

        # Determine recommendation
        high_risk_count = sum(1 for r in risks if r == 3)
        if high_risk_count >= 2:
            recommendation = "REJECT"
        elif high_risk_count == 1:
            recommendation = "APPROVE-WITH-CONDITIONS"
        elif max_risk == 2:
            recommendation = "APPROVE-WITH-CONDITIONS"
        else:
            recommendation = "APPROVE"

        result = {
            "contract_id": contract_id,
            "overall_risk": overall_risk,
            "recommendation": recommendation,
            "regulatory_summary": reg.get("recommendation", "No data"),
            "financial_summary": fin.get("recommendation", "No data"),
            "ip_summary": ip.get("recommendation", "No data"),
            "total_findings": (
                len(reg.get("findings", []))
                + len(fin.get("findings", []))
                + len(ip.get("findings", []))
            ),
            "violations": reg.get("violations", []),
            "unfavorable_terms": fin.get("unfavorable_terms", []),
            "ip_concerns": ip.get("concerns", []),
        }
        return json.dumps(result, indent=2)

    # TODO 12: Build Agent — bind model + prompt + tools (same as demo STEP 3)
    # return Agent(model=model, system_prompt=system_prompt, tools=[synthesize_compliance])
    pass  # Remove this line when you complete the TODOs


# ═══════════════════════════════════════════════════════
#  PARALLEL EXECUTION ENGINE (pre-written)
#
#  Same pattern as demo: ThreadPoolExecutor for specialists,
#  then Synthesizer runs sequentially after.
#  Study this code — it shows the parallel + synthesizer flow.
# ═══════════════════════════════════════════════════════

def run_specialists_parallel(contract_id: str) -> dict:
    """Run all 3 specialist agents in PARALLEL using ThreadPoolExecutor."""
    timings = {}

    def run_regulatory():
        agent = build_regulatory_agent()
        t = time.time()
        agent(f"Check regulatory compliance for contract {contract_id}")
        return time.time() - t

    def run_financial():
        agent = build_financial_agent()
        t = time.time()
        agent(f"Assess financial risk for contract {contract_id}")
        return time.time() - t

    def run_ip():
        agent = build_ip_agent()
        t = time.time()
        agent(f"Review IP clauses for contract {contract_id}")
        return time.time() - t

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(run_regulatory): "regulatory",
            executor.submit(run_financial): "financial",
            executor.submit(run_ip): "ip",
        }
        for future in as_completed(futures):
            name = futures[future]
            timings[name] = future.result()

    return timings


def run_specialists_sequential(contract_id: str) -> dict:
    """Run all 3 specialists SEQUENTIALLY for comparison."""
    timings = {}

    agent1 = build_regulatory_agent()
    t = time.time()
    agent1(f"Check regulatory compliance for contract {contract_id}")
    timings["regulatory"] = time.time() - t

    agent2 = build_financial_agent()
    t = time.time()
    agent2(f"Assess financial risk for contract {contract_id}")
    timings["financial"] = time.time() - t

    agent3 = build_ip_agent()
    t = time.time()
    agent3(f"Review IP clauses for contract {contract_id}")
    timings["ip"] = time.time() - t

    return timings


# ═══════════════════════════════════════════════════════
#  MAIN (pre-written)
# ═══════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("  Parallel Contract Compliance — Module 3 Exercise")
    print("  3 Specialist Agents (parallel) + 1 Synthesizer Agent")
    print("  ThreadPoolExecutor for concurrent execution")
    print("=" * 70)

    comparison = []

    for contract in CONTRACTS:
        contract_id = contract["id"]
        print(f"\n{'━' * 70}")
        print(f"  Contract: {contract_id} — {contract['title']}")
        print(f"  Type: {contract['type']} | Value: ${contract['value']:,} | Duration: {contract['duration_months']}mo")
        print(f"  {contract['description'][:65]}...")
        print(f"{'━' * 70}")

        # ── Clear caches ──
        regulatory_cache.clear()
        financial_cache.clear()
        ip_cache.clear()

        # ── PARALLEL SPECIALIST RUN ───────────────────────
        print(f"\n  >>> Running 3 specialists in PARALLEL...")
        t_parallel_start = time.time()
        parallel_timings = run_specialists_parallel(contract_id)
        t_specialists = time.time() - t_parallel_start
        print(f"  Specialists complete: {t_specialists:.1f}s (parallel)")

        # ── SYNTHESIZER RUN ───────────────────────────────
        print(f"\n  >>> Synthesizer producing compliance report...")
        synthesizer = build_synthesizer_agent()
        t_synth_start = time.time()
        synth_result = synthesizer(f"Synthesize compliance review for contract {contract_id}")
        t_synth = time.time() - t_synth_start
        t_parallel_total = t_specialists + t_synth

        # Read results from caches
        reg = regulatory_cache.get(contract_id, {})
        fin = financial_cache.get(contract_id, {})
        ip_data = ip_cache.get(contract_id, {})

        # Determine recommendation
        risk_levels = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
        risks = [
            risk_levels.get(reg.get("risk_level", "LOW"), 1),
            risk_levels.get(fin.get("risk_level", "LOW"), 1),
            risk_levels.get(ip_data.get("risk_level", "LOW"), 1),
        ]
        high_count = sum(1 for r in risks if r == 3)
        if high_count >= 2:
            decision = "REJECT"
        elif high_count == 1:
            decision = "APPROVE-WITH-CONDITIONS"
        elif max(risks) == 2:
            decision = "APPROVE-WITH-CONDITIONS"
        else:
            decision = "APPROVE"

        # Display compliance report
        print(f"\n  ┌─── Compliance Report ──────────────────────────┐")
        print(f"  │ Regulatory: {reg.get('risk_level', '?')} — {len(reg.get('violations', []))} violations found")
        print(f"  │ Financial:  {fin.get('risk_level', '?')} — {len(fin.get('unfavorable_terms', []))} unfavorable terms")
        print(f"  │ IP:         {ip_data.get('risk_level', '?')} — {len(ip_data.get('concerns', []))} concerns")
        print(f"  │")
        print(f"  │ Recommendation: {decision}")
        print(f"  └────────────────────────────────────────────────┘")
        print(f"  Parallel total: {t_parallel_total:.1f}s (specialists: {t_specialists:.1f}s + synthesizer: {t_synth:.1f}s)")

        # ── SEQUENTIAL RUN (for comparison) ───────────────
        regulatory_cache.clear()
        financial_cache.clear()
        ip_cache.clear()

        print(f"\n  >>> Running 3 specialists SEQUENTIALLY (for comparison)...")
        t_seq_start = time.time()
        sequential_timings = run_specialists_sequential(contract_id)
        t_seq_specialists = time.time() - t_seq_start

        synthesizer2 = build_synthesizer_agent()
        t_synth2_start = time.time()
        synthesizer2(f"Synthesize compliance review for contract {contract_id}")
        t_synth2 = time.time() - t_synth2_start
        t_seq_total = t_seq_specialists + t_synth2
        print(f"  Sequential total: {t_seq_total:.1f}s")

        if t_parallel_total > 0:
            speedup = t_seq_total / t_parallel_total
            print(f"\n  Speedup: {speedup:.1f}x faster with parallel specialists")

        comparison.append({
            "contract": contract_id,
            "type": contract["type"],
            "decision": decision,
            "parallel_s": round(t_parallel_total, 1),
            "sequential_s": round(t_seq_total, 1),
            "speedup": round(t_seq_total / t_parallel_total, 1) if t_parallel_total > 0 else 0,
        })

    # ── Performance Comparison ───────────────────────────
    print(f"\n{'═' * 70}")
    print("  PARALLEL vs SEQUENTIAL — PERFORMANCE COMPARISON")
    print(f"{'═' * 70}")
    print(f"  {'Contract':<15} {'Type':<18} {'Decision':<28} {'Par.':<7} {'Seq.':<7} {'Speed':<6}")
    print(f"  {'─' * 75}")
    for r in comparison:
        print(f"  {r['contract']:<15} {r['type']:<18} {r['decision']:<28} {r['parallel_s']:<7.1f} {r['sequential_s']:<7.1f} {r['speedup']:.1f}x")

    print(f"\n  Key Insight: Parallel analysis turns O(N) sequential reviews")
    print(f"  into O(1) concurrent reviews. Regulatory, financial, and IP")
    print(f"  concerns are orthogonal dimensions — they can be reviewed")
    print(f"  independently. The synthesizer then combines findings into")
    print(f"  a single compliance recommendation.\n")


if __name__ == "__main__":
    main()
