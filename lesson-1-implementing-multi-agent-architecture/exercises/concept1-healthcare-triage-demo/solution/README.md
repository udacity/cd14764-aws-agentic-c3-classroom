# Module 1 Demo — Solution: Building a 3-Agent Healthcare Triage System

## Overview

This demo builds a 3-agent healthcare triage system using the Strands Agents SDK and Amazon Bedrock. It demonstrates the core multi-agent pattern: decompose a complex workflow into focused agents that communicate through well-defined interfaces.

## Architecture

```
Patient Complaint
      │
CoordinatorAgent (orchestrates the pipeline)
      │
  ┌───┼───────────────────┐
  │   │                   │
SymptomAnalyzer  UrgencyClassifier  AppointmentScheduler
```

Each agent has a **single responsibility**:
- **SymptomAnalyzer** — maps symptoms to potential conditions
- **UrgencyClassifier** — assigns triage priority (urgent/standard/routine)
- **AppointmentScheduler** — books the appropriate time slot

## Key Concepts Demonstrated

1. **Agent class pattern**: each agent gets a model, system prompt, and tool set
2. **@tool decorator**: defines agent capabilities as typed Python functions
3. **Inter-agent communication**: coordinator invokes workers via @tool decorated functions
4. **Single-responsibility principle**: each agent handles only its domain

## Running the Demo

```bash
pip install strands-agents boto3
python healthcare_triage.py
```

## Expected Output

The system processes 3 patient complaints:
- Alice (chest pain) → **urgent** → Emergency slot
- Bob (headache/cold) → **routine** → Afternoon slot
- Carol (twisted ankle) → **standard** → Morning slot

## Tech Stack

- Python 3.11+
- Strands Agents SDK (`Agent`, `tool`, `BedrockModel`)
- Amazon Bedrock (Claude 3 Sonnet)
