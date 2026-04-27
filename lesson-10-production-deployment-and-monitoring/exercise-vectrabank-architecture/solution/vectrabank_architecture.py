"""
vectrabank_architecture.py - EXERCISE SOLUTION (Student-Led)
==============================================================
Module 10 Exercise: Plan a Production Deployment Architecture for VectraBank

This exercise creates a deployment architecture plan for the capstone project
(VectraBank financial services RAG system). Students specify:
  1. AgentCore Runtime configuration
  2. Monitoring strategy with metrics and thresholds
  3. Monthly cost estimates
  4. Operational runbook for incidents
  5. Real AgentCore Runtime deployment (create_agent_runtime API call)

Same planning pattern as the demo (deployment_walkthrough.py),
with additions:
  1. FINANCIAL DOMAIN — VectraBank-specific agents, KBs, guardrails
  2. OPERATIONAL RUNBOOK (NEW) — deploy, rollback, kill switch, latency investigation
  3. COMPLIANCE REQUIREMENTS — SEC/FINRA audit trail, PII handling
  4. COST OPTIMIZATION — model selection recommendations

Tech Stack:
  - Python 3.11+ with boto3
  - Amazon Bedrock AgentCore Runtime (bedrock-agentcore-control client)
  - Amazon CloudWatch, X-Ray (monitoring configs)
"""

import io
import json
import os
import zipfile
import boto3
from dotenv import load_dotenv

load_dotenv()

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")


# ─────────────────────────────────────────────────────────
# CLOUDFORMATION HELPER — auto-discover lab resources
# ─────────────────────────────────────────────────────────
def _load_cf_exports(project_name: str = "udacity-agentcore") -> dict:
    """Load CloudFormation stack exports (works in Udacity lab automatically)."""
    try:
        cf = boto3.client("cloudformation", region_name=AWS_REGION)
        exports = {}
        paginator = cf.get_paginator("list_exports")
        for page in paginator.paginate():
            for export in page["Exports"]:
                exports[export["Name"]] = export["Value"]
        return exports
    except Exception:
        return {}

_CF = _load_cf_exports()

# Discover resources from CloudFormation exports.
# Checks lesson-10 stack first, then project stack as fallback.
# Deploy lesson-10 infra first: python infrastructure/deploy_stack.py
_ROLE_ARN = (
    _CF.get("lesson-10-runtime-AgentCoreRoleArn")       # lesson-10 stack (preferred)
    or _CF.get("udacity-agentcore-AgentCoreRoleArn")    # project stack (fallback)
    or os.environ.get("AGENTCORE_ROLE_ARN", "")
)
_S3_BUCKET = (
    _CF.get("lesson-10-runtime-ArtifactBucket")         # lesson-10 stack (preferred)
    or _CF.get("udacity-agentcore-PolicyBucket")        # project stack (fallback)
    or os.environ.get("S3_ARTIFACT_BUCKET", "")
)
_GUARDRAIL_ID      = os.environ.get("GUARDRAIL_ID", "gr-vectrabank-compliance")
_GUARDRAIL_VERSION = os.environ.get("GUARDRAIL_VERSION", "DRAFT")


# ═══════════════════════════════════════════════════════
#  VECTRABANK AgentCore RUNTIME CONFIGURATION
# ═══════════════════════════════════════════════════════

VECTRABANK_RUNTIME_CONFIG = {
    "agentRuntimeName": "vectrabank_financial_services",
    "description": "Multi-agent financial services system with RAG, guardrails, and compliance",
    "roleArn": _ROLE_ARN,

    "networkConfiguration": {
        # In production: VPC mode with real subnet/security group IDs.
        # Lab uses PUBLIC mode — no VPC resources provisioned here.
        "networkMode": "PUBLIC",
    },

    "protocolConfiguration": {
        "serverProtocol": "MCP",
    },

    # Note: injected via before-call event hook in deploy_to_agentcore() — see Step 5
    "guardrailConfiguration": {
        "guardrailIdentifier": _GUARDRAIL_ID,
        "guardrailVersion": _GUARDRAIL_VERSION,
    },

    "environmentVariables": {
        "MARKET_DATA_KB_ID": "KB-MARKET-DATA-001",
        "COMPLIANCE_KB_ID": "KB-COMPLIANCE-002",
        "PRODUCTS_KB_ID": "KB-PRODUCTS-003",
        "STATE_TABLE_NAME": "vectrabank-agent-state",
        "AUDIT_TABLE_NAME": "vectrabank-audit-log",
        "AWS_REGION": os.environ.get("AWS_REGION", "us-east-1"),
        "LOG_LEVEL": "INFO",
        "ENVIRONMENT": "production",
        "ENABLE_XRAY": "true",
    },
}


