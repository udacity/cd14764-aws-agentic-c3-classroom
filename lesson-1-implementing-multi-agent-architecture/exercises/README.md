# Module 1: Implementing Multi-Agent Architecture with Bedrock AgentCore

This lesson contains a demo and an exercise that teach students to build multi-agent systems using the Strands Agents SDK.

## Folder Structure

```
exercises
    |_ concept1-healthcare-triage-demo
    |   |_ starter
    |   |   |_ healthcare_triage.py (with TODOs)
    |   |   |_ README.md
    |   |_ solution
    |   |   |_ healthcare_triage.py (complete)
    |   |   |_ README.md
    |_ concept2-smart-home-exercise
    |   |_ starter
    |   |   |_ smart_home_device_mgmt.py (with TODOs)
    |   |   |_ README.md
    |   |_ solution
    |   |   |_ smart_home_device_mgmt.py (complete)
    |   |   |_ README.md
    |_ README.md
```

## Key Concepts

- `Agent` class, `@tool` decorator, `BedrockModel` from Strands Agents SDK
- Single-responsibility agents with focused system prompts
- Inter-agent communication via @tool decorated routing functions
- Sequential agent pipeline (coordinator → worker agents)
