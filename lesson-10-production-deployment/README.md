# Lesson 10: Production Deployment and Monitoring

This lesson covers the development-to-production transition for multi-agent systems. We walk through AgentCore Runtime configuration (network mode, protocol, guardrails, environment variables), deployment pipelines, monitoring strategy (CloudWatch dashboards, alarms, X-Ray tracing), and cost estimation. This is a planning and configuration lesson — no agents call Bedrock.

## Folder Structure

```
lesson-10-production-deployment/
├── README.md
├── demo-deployment-walkthrough/
│   ├── README.md
│   └── deployment_walkthrough.py
└── exercise-vectrabank-architecture/
    ├── solution/
    │   ├── README.md
    │   └── vectrabank_architecture.py
    └── starter/
        ├── README.md
        └── vectrabank_architecture.py
```

## Demo: Production Deployment Walkthrough (Instructor-led)
- **Domain:** Insurance claims processing system
- **Runtime config:** PUBLIC network mode, MCP protocol, guardrails, environment variables
- **Deployment pipeline:** 6 steps — build → guardrail → runtime → memory → observability → smoke test
- **Monitoring:** 4 dashboard widgets, 2 alarms, X-Ray tracing
- **Cost estimation:** Per-agent model token costs + infrastructure
- **Key insight:** Model selection is the biggest cost driver — multi-model strategy saves ~60%

## Exercise: VectraBank Deployment Architecture (Student-led)
- **Domain:** VectraBank financial services (capstone project preview)
- **VPC network mode:** Financial services = internal only
- **Operational runbook (NEW):** Deploy, rollback, kill switch, latency investigation procedures
- **Stricter thresholds:** 2% error rate (vs 5% in demo) for financial compliance
- **Key insight:** Planning deployment, monitoring, and incident response BEFORE going live prevents production emergencies
