"""
incident_response.py - SOLUTION
================================
Module 2 Demo: Multi-Model Incident Response System

Architecture:
    Incident Alert
         │
    ┌────┴────────────────────┐
    │         │               │
  Routing   Analysis     Status
  Agent     Agent        Agent
(Nova Lite) (Claude)   (Nova Pro)
   fast     thorough    balanced

Three agents use THREE DIFFERENT Bedrock models, chosen by task:
  - Nova Lite: Fast classification (~100ms thinking)
  - Claude 3 Sonnet: Deep root cause analysis (~2s thinking)
  - Nova Pro: Balanced status drafting (~500ms thinking)

Python orchestrates the pipeline. Each agent has 1 tool.

Tech Stack:
  - Python 3.11+
  - Strands Agents SDK (Agent class, @tool decorator)
  - Amazon Bedrock (Nova Lite, Claude 3 Sonnet, Nova Pro)
"""

import json
import re
import time
import logging
from strands import Agent, tool
from strands.models import BedrockModel

logging.basicConfig(level=logging.WARNING)


def clean_response(text: str) -> str:
    """Strip <thinking>...</thinking> tags from Nova model outputs."""
    return re.sub(r"<thinking>.*?</thinking>\s*", "", str(text), flags=re.DOTALL).strip()

# ─────────────────────────────────────────────────────
# CONFIGURATION — Three different models
# ─────────────────────────────────────────────────────
AWS_REGION = "us-east-1"
NOVA_LITE_MODEL = "amazon.nova-lite-v1:0"                    # Fast, lightweight
CLAUDE_MODEL = "anthropic.claude-3-sonnet-20240229-v1:0"     # Deep reasoning
NOVA_PRO_MODEL = "amazon.nova-pro-v1:0"                      # Balanced

# ─────────────────────────────────────────────────────
# SAMPLE DATA
# ─────────────────────────────────────────────────────
INCIDENTS = [
    {
        "id": "INC-001",
        "source": "CloudWatch",
        "timestamp": "2025-01-15T03:22:00Z",
        "message": "CRITICAL: CPU utilization at 98% on prod-web-01. Memory at 94%. Response time 12s. 47 5xx errors in last 5 min.",
        "affected_service": "web-frontend",
        "region": "us-east-1",
    },
    {
        "id": "INC-002",
        "source": "CloudWatch",
        "timestamp": "2025-01-15T08:15:00Z",
        "message": "WARNING: Disk usage at 82% on db-replica-03. Growth rate 2GB/day. Estimated full in 9 days.",
        "affected_service": "database",
        "region": "us-east-1",
    },
    {
        "id": "INC-003",
        "source": "CodePipeline",
        "timestamp": "2025-01-15T14:00:00Z",
        "message": "INFO: Deployment v2.4.1 to staging completed. All health checks passed. 0 errors in canary.",
        "affected_service": "deployment",
        "region": "us-east-1",
    },
]

SEVERITY_KEYWORDS = {
    "critical": ["cpu utilization at 9", "5xx errors", "response time", "outage", "down"],
    "warning":  ["disk usage at 8", "growth rate", "estimated full", "degraded", "slow"],
    "info":     ["completed", "health checks passed", "successful", "deployed"],
}

KNOWN_ISSUES = {
    "high_cpu": {
        "probable_cause": "Memory leak or traffic spike causing resource exhaustion",
        "common_causes": ["Memory leak in application", "Runaway process", "DDoS attack", "Unoptimized query"],
        "runbooks": ["Scale horizontally (add 2 instances)", "Restart affected pod", "Enable WAF rate limiting"],
        "estimated_resolution": "15-30 minutes",
    },
    "disk_usage": {
        "probable_cause": "Log accumulation without rotation policy",
        "common_causes": ["Log rotation disabled", "Large temp files", "Database bloat", "Orphaned snapshots"],
        "runbooks": ["Enable log rotation (7-day retention)", "Clean /tmp older than 24h", "Run VACUUM FULL"],
        "estimated_resolution": "1-2 hours",
    },
    "deployment": {
        "probable_cause": "Normal deployment activity — no action needed",
        "common_causes": ["Scheduled release"],
        "runbooks": ["Monitor canary metrics for 30 minutes", "Verify rollback plan ready"],
        "estimated_resolution": "N/A — monitoring only",
    },
}

SERVICE_CATEGORY_MAP = {
    "web-frontend": "high_cpu",
    "database": "disk_usage",
    "deployment": "deployment",
}

STATUS_TEMPLATES = {
    "critical": {"audience": "Engineering + Management + On-call", "tone": "Urgent, concise, action-oriented"},
    "warning":  {"audience": "Engineering team", "tone": "Informative, preventive"},
    "info":     {"audience": "Engineering team", "tone": "Brief, positive"},
}

