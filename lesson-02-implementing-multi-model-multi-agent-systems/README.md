# Lesson 2: Multi-Model Systems

This lesson covers assigning different Bedrock foundation models to different agents based on task requirements (fast vs. deep vs. balanced).

## Folder Structure

```
lesson-02-implementing-multi-model-multi-agent-systems/
├── README.md
├── demo-multi-model-incident-response/
│   ├── README.md
│   └── incident_response.py
└── exercise-content-moderation-pipeline/
    ├── solution/
    │   ├── README.md
    │   └── content_moderation.py
    └── starter/
        ├── README.md
        └── content_moderation.py
```

## Demo: Multi-Model Incident Response (Instructor-led)
- **Domain:** Cloud Infrastructure
- **Architecture:** 3 agents, 3 models — Alert Router (Nova Lite), Root Cause Analyzer (Claude), Status Drafter (Nova Pro)
- **Test cases:** INC-001 (critical CPU spike), INC-002 (warning disk usage), INC-003 (info deployment)
- **Key insight:** Latency comparison table showing model speed/quality tradeoffs

## Exercise: Content Moderation Pipeline (Student-led)
- **Domain:** Social Media / Content Safety
- **Architecture:** 3 agents — Screener (Nova Lite, all posts), Deep Reviewer (Claude, borderline only), Notice Agent (Nova Pro, harmful only)
- **Test cases:** 9 posts (3 safe, 3 harmful, 3 borderline) — demonstrates fast-track path vs. full pipeline
- **Key insight:** Safe posts skip Claude entirely — cheapest model for easy cases
