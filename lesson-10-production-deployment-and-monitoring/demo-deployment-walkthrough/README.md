# Demo: Production Deployment Walkthrough

## Architecture

![Architecture Diagram](architecture.svg)

## Overview
This demo walks through the complete development-to-production transition for a multi-agent insurance claims processing system. It defines AgentCore Runtime configuration, a 6-step deployment pipeline, monitoring strategy, and cost estimates. The runtime is deployed to a real Bedrock AgentCore Runtime via `create_agent_runtime()` using the IAM role and S3 artifact bucket the stack provisions.

## Setup

1. Copy the env template and paste credentials from the "Load AWS Credentials" sidebar:
   ```bash
   cp .env.example .env
   ```
2. Deploy the IAM role, S3 artifact bucket, and Bedrock guardrail:
   ```bash
   python infrastructure/deploy_stack.py
   ```

All resource identifiers (role ARN, bucket name, guardrail ID) are auto-discovered from CloudFormation exports — no manual values needed in `.env`.

**How this works:** at startup, `_load_cf_exports()` calls `cloudformation:ListExports` to fetch every export in your region, then picks the three values it needs by their export names (e.g. `lesson-10-demo-AgentCoreRoleArn`). Your AWS credentials in `.env` are what authorize that API call.

## What This Demo Covers
1. **Runtime config** — name, network mode (PUBLIC), protocol (MCP), guardrails, env vars
2. **Agent definitions** — 3 agents with different models and cost profiles
3. **Deployment pipeline** — 6 gated steps from build to smoke test
4. **Monitoring** — dashboard widgets, alarms, X-Ray tracing
5. **Cost estimation** — per-agent model costs + infrastructure

## Running
```bash
python deployment_walkthrough.py
```

## Cleanup
```bash
aws cloudformation delete-stack --stack-name lesson-10-demo-runtime
```

You may also want to delete the AgentCore Runtime itself from the Bedrock console (Runtime → select → Delete) if the demo created one.

## Key Takeaways
1. **Runtime is configuration** — AgentCore Runtime deploys config, not code packages
2. **Environment variables** — no hardcoded IDs; same code for dev/staging/prod
3. **Multi-model cost optimization** — Lite for routing, Sonnet for analysis
4. **Gated deployment** — each step has a pass/fail gate before proceeding
5. **Monitoring before launch** — dashboard and alarms set up before first production request
