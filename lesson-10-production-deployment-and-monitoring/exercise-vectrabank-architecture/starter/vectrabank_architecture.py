"""
vectrabank_architecture.py - EXERCISE STARTER (Student-Led)
==============================================================
Module 10 Exercise: Plan a Production Deployment Architecture for VectraBank

Create a deployment architecture plan for VectraBank's financial services
multi-agent system. Define runtime configuration, monitoring strategy,
cost estimates, and operational runbooks.

Same planning pattern as the demo (deployment_walkthrough.py),
with additions:
  1. FINANCIAL DOMAIN — VectraBank-specific agents and KBs
  2. OPERATIONAL RUNBOOK (NEW) — deploy, rollback, kill switch, latency
  3. COMPLIANCE REQUIREMENTS — VPC network mode, stricter thresholds
  4. COST OPTIMIZATION — model selection recommendations

Instructions:
  - Follow the demo pattern (deployment_walkthrough.py)
  - Look for TODO 1-8 below
  - Define configs as Python dicts (no AWS calls needed)
  - Focus on WHAT to configure and WHY
"""

import json
import os
from dotenv import load_dotenv

load_dotenv()


# ═══════════════════════════════════════════════════════
#  VECTRABANK RUNTIME CONFIGURATION
# ═══════════════════════════════════════════════════════

# TODO 1: Define the AgentCore Runtime configuration
# Hint: Same structure as demo, but:
#   - networkMode: "VPC" (financial services = internal only)
#   - Add vpcConfiguration with vpcId, subnetIds, securityGroupIds
#   - Guardrail: "gr-vectrabank-compliance" version "1"
#   - Environment variables: 3 KB IDs, state table, audit table, region, log level
VECTRABANK_RUNTIME_CONFIG = {
    "agentRuntimeName": "vectrabank-financial-services",
    # Replace with full config...
}


# ═══════════════════════════════════════════════════════
#  AGENT DEFINITIONS
# ═══════════════════════════════════════════════════════

# TODO 2: Define 4 agents for VectraBank
# Hint: QueryRouter (Nova Lite), MarketDataRetriever (Nova Lite),
#       ComplianceRetriever (Nova Lite), FinancialAdvisor (Claude Sonnet)
#   Each needs: name, model, temperature, role, tools, estimated_tokens, requests_per_day
VECTRABANK_AGENTS = [
    # Replace with 4 agent definitions...
]


# ═══════════════════════════════════════════════════════
#  MONITORING STRATEGY
# ═══════════════════════════════════════════════════════

# TODO 3: Define the monitoring dashboard (6 widgets)
# Hint: Total Queries, Latency P50/P99, Error Rate (2% threshold),
#       Guardrail Blocks, RAG Quality (NEW), Kill Switch Status (NEW)

# TODO 4: Define 3 alarms with thresholds
# Hint: HighErrorRate (2%), HighLatencyP99 (8s), GuardrailViolationSpike (50 blocks/5min)

# TODO 5: Define X-Ray tracing config
# Hint: 10% sampling for financial audit, annotations for query_type, agent_name, etc.
VECTRABANK_MONITORING = {
    "dashboard_name": "vectrabank-financial-services",
    "widgets": [],   # Replace with 6 widget definitions
    "alarms": [],    # Replace with 3 alarm definitions
    "xray_tracing": {},  # Replace with tracing config
}


# ═══════════════════════════════════════════════════════
#  COST ESTIMATION (provided — same as demo)
# ═══════════════════════════════════════════════════════

MODEL_PRICING = {
    "amazon.nova-lite-v1:0": {"input": 0.00006, "output": 0.00024},
    "amazon.nova-pro-v1:0": {"input": 0.0008, "output": 0.0032},
    "anthropic.claude-3-sonnet-20240229-v1:0": {"input": 0.003, "output": 0.015},
}


def estimate_monthly_costs(agents: list, days: int = 30) -> dict:
    """Estimate monthly costs for VectraBank."""
    costs = {}
    total = 0

    for agent in agents:
        model = agent["model"]
        pricing = MODEL_PRICING.get(model, {"input": 0.001, "output": 0.005})
        tokens = agent["estimated_tokens_per_request"]
        daily_requests = agent["requests_per_day"]

        input_tokens = tokens * 0.6
        output_tokens = tokens * 0.4
        daily_cost = ((input_tokens / 1000) * pricing["input"] +
                      (output_tokens / 1000) * pricing["output"]) * daily_requests
        monthly_cost = daily_cost * days

        costs[agent["name"]] = {
            "model": model, "daily_requests": daily_requests,
            "monthly_cost": round(monthly_cost, 2),
        }
        total += monthly_cost

    # TODO 6: Add infrastructure costs
    # Hint: DynamoDB (2 tables), Knowledge Bases (3 KBs), CloudWatch + X-Ray, VPC
    # Add each as costs["name"] = {"monthly_cost": estimated_cost}
    infrastructure_costs = {
        "dynamodb": {
            "table_state": 0.0,  # TODO 6a: State table (transactions, reads/writes)
            "table_audit": 0.0,  # TODO 6b: Audit log table (compliance requirement)
        },
        "knowledge_bases": {
            "market_data_kb": 0.0,  # TODO 6c: Market data retrieval KB
            "compliance_kb": 0.0,   # TODO 6d: Compliance & regulatory KB
            "risk_assessment_kb": 0.0,  # TODO 6e: Risk assessment KB
        },
        "cloudwatch": {
            "logs": 0.0,  # TODO 6f: CloudWatch Logs ingestion/storage
            "metrics": 0.0,  # TODO 6g: Custom metrics
            "dashboard": 0.0,  # TODO 6h: Dashboard
        },
        "xray": {
            "sampling_and_analysis": 0.0,  # TODO 6i: 10% sampling rate
        },
        "vpc": {
            "nat_gateway": 0.0,  # TODO 6j: VPC NAT gateway (outbound traffic)
            "vpc_endpoints": 0.0,  # TODO 6k: VPC endpoints for Bedrock, S3
        },
    }

    # TODO 6l: Calculate total infrastructure costs and add to costs dict
    # Example: costs["DynamoDB"] = {"monthly_cost": sum of dynamodb costs}
    #         costs["Knowledge Bases"] = {"monthly_cost": sum of KB costs}
    #         etc.

    costs["TOTAL"] = {"monthly_cost": round(total, 2)}
    return costs


