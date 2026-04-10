"""
deployment_walkthrough.py - DEMO (Instructor-Led)
==============================================================
Module 10 Demo: From Development to Production — AgentCore Runtime Deployment

This demo walks through the complete development-to-production transition
for a multi-agent system. It covers:
  1. AgentCore Runtime configuration
  2. Deployment pipeline (agents → guardrails → runtime → memory → observability)
  3. Monitoring strategy (CloudWatch metrics, X-Ray tracing)
  4. Cost estimation for a 10,000 req/day system

This is a CONFIGURATION AND PLANNING demo — the code defines and prints
deployment configs, NOT running agents. Students learn what decisions to
make BEFORE deploying their capstone project.

Tech Stack:
  - Python 3.11+ (configuration definitions)
  - Amazon Bedrock AgentCore Runtime (simulated configs)
  - Amazon CloudWatch, X-Ray (simulated monitoring configs)
  - AWS Cost estimation
"""

import json
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()


# ═══════════════════════════════════════════════════════
# STEP 1: AgentCore RUNTIME CONFIGURATION
#
# Production equivalent:
#   agentcore = boto3.client('bedrock-agentcore')
#   response = agentcore.create_agent_runtime(
#       agentRuntimeName='insurance-claims-runtime',
#       roleArn='arn:aws:iam::123456789:role/AgentCoreRole',
#       networkConfiguration={'networkMode': 'PUBLIC'},
#       protocolConfiguration={'serverProtocol': 'MCP'},
#       guardrailConfiguration={
#           'guardrailIdentifier': 'gr-insurance-claims',
#           'guardrailVersion': '1'
#       },
#       environmentVariables={...}
#   )
# ═══════════════════════════════════════════════════════

RUNTIME_CONFIG = {
    "agentRuntimeName": "insurance-claims-runtime",
    "description": "Multi-agent system for insurance claims processing",
    "roleArn": "arn:aws:iam::123456789012:role/AgentCoreExecutionRole",

    # Network mode: PUBLIC (internet-facing) vs VPC (internal only)
    "networkConfiguration": {
        "networkMode": "PUBLIC",
        # VPC alternative for internal-only agents:
        # "networkMode": "VPC",
        # "vpcConfiguration": {
        #     "vpcId": "vpc-abc123",
        #     "subnetIds": ["subnet-1", "subnet-2"],
        #     "securityGroupIds": ["sg-abc123"]
        # }
    },

    # Protocol: MCP (Model Context Protocol) for tool communication
    "protocolConfiguration": {
        "serverProtocol": "MCP",
    },

    # Guardrails attached at runtime level (applies to ALL agents)
    "guardrailConfiguration": {
        "guardrailIdentifier": "gr-insurance-claims",
        "guardrailVersion": "1",
    },

    # Environment variables — NO hardcoded IDs in agent code
    "environmentVariables": {
        "CLAIMS_KB_ID": "KB-CLAIMS-001",
        "POLICY_KB_ID": "KB-POLICY-002",
        "STATE_TABLE_NAME": "insurance-claims-state",
        "AWS_REGION": os.environ.get("AWS_REGION", "us-east-1"),
        "LOG_LEVEL": "INFO",
        "ENVIRONMENT": "production",
    },
}


# ═══════════════════════════════════════════════════════
# STEP 2: AGENT DEFINITIONS
# ═══════════════════════════════════════════════════════

AGENT_DEFINITIONS = [
    {
        "name": "ClaimsRouter",
        "model": "amazon.nova-lite-v1:0",
        "temperature": 0.0,
        "role": "Route incoming claims to the correct specialist agent",
        "tools": ["classify_claim", "check_priority"],
        "estimated_tokens_per_request": 500,
        "requests_per_day": 10000,  # Every request hits the router
    },
    {
        "name": "ClaimsAnalyzer",
        "model": "anthropic.claude-3-sonnet-20240229-v1:0",
        "temperature": 0.1,
        "role": "Deep analysis of complex claims (fraud detection, coverage gaps)",
        "tools": ["analyze_claim", "check_fraud_indicators", "retrieve_policy"],
        "estimated_tokens_per_request": 2000,
        "requests_per_day": 3000,  # ~30% of claims need deep analysis
    },
    {
        "name": "ClaimsResponder",
        "model": "amazon.nova-pro-v1:0",
        "temperature": 0.3,
        "role": "Draft customer-facing claim status updates and decisions",
        "tools": ["draft_response", "lookup_template"],
        "estimated_tokens_per_request": 1000,
        "requests_per_day": 10000,  # Every claim gets a response
    },
]


# ═══════════════════════════════════════════════════════
# STEP 3: DEPLOYMENT PIPELINE
# ═══════════════════════════════════════════════════════