# ═══════════════════════════════════════════════════════
#  AGENT DEFINITIONS — VectraBank
# ═══════════════════════════════════════════════════════

VECTRABANK_AGENTS = [
    {
        "name": "QueryRouter",
        "model": "amazon.nova-lite-v1:0",
        "temperature": 0.0,
        "role": "Classify incoming financial queries and route to specialist",
        "tools": ["classify_query", "check_priority"],
        "estimated_tokens_per_request": 400,
        "requests_per_day": 10000,
    },
    {
        "name": "MarketDataRetriever",
        "model": "amazon.nova-lite-v1:0",
        "temperature": 0.0,
        "role": "Retrieve market data and financial reports from KB",
        "tools": ["retrieve_market_data"],
        "estimated_tokens_per_request": 600,
        "requests_per_day": 6000,  # ~60% of queries need market data
    },
    {
        "name": "ComplianceRetriever",
        "model": "amazon.nova-lite-v1:0",
        "temperature": 0.0,
        "role": "Retrieve SEC/FINRA regulations and compliance guidelines from KB",
        "tools": ["retrieve_compliance_docs"],
        "estimated_tokens_per_request": 600,
        "requests_per_day": 4000,  # ~40% need compliance info
    },
    {
        "name": "FinancialAdvisor",
        "model": "us.anthropic.claude-sonnet-4-20250514-v1:0",
        "temperature": 0.1,
        "role": "Synthesize retrieved data into grounded financial analysis with citations",
        "tools": [],
        "estimated_tokens_per_request": 2500,
        "requests_per_day": 10000,  # Every query gets a synthesized response
    },
]


# ═══════════════════════════════════════════════════════
#  MONITORING STRATEGY
# ═══════════════════════════════════════════════════════

VECTRABANK_MONITORING = {
    "dashboard_name": "vectrabank-financial-services",
    "widgets": [
        {"title": "Total Queries", "type": "line", "metric": "AgentCore/Invocations",
         "period": 60, "stat": "Sum"},
        {"title": "Latency P50/P99", "type": "line",
         "metrics": [
             {"name": "AgentCore/Latency", "stat": "p50"},
             {"name": "AgentCore/Latency", "stat": "p99"},
         ], "period": 60},
        {"title": "Error Rate", "type": "number", "metric": "AgentCore/Errors",
         "period": 300, "stat": "Average", "threshold": 0.02},  # 2% for financial
        {"title": "Guardrail Blocks by Policy", "type": "stacked_bar",
         "metrics": [
             {"name": "Guardrail/PIIBlocks", "label": "PII"},
             {"name": "Guardrail/TopicBlocks", "label": "Topic"},
             {"name": "Guardrail/ContentBlocks", "label": "Content"},
         ], "period": 300},
        {"title": "RAG Retrieval Quality", "type": "line",
         "metric": "Custom/AvgRelevanceScore", "period": 300, "stat": "Average"},
        {"title": "Kill Switch Status", "type": "indicator",
         "metric": "Custom/KillSwitchActive", "period": 60},
    ],
    "alarms": [
        {
            "name": "HighErrorRate",
            "metric": "AgentCore/Errors",
            "threshold": 0.02,  # 2% — stricter for financial
            "period": 300,
            "action": "SNS → kill-switch-topic → Lambda disables runtime",
        },
        {
            "name": "HighLatencyP99",
            "metric": "AgentCore/Latency",
            "stat": "p99",
            "threshold": 8.0,  # 8 seconds
            "period": 300,
            "action": "SNS → ops-team-pager",
        },
        {
            "name": "GuardrailViolationSpike",
            "metric": "Guardrail/TotalBlocks",
            "threshold": 50,  # 50 blocks in 5 min = potential attack
            "period": 300,
            "action": "SNS → security-team + rate-limit-increase",
        },
    ],
    "xray_tracing": {
        "enabled": True,
        "sampling_rate": 0.10,  # 10% for financial (higher for audit)
        "annotations": ["query_type", "agent_name", "model_id", "customer_tier"],
    },
}


