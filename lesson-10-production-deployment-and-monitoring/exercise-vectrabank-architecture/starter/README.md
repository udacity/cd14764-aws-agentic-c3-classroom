# Exercise: VectraBank Deployment Architecture

![Architecture Diagram](architecture.svg)

This activity reviews runtime configuration, agent roles, monitoring and costs.
The Python script deploys through the provided `agentcore_cli.py` helper using
AgentCore CLI 0.30.0, already available in the classroom environment.

**Scope:** The deployed HTTP endpoint is a deployment smoke test. Agent definitions,
Knowledge Base IDs, dashboards, alarms and X-Ray sampling are architecture plans;
this activity does not execute the proposed multi-agent workflow or create those
monitoring resources. `runtime/main.py` makes no model calls. Guardrail identifiers
are supplied as runtime environment variables for future application model calls.

**Video note:** The video shows the earlier AWS SDK deployment workflow. Follow
these instructions and the updated workspace files for AgentCore CLI deployment.

## Setup

1. Copy `.env.example` to `.env` and paste the student AWS credentials from
   “Load AWS Credentials.” Check `AWS_REGION`.
2. Deploy the supporting execution role and guardrail:
   ```bash
   python infrastructure/deploy_stack.py
   ```

The helper reads the role and guardrail from the `lesson-10-exercise-runtime` stack.
The CLI manages the separate runtime stack and deployment asset storage.
When moving from starter to solution, reuse the supporting stack and remove the
starter runtime stack first. Run setup again only if the supporting stack is absent
or the infrastructure template changed.

## Your Task
Complete **8 TODOs** in `vectrabank_architecture.py`:

| TODO | What to define | Hint |
|------|----------------|------|
| TODO 1 | Runtime configuration | PUBLIC/HTTP for lab; document production VPC; env vars for 3 KBs |
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
- Runtime config with PUBLIC/HTTP for the lab and a production VPC plan
- 4 agent definitions with model assignments
- 6-widget dashboard + 3 alarms + X-Ray config
- Monthly cost table
- 4 operational runbook procedures

## Run

Complete all eight TODO sections first. The supplied deployment helper is not a student TODO.

```bash
python vectrabank_architecture.py
agentcore status
agentcore invoke '{"prompt":"deployment smoke test"}'
```

The expected invocation response says “Lesson 10 deployment smoke test passed”;
it does not validate model access or process a business request. The runtime uses
PUBLIC networking and HTTP. Real VPC deployment requires additional network resources.
Re-running the Python script updates the CLI configuration and existing runtime.
Never copy AWS credentials into the runtime configuration. The execution role
provides the runtime's AWS access.

## Cleanup

In the CloudFormation console, delete `AgentCore-lesson10starter-default` and wait for
completion. Then delete the supporting infrastructure when it is no longer needed
by either exercise folder:

```bash
aws cloudformation delete-stack --stack-name lesson-10-exercise-runtime
```

Do not delete a CLI-managed runtime individually in the AgentCore console.
The shared `CDKToolkit` bootstrap stack may be used by other activities; leave it in place.
For a different student account or region, start with a fresh copy of this activity.
