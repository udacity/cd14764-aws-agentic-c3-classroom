# Module 1 Demo — Starter: Building a 3-Agent Healthcare Triage System

## Overview

In this demo, you will build a 3-agent healthcare triage system from scratch using the Strands Agents SDK and Amazon Bedrock. You will set up three agents (SymptomAnalyzer, UrgencyClassifier, AppointmentScheduler), configure inter-agent communication, and run the system.

## What You Need to Do

Complete all `TODO` items in `healthcare_triage.py`. The TODOs guide you through:

1. **TODOs 1-3**: Build the SymptomAnalyzer agent (model + prompt + Agent instantiation)
2. **TODOs 4-6**: Build the UrgencyClassifier agent
3. **TODOs 7-9**: Build the AppointmentScheduler agent
4. **TODOs 10-16**: Build the Coordinator that wires all three agents together

## Key Patterns

- **BedrockModel**: `BedrockModel(model_id=..., region_name=..., temperature=0.0)`
- **Agent**: `Agent(model=model, system_prompt=prompt, tools=[tool_fn])`
- **@tool decorator**: Already applied to tool functions — you write the agent wiring
- **Inter-agent call**: `response = worker_agent("your prompt here")` then `return str(response)`

## Running

```bash
pip install strands-agents boto3
python healthcare_triage.py
```

## Expected Output

Three patients are triaged:
- Alice (chest pain) → **urgent** → Emergency slot
- Bob (headache/cold) → **routine** → Afternoon slot
- Carol (twisted ankle) → **standard** → Morning slot
