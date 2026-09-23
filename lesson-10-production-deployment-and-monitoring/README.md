# Lesson 10 — Production Deployment and Monitoring

The demo, exercise starter and solution use AgentCore CLI 0.30.0 for runtime deployment.
Open the activity README for setup, invocation and cleanup:

- [Insurance claims demo](demo-deployment-walkthrough/README.md)
- [VectraBank starter](exercise-vectrabank-architecture/starter/README.md)
- [VectraBank solution](exercise-vectrabank-architecture/solution/README.md)

Each activity is self-contained: `agentcore_cli.py` provides deployment support,
`agentcore/` holds CLI configuration, `runtime/` contains the HTTP smoke-test endpoint,
and `infrastructure/` provisions the execution role and guardrail using CloudFormation.
Python 3.12+ and the CLI are provided by the classroom environment.

The runtime smoke test verifies deployment, not a complete business workflow.
Agent roles, monitoring, costs and operational runbooks remain architecture exercises.
The starter retains all eight student TODO sections. Neither model access nor
monitoring configuration is verified by a successful smoke test.

The videos show the previous SDK deployment. Use the updated activity instructions.