DEPLOYMENT_PIPELINE = [
    {
        "step": 1,
        "name": "Build & Test Agents",
        "description": "Run all agent test suites locally",
        "command": "python -m pytest tests/ -v",
        "gate": "All tests pass",
    },
    {
        "step": 2,
        "name": "Create/Update Guardrail",
        "description": "Deploy guardrail configuration to Bedrock",
        "command": "aws bedrock create-guardrail --cli-input-json file://guardrail-config.json",
        "gate": "Guardrail version promoted from DRAFT",
    },
    {
        "step": 3,
        "name": "Deploy AgentCore Runtime",
        "description": "Create or update the runtime with new config",
        "command": "aws bedrock-agentcore create-agent-runtime --cli-input-json file://runtime-config.json",
        "gate": "Runtime status = ACTIVE",
    },
    {
        "step": 4,
        "name": "Configure Memory",
        "description": "Set up AgentCore Memory with SESSION_SUMMARY strategy",
        "command": "aws bedrock-agentcore create-memory --memory-strategy SESSION_SUMMARY",
        "gate": "Memory service healthy",
    },
    {
        "step": 5,
        "name": "Enable Observability",
        "description": "Configure CloudWatch Logs, X-Ray tracing, custom dashboard",
        "command": "aws cloudwatch put-dashboard --dashboard-name insurance-claims --dashboard-body file://dashboard.json",
        "gate": "Dashboard visible, logs flowing",
    },
    {
        "step": 6,
        "name": "Smoke Test",
        "description": "Send 10 test claims through production endpoint",
        "command": "python smoke_test.py --endpoint $RUNTIME_ENDPOINT --count 10",
        "gate": "10/10 claims processed, latency < 5s P99",
    },
]


# ═══════════════════════════════════════════════════════
# STEP 4: MONITORING STRATEGY
#
# Production equivalent:
#   cloudwatch.put_dashboard(
#       DashboardName='insurance-claims-dashboard',
#       DashboardBody=json.dumps({'widgets': [...]})
#   )
# ═══════════════════════════════════════════════════════

MONITORING_STRATEGY = {
    "dashboard_name": "insurance-claims-dashboard",
    "widgets": [
        {
            "title": "Total Invocations",
            "type": "line",
            "metric": "AgentCore/Invocations",
            "period": 60,
            "stat": "Sum",
        },
        {
            "title": "Latency P50/P99",
            "type": "line",
            "metrics": [
                {"name": "AgentCore/Latency", "stat": "p50"},
                {"name": "AgentCore/Latency", "stat": "p99"},
            ],
            "period": 60,
        },
        {
            "title": "Error Rate",
            "type": "number",
            "metric": "AgentCore/Errors",
            "period": 300,
            "stat": "Average",
            "threshold": 0.05,  # 5% error rate alarm
        },
        {
            "title": "Guardrail Blocks by Type",
            "type": "stacked_bar",
            "metrics": [
                {"name": "Guardrail/ContentBlocks", "label": "Content"},
                {"name": "Guardrail/PIIBlocks", "label": "PII"},
                {"name": "Guardrail/TopicBlocks", "label": "Topic"},
            ],
            "period": 300,
        },
    ],
    "alarms": [
        {
            "name": "HighErrorRate",
            "metric": "AgentCore/Errors",
            "threshold": 0.05,
            "period": 300,
            "action": "SNS → kill-switch-topic → Lambda disables runtime",
        },
        {
            "name": "HighLatency",
            "metric": "AgentCore/Latency",
            "stat": "p99",
            "threshold": 10.0,  # 10 seconds P99
            "period": 300,
            "action": "SNS → ops-team-pager",
        },
    ],
    "xray_tracing": {
        "enabled": True,
        "sampling_rate": 0.05,  # 5% of requests
        "annotations": ["claim_type", "agent_name", "model_id"],
    },
}


# ═══════════════════════════════════════════════════════
# STEP 5: COST ESTIMATION
# ═══════════════════════════════════════════════════════

# Bedrock pricing (approximate, us-east-1, per 1K tokens)
MODEL_PRICING = {
    "amazon.nova-lite-v1:0": {"input": 0.00006, "output": 0.00024},
    "amazon.nova-pro-v1:0": {"input": 0.0008, "output": 0.0032},
    "anthropic.claude-3-sonnet-20240229-v1:0": {"input": 0.003, "output": 0.015},
}


def estimate_monthly_costs(agents: list, days: int = 30) -> dict:
    """Estimate monthly costs for a multi-agent system."""
    costs = {}
    total = 0

    for agent in agents:
        model = agent["model"]
        pricing = MODEL_PRICING.get(model, {"input": 0.001, "output": 0.005})
        tokens = agent["estimated_tokens_per_request"]
        daily_requests = agent["requests_per_day"]

        # Assume 60% input tokens, 40% output tokens
        input_tokens = tokens * 0.6
        output_tokens = tokens * 0.4

        daily_input_cost = (input_tokens / 1000) * pricing["input"] * daily_requests
        daily_output_cost = (output_tokens / 1000) * pricing["output"] * daily_requests
        monthly_cost = (daily_input_cost + daily_output_cost) * days

        costs[agent["name"]] = {
            "model": model,
            "daily_requests": daily_requests,
            "monthly_cost": round(monthly_cost, 2),
        }
        total += monthly_cost

    # DynamoDB costs (estimated)
    dynamodb_monthly = 25.0  # On-demand: ~10K reads/writes per day
    cloudwatch_monthly = 15.0  # Logs, metrics, dashboard
    xray_monthly = 5.0  # 5% sampling

    costs["DynamoDB"] = {"monthly_cost": dynamodb_monthly}
    costs["CloudWatch"] = {"monthly_cost": cloudwatch_monthly}
    costs["X-Ray"] = {"monthly_cost": xray_monthly}
    total += dynamodb_monthly + cloudwatch_monthly + xray_monthly

    costs["TOTAL"] = {"monthly_cost": round(total, 2)}
    return costs


