# Demo Solution: Multi-Model Incident Response

This folder contains the working solution for the Module 2 demo.

## File
- `incident_response.py` — Complete implementation of a multi-model incident response system.

## What It Demonstrates
- Creating three BedrockModel instances with different model IDs (Nova Lite, Claude, Nova Pro)
- Assigning models to agents based on task requirements (fast routing, deep analysis, balanced drafting)
- Python-orchestrated pipeline across three agents
- Latency comparison table showing model speed/quality tradeoffs

## How to Run
```bash
python incident_response.py
```

## Expected Output
- INC-001 (CPU spike) -> Critical -> Root cause analysis -> Urgent status update
- INC-002 (Disk usage) -> Warning -> Root cause analysis -> Proactive alert
- INC-003 (Deployment) -> Info -> Normal activity -> Brief status update
- Latency comparison table (Nova Lite fastest, Claude slowest)