# KEY PATTERN: Shared cache so Python can read tool outputs across agents.
# Tools store their results here. Main() reads from the cache to pass data
# between agents — avoiding the need to parse LLM natural language output.
classification_cache = {}


# ═══════════════════════════════════════════════════════
#  AGENT 1: ALERT ROUTER  (Nova Lite — fast classification)
# ═══════════════════════════════════════════════════════

def build_routing_agent() -> Agent:
    """Build the Alert Router using Nova Lite for fast severity classification."""

    # STEP 1: Create BedrockModel with Nova Lite
    # - Nova Lite is the fastest/cheapest model — ideal for simple classification
    # - temperature=0.0 for deterministic routing (no creativity needed)
    model = BedrockModel(
        model_id=NOVA_LITE_MODEL,
        region_name=AWS_REGION,
        temperature=0.0,
    )

    # STEP 2: System prompt — keep it minimal for a fast model
    system_prompt = """You are an alert routing agent. Your ONLY job:
1. Call classify_alert with the incident_id provided by the user
2. Report the result in exactly 2 lines:
   Severity: <CRITICAL|WARNING|INFO>
   Service: <affected service name>
Do NOT add any other commentary."""

    @tool
    def classify_alert(incident_id: str) -> str:
        """
        Classify an incident's severity using keyword-based rules.

        Args:
            incident_id: The incident ID (e.g., "INC-001")

        Returns:
            JSON with severity classification and incident summary
        """
        incident = next((i for i in INCIDENTS if i["id"] == incident_id), None)
        if not incident:
            return json.dumps({"error": f"Incident {incident_id} not found"})

        msg_lower = incident["message"].lower()
        severity = "info"
        for level, keywords in SEVERITY_KEYWORDS.items():
            if any(kw in msg_lower for kw in keywords):
                severity = level
                break

        result = {
            "incident_id": incident_id,
            "severity": severity,
            "affected_service": incident["affected_service"],
            "source": incident["source"],
            "summary": incident["message"][:120],
        }
        classification_cache[incident_id] = result
        return json.dumps(result, indent=2)

    # STEP 3: Build Agent — bind model + prompt + tools
    return Agent(model=model, system_prompt=system_prompt, tools=[classify_alert])


# ═══════════════════════════════════════════════════════
#  AGENT 2: ROOT CAUSE ANALYZER  (Claude — deep reasoning)
# ═══════════════════════════════════════════════════════

def build_analysis_agent() -> Agent:
    """Build the Root Cause Analyzer using Claude for deep investigation."""

    # STEP 1: Create BedrockModel with Claude
    # - Claude is the most capable model — ideal for complex reasoning
    # - temperature=0.1 allows slight variation while staying analytical
    model = BedrockModel(
        model_id=CLAUDE_MODEL,
        region_name=AWS_REGION,
        temperature=0.1,
    )

    # STEP 2: System prompt — ask for structured synthesis, not raw data dumps
    system_prompt = """You are a root cause analysis agent. Your job:
1. Call investigate_incident with the incident_id
2. Synthesize findings into exactly 3 lines:
   Root Cause: <most likely cause from the data>
   Action: <top priority runbook step>
   ETA: <estimated resolution time>
Do NOT repeat the raw JSON. Just give the 3-line diagnosis."""

    @tool
    def investigate_incident(incident_id: str) -> str:
        """
        Look up root cause data from the known issues database.

        Args:
            incident_id: The incident ID to investigate

        Returns:
            JSON with incident details, known causes, and recommended runbooks
        """
        incident = next((i for i in INCIDENTS if i["id"] == incident_id), None)
        if not incident:
            return json.dumps({"error": f"Incident {incident_id} not found"})

        category = SERVICE_CATEGORY_MAP.get(incident["affected_service"], "unknown")
        known = KNOWN_ISSUES.get(category, {})

        return json.dumps({
            "incident_id": incident_id,
            "incident_message": incident["message"],
            "category": category,
            "probable_cause": known.get("probable_cause", "Unknown — requires manual investigation"),
            "common_causes": known.get("common_causes", []),
            "runbooks": known.get("runbooks", []),
            "estimated_resolution": known.get("estimated_resolution", "Unknown"),
        }, indent=2)

    # STEP 3: Build Agent
    return Agent(model=model, system_prompt=system_prompt, tools=[investigate_incident])


# ═══════════════════════════════════════════════════════
#  AGENT 3: STATUS DRAFTER  (Nova Pro — balanced communication)
# ═══════════════════════════════════════════════════════