# ═══════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("  Production Deployment Walkthrough — Module 10 Demo")
    print("  AgentCore Runtime + Monitoring + Cost Estimation")
    print("=" * 70)

    # ── Runtime Configuration ──
    print(f"\n{'━' * 70}")
    print("  1. AgentCore Runtime Configuration")
    print(f"{'━' * 70}")
    print(f"  Runtime:  {RUNTIME_CONFIG['agentRuntimeName']}")
    print(f"  Network:  {RUNTIME_CONFIG['networkConfiguration']['networkMode']}")
    print(f"  Protocol: {RUNTIME_CONFIG['protocolConfiguration']['serverProtocol']}")
    print(f"  Guardrail: {RUNTIME_CONFIG['guardrailConfiguration']['guardrailIdentifier']} "
          f"v{RUNTIME_CONFIG['guardrailConfiguration']['guardrailVersion']}")
    print(f"  Environment Variables:")
    for key, val in RUNTIME_CONFIG["environmentVariables"].items():
        print(f"    {key}: {val}")

    # ── Agent Definitions ──
    print(f"\n{'━' * 70}")
    print("  2. Agent Definitions (3 agents)")
    print(f"{'━' * 70}")
    for agent in AGENT_DEFINITIONS:
        print(f"\n  {agent['name']}:")
        print(f"    Model:       {agent['model']}")
        print(f"    Temperature: {agent['temperature']}")
        print(f"    Role:        {agent['role']}")
        print(f"    Tools:       {', '.join(agent['tools'])}")
        print(f"    Est. tokens: {agent['estimated_tokens_per_request']}/request")
        print(f"    Daily reqs:  {agent['requests_per_day']:,}")

    # ── Deployment Pipeline ──
    print(f"\n{'━' * 70}")
    print("  3. Deployment Pipeline (6 steps)")
    print(f"{'━' * 70}")
    for step in DEPLOYMENT_PIPELINE:
        print(f"\n  Step {step['step']}: {step['name']}")
        print(f"    {step['description']}")
        print(f"    $ {step['command']}")
        print(f"    Gate: {step['gate']}")

    # ── Monitoring Strategy ──
    print(f"\n{'━' * 70}")
    print("  4. Monitoring Strategy")
    print(f"{'━' * 70}")
    print(f"\n  Dashboard: {MONITORING_STRATEGY['dashboard_name']}")
    print(f"  Widgets:")
    for w in MONITORING_STRATEGY["widgets"]:
        print(f"    [{w['type']:12s}] {w['title']}")
    print(f"\n  Alarms:")
    for a in MONITORING_STRATEGY["alarms"]:
        print(f"    {a['name']}: {a['metric']} > {a['threshold']} "
              f"(period: {a['period']}s) → {a['action']}")
    print(f"\n  X-Ray Tracing:")
    xray = MONITORING_STRATEGY["xray_tracing"]
    print(f"    Enabled: {xray['enabled']}, Sampling: {xray['sampling_rate']*100:.0f}%")
    print(f"    Annotations: {', '.join(xray['annotations'])}")

    # ── Cost Estimation ──
    print(f"\n{'━' * 70}")
    print("  5. Monthly Cost Estimation (10,000 requests/day)")
    print(f"{'━' * 70}")
    costs = estimate_monthly_costs(AGENT_DEFINITIONS)
    print(f"\n  {'Component':<25s} {'Model':<40s} {'Monthly Cost':>12s}")
    print(f"  {'─' * 77}")
    for name, data in costs.items():
        if name == "TOTAL":
            print(f"  {'─' * 77}")
        model = data.get("model", "—")
        cost = data["monthly_cost"]
        daily = data.get("daily_requests", "")
        daily_str = f" ({daily:,}/day)" if daily else ""
        print(f"  {name:<25s} {model:<40s} ${cost:>10.2f}{daily_str}")

    # ── Key Takeaways ──
    print(f"\n{'━' * 70}")
    print("  Key Takeaways")
    print(f"{'━' * 70}")
    print(f"  1. RUNTIME CONFIG — network mode, protocol, guardrails, env vars")
    print(f"  2. DEPLOYMENT PIPELINE — build → guardrail → runtime → memory → observability")
    print(f"  3. MONITORING — dashboard (4 widgets), alarms (error rate, latency), X-Ray")
    print(f"  4. COST MANAGEMENT — model selection is the biggest cost driver")
    print(f"     Multi-model strategy (Lite for routing, Sonnet for analysis) saves ~60%")
    print(f"  5. ENV VARS — no hardcoded IDs; same code deploys to dev/staging/prod\n")


if __name__ == "__main__":
    main()
