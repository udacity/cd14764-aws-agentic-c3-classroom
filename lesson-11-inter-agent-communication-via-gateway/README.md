# Lesson 11 — Inter-Agent Communication via Gateway

This lesson teaches the **AgentCore Gateway pattern**: instead of hardcoding
tool integrations with `@tool` decorators, you register APIs with a Gateway
and agents discover them through MCP at runtime. Tools can be added, updated,
or removed without touching agent code.

The demo uses real AWS Lambda functions as tool backends and ends with a live
`create_gateway` / `create_gateway_target` call to show the exact production
API.

---

## Prerequisites

- Python 3.10+
- A Udacity lab session with AWS credentials loaded

---

## Setup (do this once per lab session)

### Step 1 — Install dependencies

```bash
cd lesson-11-inter-agent-communication-via-gateway
pip install -r ../lesson-10-production-deployment-and-monitoring/requirements.txt
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

This creates the Lambda tool backends and the AgentCore Gateway IAM role.
Run it once; subsequent runs detect the existing stack and exit immediately.

```bash
python infrastructure/deploy_stack.py
```

Expected output:

```
Creating stack 'lesson-11-gateway'...
  Done: CREATE_COMPLETE

============================================================
  Lesson 11 Infrastructure — Ready
============================================================

  AgentCore Gateway Role ARN:
    arn:aws:iam::<ACCOUNT_ID>:role/lesson-11-gateway-agentcore-role

  Lambda Functions:
    Inventory     arn:aws:lambda:us-east-1:...
    Shipping      arn:aws:lambda:us-east-1:...
    ...

  Next step — paste the Role ARN into your .env:
    AGENTCORE_ROLE_ARN=arn:aws:iam::<ACCOUNT_ID>:role/...
```

### Step 4 — Paste the role ARN into `.env`

Copy the `AGENTCORE_ROLE_ARN=...` line from the output above and add it
to your `.env` file.

---

## Demo — Supply Chain Gateway (Instructor-led)

```bash
python demo-supply-chain-gateway/supply_chain_gateway.py
```

This demo covers:
1. **LambdaGateway** — registers tool backends, routes invocations
2. **Dynamic registration** — adds a 4th tool (Quality Inspection) with zero agent code changes
3. **Semantic routing** — agent selects tools by description, not hardcoded names
4. **AgentCore Gateway API** — live `create_gateway` + `create_gateway_target` calls that deploy the same gateway in production

---

## Exercise — Analytics Gateway (Student-led)

```bash
python exercise-analytics-gateway/solution/analytics_gateway.py
```

Students implement the same pattern with a different domain (analytics tools:
weather, currency, news) and learn about mixing Lambda and REST API backends.

---

## Cleanup

```bash
aws cloudformation delete-stack --stack-name lesson-11-gateway
```

If you created an AgentCore Gateway during the demo, delete it from the
Bedrock console: **Gateway → select → Delete**. The CloudFormation stack
only manages the Lambda functions and IAM role.

---

## Troubleshooting

**`NoCredentialsError`** — Your `.env` is missing or has wrong values.
Check that all three AWS credential variables are filled in.

**`Stack is in a failed state`** — `deploy_stack.py` automatically deletes
and re-creates failed stacks. Just re-run it.

**`ResourceNotFoundException` for Lambda** — The Lambda functions may not exist yet.
Run `deploy_stack.py` first and confirm `CREATE_COMPLETE`.

**Credentials expired mid-run** — Lab sessions have short-lived tokens.
Get fresh credentials from the sidebar, update `.env`, and re-run.