# ═══════════════════════════════════════════════════════
#  OPERATIONAL RUNBOOK (NEW — not in demo)
# ═══════════════════════════════════════════════════════

# TODO 7: Define 4 operational runbook procedures
# Hint: Each is a dict with "name", "steps" (list of strings), and procedure-specific fields
#   1. Deploy a New Version — test, update guardrail, deploy runtime, smoke test, monitor
#   2. Rollback — identify previous version, update runtime, verify, post-mortem
#   3. Kill Switch Triggered — acknowledge, check audit log, investigate, fix, re-enable
#   4. Latency Investigation — X-Ray map, per-agent latency, identify bottleneck, scale
OPERATIONAL_RUNBOOK = {
    "deploy": {
        "name": "Production Deployment",
        "steps": [
            # TODO 7a: Add step 1 (run test suite)
            # TODO 7b: Add step 2 (validate guardrail configuration)
            # TODO 7c: Add step 3 (deploy new runtime version)
            # TODO 7d: Add step 4 (run smoke tests on 10 test transactions)
            # TODO 7e: Add step 5 (monitor error rate and latency for 5 minutes)
        ],
        "rollback_trigger": "",  # TODO 7f: Under what condition do we rollback? (e.g., "Error rate > 2%")
        "estimated_duration_minutes": 15,  # Estimate time to complete
    },

    "rollback": {
        "name": "Emergency Rollback",
        "steps": [
            # TODO 7g: Add step 1 (identify previous stable runtime version)
            # TODO 7h: Add step 2 (revert runtime to previous version)
            # TODO 7i: Add step 3 (verify agents are responding to transactions)
            # TODO 7j: Add step 4 (post-incident review - what went wrong?)
        ],
        "estimated_duration_minutes": 10,
    },

    "kill_switch": {
        "name": "Kill Switch Activation",
        "steps": [
            # TODO 7k: Add step 1 (acknowledge alert in PagerDuty)
            # TODO 7l: Add step 2 (check AWS X-Ray for error patterns)
            # TODO 7m: Add step 3 (check CloudWatch audit logs for anomalies)
            # TODO 7n: Add step 4 (disable runtime if attack/fraud detected)
            # TODO 7o: Add step 5 (notify compliance team)
        ],
        "threshold": "",  # TODO 7p: What metric threshold triggers this? (e.g., "Guardrail blocks > 50/5min")
        "requires_approval": True,  # Financial system requires human approval
        "estimated_duration_minutes": 5,
    },

    "latency_investigation": {
        "name": "High Latency Investigation",
        "steps": [
            # TODO 7q: Add step 1 (pull X-Ray service map to identify slow service)
            # TODO 7r: Add step 2 (check per-agent latency in CloudWatch)
            # TODO 7s: Add step 3 (identify bottleneck - agent, KB, or knowledge base retrieval?)
            # TODO 7t: Add step 4 (check DynamoDB throttling or KB latency)
            # TODO 7u: Add step 5 (scale the bottleneck component - more provisioned capacity?)
        ],
        "trigger_threshold": "P99 latency > 8 seconds",
        "estimated_duration_minutes": 20,
    },
}


# ═══════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("  VectraBank Deployment Architecture — Module 10 Exercise")
    print("  Runtime Config + Monitoring + Cost + Operational Runbook")
    print("=" * 70)

    # ── Runtime Configuration ──
    print(f"\n{'━' * 70}")
    print("  1. AgentCore Runtime Configuration")
    print(f"{'━' * 70}")

    # TODO 8: Print the runtime config, agent definitions, monitoring strategy,
    #         cost estimates, and operational runbook
    # Hint: Follow the demo's main() output format
    print("  [Complete TODOs 1-7 to populate this output]")

    if VECTRABANK_AGENTS:
        # ── Cost Estimation ──
        print(f"\n{'━' * 70}")
        print("  4. Monthly Cost Estimation (10,000 requests/day)")
        print(f"{'━' * 70}")
        costs = estimate_monthly_costs(VECTRABANK_AGENTS)
        print(f"\n  {'Component':<25s} {'Model':<40s} {'Monthly':>10s}")
        print(f"  {'─' * 75}")
        for name, data in costs.items():
            if name == "TOTAL":
                print(f"  {'─' * 75}")
            model = data.get("model", "—")
            cost = data["monthly_cost"]
            print(f"  {name:<25s} {model:<40s} ${cost:>9.2f}")

    print(f"\n  Key Takeaways:")
    print(f"  1. VPC NETWORK MODE — financial services agents stay internal")
    print(f"  2. MULTI-MODEL COST OPTIMIZATION — Lite for routing/retrieval, Sonnet for synthesis")
    print(f"  3. STRICTER THRESHOLDS — 2% error rate for financial compliance")
    print(f"  4. OPERATIONAL RUNBOOK — deploy, rollback, kill switch, latency procedures (NEW)")
    print(f"  5. AUDIT TRAIL — X-Ray at 10% sampling + full guardrail audit log\n")


if __name__ == "__main__":
    main()