def build_status_agent() -> Agent:
    """Build the Status Drafter using Nova Pro for balanced communication."""

    # STEP 1: Create BedrockModel with Nova Pro
    # - Nova Pro balances speed and quality — good for drafting communications
    # - temperature=0.3 allows some creativity for natural-sounding text
    model = BedrockModel(
        model_id=NOVA_PRO_MODEL,
        region_name=AWS_REGION,
        temperature=0.3,
    )

    # STEP 2: System prompt — enforce a specific output format
    system_prompt = """You are a status communication agent. Your job:
1. Call draft_status_components with the incident_id and severity
2. Write a concise status update (4 lines max):
   [SEVERITY] Incident <ID> — <one-line title>
   Impact: <what is affected>
   Action: <what is being done>
   ETA: <expected resolution time>
Match the tone to the severity. Do NOT exceed 4 lines."""

    @tool
    def draft_status_components(incident_id: str, severity: str) -> str:
        """
        Get template and incident data for drafting a status update.

        Args:
            incident_id: The incident ID
            severity: The severity level ("critical", "warning", "info")

        Returns:
            JSON with incident details and communication template
        """
        incident = next((i for i in INCIDENTS if i["id"] == incident_id), None)
        if not incident:
            return json.dumps({"error": f"Incident {incident_id} not found"})

        template = STATUS_TEMPLATES.get(severity.lower(), STATUS_TEMPLATES["info"])

        return json.dumps({
            "incident_id": incident_id,
            "severity": severity,
            "incident_message": incident["message"],
            "affected_service": incident["affected_service"],
            "timestamp": incident["timestamp"],
            "audience": template["audience"],
            "tone": template["tone"],
        }, indent=2)

    # STEP 3: Build Agent
    return Agent(model=model, system_prompt=system_prompt, tools=[draft_status_components])


# ═══════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("  Multi-Model Incident Response — Module 2 Demo")
    print("  Nova Lite (fast) + Claude (deep) + Nova Pro (balanced)")
    print("=" * 60)

    latency_report = []

    for incident in INCIDENTS:
        inc_id = incident["id"]
        print(f"\n{'━' * 60}")
        print(f"  Processing: {inc_id}")
        print(f"  Alert: {incident['message'][:80]}...")
        print(f"{'━' * 60}")

        # ── Step 1: Route with Nova Lite (fast) ─────────────────
        print(f"\n  [Agent 1] Alert Router (Nova Lite)")
        routing_agent = build_routing_agent()
        t1 = time.time()
        routing_result = routing_agent(f"Classify incident {inc_id}")
        routing_time = time.time() - t1
        severity = classification_cache.get(inc_id, {}).get("severity", "info")
        print(f"  Result: {clean_response(routing_result)}")
        print(f"  Latency: {routing_time:.1f}s")

        # ── Step 2: Analyze with Claude (deep) ──────────────────
        print(f"\n  [Agent 2] Root Cause Analyzer (Claude)")
        analysis_agent = build_analysis_agent()
        t2 = time.time()
        analysis_result = analysis_agent(f"Investigate incident {inc_id}")
        analysis_time = time.time() - t2
        print(f"  Result: {clean_response(analysis_result)}")
        print(f"  Latency: {analysis_time:.1f}s")

        # ── Step 3: Draft status with Nova Pro (balanced) ───────
        print(f"\n  [Agent 3] Status Drafter (Nova Pro)")
        status_agent = build_status_agent()
        t3 = time.time()
        status_result = status_agent(
            f"Draft a status update for incident {inc_id}. The severity is {severity}."
        )
        status_time = time.time() - t3
        print(f"  Result: {clean_response(status_result)}")
        print(f"  Latency: {status_time:.1f}s")

        total = routing_time + analysis_time + status_time
        latency_report.append({
            "incident": inc_id,
            "severity": severity,
            "nova_lite_s": round(routing_time, 1),
            "claude_s": round(analysis_time, 1),
            "nova_pro_s": round(status_time, 1),
            "total_s": round(total, 1),
        })

    # ── Latency Comparison Table ────────────────────────────
    print(f"\n{'═' * 60}")
    print("  LATENCY COMPARISON TABLE")
    print(f"{'═' * 60}")
    header = f"  {'Incident':<10} {'Severity':<10} {'Nova Lite':<11} {'Claude':<10} {'Nova Pro':<10} {'Total':<8}"
    print(header)
    print(f"  {'─' * 56}")
    for r in latency_report:
        print(f"  {r['incident']:<10} {r['severity']:<10} {r['nova_lite_s']:<11.1f} {r['claude_s']:<10.1f} {r['nova_pro_s']:<10.1f} {r['total_s']:<8.1f}")

    print(f"\n  Key Insight: Nova Lite handles fast routing, Claude provides")
    print(f"  deep analysis, Nova Pro balances speed and quality for comms.")
    print(f"  Choose the right model for each agent's task requirements.\n")


if __name__ == "__main__":
    main()
