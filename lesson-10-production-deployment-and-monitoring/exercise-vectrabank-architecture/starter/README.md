# Exercise Starter: VectraBank Deployment Architecture

## Architecture

![Architecture Diagram](architecture.svg)

## Overview
Create a deployment architecture plan for VectraBank following the demo pattern (deployment_walkthrough.py). Define runtime configuration, agent definitions, monitoring strategy, cost estimates, and operational runbooks. The runtime is deployed to a real Bedrock AgentCore Runtime using the IAM role and S3 artifact bucket the stack provisions.

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

**How this works:** at startup, `_load_cf_exports()` calls `cloudformation:ListExports` to fetch every export in your region, then picks the three values it needs by their export names (e.g. `lesson-10-exercise-AgentCoreRoleArn`). Your AWS credentials in `.env` are what authorize that API call.

## Your Task
Complete **8 TODOs** in `vectrabank_architecture.py`:

| TODO | What to define | Hint |
|------|----------------|------|
| TODO 1 | Runtime configuration | VPC mode, guardrail, env vars for 3 KBs |
| TODO 2 | 4 agent definitions | Router (Lite), 2 Retrievers (Lite), Advisor (Sonnet) |
| TODO 3 | Dashboard widgets (6) | Queries, latency, errors, guardrails, RAG quality, kill switch |
| TODO 4 | Alarms (3) | Error rate 2%, latency P99 8s, guardrail spike 50/5min |
| TODO 5 | X-Ray tracing config | 10% sampling, financial annotations |
| TODO 6 | Infrastructure costs | DynamoDB, KBs, CloudWatch, VPC |
| TODO 7 | Operational runbook (4 procedures) | Deploy, rollback, kill switch, latency |
| TODO 8 | Print all configs in main() | Follow demo output format |

## What's Already Done
- Cost estimation function (estimate_monthly_costs)
- Model pricing table
- Main function skeleton with output formatting

## Expected Output
- Runtime config with VPC network mode
- 4 agent definitions with model assignments
- 6-widget dashboard + 3 alarms + X-Ray config
- Monthly cost table
- 4 operational runbook procedures

## Running
```bash
python vectrabank_architecture.py
```

## Cleanup
```bash
aws cloudformation delete-stack --stack-name lesson-10-exercise-runtime
```

If the script created an AgentCore Runtime, also delete it from the Bedrock console (Runtime → select → Delete).
