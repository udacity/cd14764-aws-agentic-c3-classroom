# Lesson 10 — Production Deployment and Monitoring

This lesson deploys a real AgentCore Runtime to AWS Bedrock and observes
CloudWatch metrics, alarms, and X-Ray traces. You will use the
`bedrock-agentcore-control` boto3 client to deploy, configure, and monitor
a production-ready agent runtime.

---

## Prerequisites

- Python 3.10+
- A Udacity lab session with AWS credentials loaded
- The guardrail you created in Lesson 9 — you'll paste its ID into `.env`

---

## Setup (do this once per lab session)

### Step 1 — Install dependencies

```bash
cd lesson-10-production-deployment-and-monitoring
pip install -r requirements.txt
```

### Step 2 — Add your AWS credentials

```bash
cp .env.example .env
```

Open `.env` and replace the three placeholder values with the credentials
from your Udacity lab sidebar ("Load AWS Credentials"):

```
AWS_ACCESS_KEY_ID=ASIA...
AWS_SECRET_ACCESS_KEY=...
AWS_SESSION_TOKEN=...
```

> **Never commit `.env` to git — it is gitignored.**

### Step 3 — Deploy the lesson infrastructure

This creates the IAM role and S3 bucket that AgentCore Runtime requires.
Run it once; subsequent runs detect the existing stack and exit immediately.

```bash
python infrastructure/deploy_stack.py
```

Expected output:

```
Creating stack 'lesson-10-runtime'...
  Done: CREATE_COMPLETE

============================================================
  Lesson 10 Infrastructure — Ready
============================================================

  AgentCore Role ARN:
    arn:aws:iam::<ACCOUNT_ID>:role/lesson-10-runtime-agentcore-role

  S3 Artifact Bucket:
    lesson-10-runtime-artifacts-<ACCOUNT_ID>

  You are ready to run:
    python demo-deployment-walkthrough/deployment_walkthrough.py
    python exercise-vectrabank-architecture/solution/vectrabank_architecture.py
```

---

## Demo — Insurance Claims Deployment Walkthrough

```bash
python demo-deployment-walkthrough/deployment_walkthrough.py
```

This script walks through the full deployment lifecycle:
1. Builds an in-memory deployment artifact (`.zip`) and uploads it to S3
2. Calls `create_agent_runtime()` with guardrail, network, and observability config
3. Waits for the runtime to reach `READY` status
4. Enables CloudWatch logging via `put_agent_runtime_logging_configuration`
5. Prints the runtime ARN and endpoint URL

---

## Exercise — VectraBank Multi-Agent Architecture

```bash
python exercise-vectrabank-architecture/solution/vectrabank_architecture.py
```

Deploys a financial-services grade architecture:
- 4 specialized agents (Market Data, Risk Assessment, Portfolio, Compliance)
- VPC network mode with private endpoints
- 10% X-Ray sampling
- 3 CloudWatch alarms (error rate, latency, throttling)
- 6-widget CloudWatch dashboard

---

## Troubleshooting

**`NoCredentialsError`** — Your `.env` is missing or has wrong values.
Double-check that `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and
`AWS_SESSION_TOKEN` are all filled in (no placeholder text remaining).

**`Stack is in a failed state`** — `deploy_stack.py` automatically deletes
and re-creates failed stacks. Just re-run it.

**`ResourceNotFoundException` on logging config** — The script catches this
and continues. The runtime itself is still created successfully.

**Credentials expired mid-run** — Lab sessions have short-lived tokens.
Get fresh credentials from the sidebar, update `.env`, and re-run.
