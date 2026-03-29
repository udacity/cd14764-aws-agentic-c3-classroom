# Module 1 Exercise — Starter: 3-Agent Smart Home Device Management System

## Overview

Build a 3-agent IoT device management system that monitors devices, diagnoses issues, and sends corrective actions. This exercise reinforces the multi-agent architecture pattern from the demo, applied to a different domain.

## What You Need to Do

Complete all `TODO` items in `smart_home_device_mgmt.py` (16 TODOs total):

### Agent Definitions (TODOs 1-9)
For each of the three agents (DeviceMonitor, DiagnosticsAgent, CommandAgent):
- Create a `BedrockModel` with the correct model ID and temperature
- Write a focused system prompt that enforces single-responsibility
- Instantiate and return the `Agent` with model, prompt, and tools

### Coordinator Wiring (TODOs 10-16)
- Create the coordinator's model and system prompt
- Build the three worker agents
- Implement the routing tools that invoke each worker agent
- Return the coordinator Agent

## Key Patterns (from the demo)

```python
# Creating a model
model = BedrockModel(model_id=MODEL_ID, region_name=AWS_REGION, temperature=0.0)

# Creating an agent
agent = Agent(model=model, system_prompt="...", tools=[my_tool])

# Invoking a worker agent from a routing tool
@tool
def route_to_worker(input_data: str) -> str:
    response = worker_agent(f"Process this: {input_data}")
    return str(response)
```

## Test Scenarios

Your solution should handle these three cases:
1. **DEV-001** (Thermostat at 92.5°F) → overheating → restart device
2. **DEV-002** (Smart Lock at 12% connectivity) → firmware issue → push update
3. **DEV-003** (Doorbell Camera at 7% battery) → low battery → recharge notification

## Running

```bash
pip install strands-agents boto3
python smart_home_device_mgmt.py
```

## Deliverable

A working 3-agent system where the coordinator successfully processes all three test scenarios, producing correct diagnoses and corrective actions for each device.