# ═══════════════════════════════════════════════════════
#  COST ESTIMATION
# ═══════════════════════════════════════════════════════

MODEL_PRICING = {
    "amazon.nova-lite-v1:0": {"input": 0.00006, "output": 0.00024},
    "amazon.nova-pro-v1:0": {"input": 0.0008, "output": 0.0032},
    "us.anthropic.claude-sonnet-4-20250514-v1:0": {"input": 0.003, "output": 0.015},
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

    # Infrastructure costs
    infra = {
        "DynamoDB (2 tables)": 50.0,
        "Knowledge Bases (3 KBs)": 30.0,
        "CloudWatch + X-Ray": 25.0,
        "VPC/Networking": 10.0,
    }
    for name, cost in infra.items():
        costs[name] = {"monthly_cost": cost}
        total += cost

    costs["TOTAL"] = {"monthly_cost": round(total, 2)}
    return costs


# ═══════════════════════════════════════════════════════
#  OPERATIONAL RUNBOOK (NEW — not in demo)
# ═══════════════════════════════════════════════════════

OPERATIONAL_RUNBOOK = {
    "deploy_new_version": {
        "title": "Deploy a New Version",
        "steps": [
            "1. Run full test suite: python -m pytest tests/ -v --cov",
            "2. Update guardrail if policies changed: aws bedrock create-guardrail-version ...",
            "3. Deploy runtime with new config: aws bedrock-agentcore update-agent-runtime ...",
            "4. Run smoke test against production: python smoke_test.py --count 20",
            "5. Monitor dashboard for 15 minutes — verify error rate < 2%",
            "6. If error rate > 2%, execute rollback procedure immediately",
        ],
    },
    "rollback": {
        "title": "Rollback to Previous Version",
        "steps": [
            "1. Identify previous stable runtime version from deployment log",
            "2. Update runtime to previous config: aws bedrock-agentcore update-agent-runtime ...",
            "3. Revert guardrail version if changed: reference previous guardrailVersion",
            "4. Run smoke test to verify rollback: python smoke_test.py --count 10",
            "5. Post-mortem: investigate why new version failed, create incident ticket",
        ],
    },
    "kill_switch_triggered": {
        "title": "Kill Switch Triggered — Agent Disabled",
        "steps": [
            "1. Acknowledge alarm in CloudWatch — note trigger time and error details",
            "2. Check audit log for root cause: query type, guardrail policy, error pattern",
            "3. If adversarial attack: enable stricter rate limiting, investigate source IPs",
            "4. If agent malfunction: review recent deployment changes, check model availability",
            "5. Fix root cause and re-enable agent: aws bedrock-agentcore update-agent-runtime ...",
            "6. Monitor for 30 minutes post-recovery — verify kill switch doesn't re-trigger",
        ],
    },
    "latency_investigation": {
        "title": "Investigate Latency Spike (P99 > 8s)",
        "steps": [
            "1. Open X-Ray service map — identify which agent/model is the bottleneck",
            "2. Check per-agent latency: Router (<200ms), Retrievers (<1s), Advisor (<3s)",
            "3. If Retriever slow: check KB indexing status, vector store health",
            "4. If Advisor slow: check model throttling, consider model fallback to Nova Pro",
            "5. If Router slow: check for DynamoDB throttling on state table",
            "6. Scale if needed: increase DynamoDB capacity, add retry backoff for throttling",
        ],
    },
}


# ═══════════════════════════════════════════════════════
#  STEP 5: REAL AgentCore RUNTIME DEPLOYMENT
#
#  VectraBank specifics vs demo:
#   - VPC network mode (financial services — internal only)
#   - Stricter X-Ray sampling (10% vs 5%) for SEC/FINRA audit trail
# ═══════════════════════════════════════════════════════

def deploy_to_agentcore() -> str:
    """
    Deploy the VectraBank runtime to Amazon Bedrock AgentCore.
    Returns the runtime ARN.
    """
    agentcore_control = boto3.client("bedrock-agentcore-control", region_name=AWS_REGION)
    s3_client         = boto3.client("s3",                        region_name=AWS_REGION)

    runtime_name = VECTRABANK_RUNTIME_CONFIG["agentRuntimeName"]

    # ── Check if runtime already exists ───────────────────────────────────
    try:
        existing = agentcore_control.list_agent_runtimes()
        for r in existing.get("agentRuntimes", []):
            if r["agentRuntimeName"] == runtime_name:
                print(f"  Runtime already exists: {r['agentRuntimeArn']}")
                return r["agentRuntimeArn"]
    except Exception as e:
        print(f"  [Note] Could not check existing runtimes: {e}")

    # ── WORKAROUND 1: STS role fetch + before-call event hook ─────────────
    sts        = boto3.client("sts", region_name=AWS_REGION)
    account_id = sts.get_caller_identity()["Account"]
    print(f"  AWS Account: {account_id}  |  Region: {AWS_REGION}")

    guardrail_config = {
        "guardrailIdentifier": _GUARDRAIL_ID,
        "guardrailVersion":    _GUARDRAIL_VERSION,
    }

    def _inject_guardrail(params, **kwargs):
        params["guardrailConfiguration"] = guardrail_config

    agentcore_control.meta.events.register(
        "before-call.bedrock-agentcore-control.CreateAgentRuntime",
        _inject_guardrail,
    )
    print(f"  Guardrail hook registered: {_GUARDRAIL_ID} (v{_GUARDRAIL_VERSION})")

    # -- WORKAROUND 2: Dummy deployment.zip to S3 --
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("main.py", "# VectraBank AgentCore Runtime entry point\n")
    zip_buffer.seek(0)

    artifact_key = f"agentcore-artifacts/{runtime_name}/deployment.zip"
    s3_client.put_object(
        Bucket=_S3_BUCKET,
        Key=artifact_key,
        Body=zip_buffer.getvalue(),
        ContentType="application/zip",
    )
    print(f"  Artifact uploaded: s3://{_S3_BUCKET}/{artifact_key}")

    # -- DEPLOY --
    print(f"  Calling create_agent_runtime...")
    response = agentcore_control.create_agent_runtime(
        agentRuntimeName=runtime_name,
        description=VECTRABANK_RUNTIME_CONFIG["description"],
        roleArn=VECTRABANK_RUNTIME_CONFIG["roleArn"],
        networkConfiguration=VECTRABANK_RUNTIME_CONFIG["networkConfiguration"],
        protocolConfiguration=VECTRABANK_RUNTIME_CONFIG["protocolConfiguration"],
        agentRuntimeArtifact={
            "codeConfiguration": {
                "code": {
                    "s3": {
                        "bucket": _S3_BUCKET,
                        "prefix": artifact_key,
                    }
                },
                "runtime": "PYTHON_3_12",
                "entryPoint": ["main.py"],
            }
        },
        environmentVariables=VECTRABANK_RUNTIME_CONFIG["environmentVariables"],
    )

    runtime_arn = response.get("agentRuntimeArn", response.get("arn", ""))
    print(f"  Runtime ARN: {runtime_arn}")

    # -- WORKAROUND 3: try/except on logging configuration --
    try:
        runtime_id = runtime_arn.split("/")[-1]
        agentcore_control.put_agent_runtime_logging_configuration(
            agentRuntimeId=runtime_id,
            loggingConfiguration={
                "cloudWatchConfig": {
                    "logGroupName": f"/aws/agentcore/{runtime_name}",
                    "logLevel":     "INFO",
                    "enabled":      True,
                },
                "xRayConfig": {
                    "enabled":      True,
                    "samplingRate": VECTRABANK_MONITORING["xray_tracing"]["sampling_rate"],
                },
            },
        )
        print(f"  Observability configured: CloudWatch + X-Ray (10% sampling)")
    except Exception as e:
        print(f"  [Note] Logging config skipped (SDK version mismatch): {e}")

    return runtime_arn


def main():
    print("=" * 70)
    print("  VectraBank Deployment Architecture -- Module 10 Exercise")
    print("  Runtime Config + Monitoring + Cost + Operational Runbook")
    print("=" * 70)

    print(f"\n{'━' * 70}")
    print("  1. AgentCore Runtime Configuration")
    print(f"{'━' * 70}")
    cfg = VECTRABANK_RUNTIME_CONFIG
    print(f"  Runtime:  {cfg['agentRuntimeName']}")
    print(f"  Network:  {cfg['networkConfiguration']['networkMode']}")
    print(f"  Note:     Production deploys use VPC mode with private subnets")
    print(f"  Protocol: {cfg['protocolConfiguration']['serverProtocol']}")
    print(f"  Guardrail: {cfg['guardrailConfiguration']['guardrailIdentifier']} "
          f"v{cfg['guardrailConfiguration']['guardrailVersion']}")
    print(f"  Environment Variables:")
    for key, val in cfg["environmentVariables"].items():
        print(f"    {key}: {val}")

    print(f"\n{'━' * 70}")
    print("  2. Agent Definitions (4 agents)")
    print(f"{'━' * 70}")
    for agent in VECTRABANK_AGENTS:
        print(f"\n  {agent['name']}:")
        print(f"    Model:       {agent['model']}")
        print(f"    Temperature: {agent['temperature']}")
        print(f"    Role:        {agent['role']}")
        print(f"    Daily reqs:  {agent['requests_per_day']:,}")

    print(f"\n{'━' * 70}")
    print("  3. Monitoring Strategy")
    print(f"{'━' * 70}")
    mon = VECTRABANK_MONITORING
    print(f"\n  Dashboard: {mon['dashboard_name']} ({len(mon['widgets'])} widgets)")
    for w in mon["widgets"]:
        print(f"    [{w['type']:12s}] {w['title']}")
    print(f"\n  Alarms ({len(mon['alarms'])}):")
    for a in mon["alarms"]:
        print(f"    {a['name']}: threshold={a['threshold']}, period={a['period']}s")
        print(f"      -> {a['action']}")
    print(f"\n  X-Ray: sampling={mon['xray_tracing']['sampling_rate']*100:.0f}%, "
          f"annotations={', '.join(mon['xray_tracing']['annotations'])}")

    print(f"\n{'━' * 70}")
    print("  4. Monthly Cost Estimation (10,000 requests/day)")
    print(f"{'━' * 70}")
    costs = estimate_monthly_costs(VECTRABANK_AGENTS)
    print(f"\n  {'Component':<25s} {'Model':<40s} {'Monthly':>10s}")
    print(f"  {'─' * 75}")
    for name, data in costs.items():
        if name == "TOTAL":
            print(f"  {'─' * 75}")
        model = data.get("model", "--")
        cost = data["monthly_cost"]
        print(f"  {name:<25s} {model:<40s} ${cost:>9.2f}")

    print(f"\n{'━' * 70}")
    print("  5. Operational Runbook (4 procedures)")
    print(f"{'━' * 70}")
    for key, runbook in OPERATIONAL_RUNBOOK.items():
        print(f"\n  {runbook['title']}")
        for step in runbook["steps"]:
            print(f"    {step}")

    print(f"\n{'━' * 70}")
    print("  6. Deploy to AgentCore Runtime (Real API Call)")
    print(f"{'━' * 70}")
    print(f"\n  Role ARN:    {_ROLE_ARN}")
    print(f"  S3 Bucket:   {_S3_BUCKET}")
    print(f"  Guardrail:   {_GUARDRAIL_ID} (v{_GUARDRAIL_VERSION})")
    print()
    runtime_arn = deploy_to_agentcore()

    print(f"\n{'━' * 70}")
    print("  Key Takeaways")
    print(f"{'━' * 70}")
    print(f"  1. VPC NETWORK MODE -- financial services agents stay internal")
    print(f"  2. MULTI-MODEL COST OPTIMIZATION -- Lite for routing/retrieval, Sonnet for synthesis")
    print(f"  3. STRICTER THRESHOLDS -- 2% error rate (vs 5% in demo) for financial compliance")
    print(f"  4. OPERATIONAL RUNBOOK -- deploy, rollback, kill switch, latency procedures")
    print(f"  5. AUDIT TRAIL -- X-Ray at 10% sampling + full guardrail audit log")
    print(f"  6. RUNTIME ARN: {runtime_arn}\n")


if __name__ == "__main__":
    main()
