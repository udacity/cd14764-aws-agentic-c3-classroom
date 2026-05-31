# Lesson 10 — Production Deployment and Monitoring

This lesson deploys a real AgentCore Runtime to AWS Bedrock and observes CloudWatch metrics, alarms, and X-Ray traces. You will use the `bedrock-agentcore-control` boto3 client to deploy, configure, and monitor a production-ready agent runtime.

Each activity folder below has its own `infrastructure/`, `.env.example`, and `README.md` — open the one you're working on for setup steps.

## Folder Structure

```
lesson-10-production-deployment-and-monitoring/
├── README.md
├── demo-deployment-walkthrough/
│   ├── README.md
│   ├── .env.example
│   ├── infrastructure/
│   │   ├── deploy_stack.py
│   │   └── stack.yaml                    ← demo AgentCore role + S3 bucket
│   └── deployment_walkthrough.py
└── exercise-vectrabank-architecture/
    ├── starter/
    │   ├── README.md
    │   ├── .env.example
    │   ├── infrastructure/
    │   │   ├── deploy_stack.py
    │   │   └── stack.yaml                ← exercise AgentCore role + S3 bucket
    │   └── vectrabank_architecture.py
    └── solution/
        ├── README.md
        ├── .env.example
        ├── infrastructure/                ← same as starter; deploy only if you skipped the starter
        └── vectrabank_architecture.py
```

- **Demo (insurance claims):** Production-ready AgentCore Runtime deployment with monitoring, guardrails, and a 6-step gated pipeline.
- **Exercise (VectraBank):** Same deployment pattern with VPC network mode, stricter compliance thresholds, operational runbooks, and a 4-agent architecture.

**Guardrail prerequisite:** Both activities expect `GUARDRAIL_ID` in `.env` from Lesson 9.
