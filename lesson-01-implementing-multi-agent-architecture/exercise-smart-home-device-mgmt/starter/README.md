# Exercise Starter: Smart Home Device Management

This folder contains the starter code for the Module 1 exercise.

## File
- `smart_home_device_mgmt.py` — Partially implemented. Students must complete 6 TODOs.

## TODOs
1. **TODO 1:** Build the Device Monitor agent (model + system prompt + tool)
2. **TODO 2:** Build the Diagnostics agent (model + system prompt + tool)
3. **TODO 3:** Build the Command agent (model + system prompt + tool)
4. **TODO 4:** Coordinator step 1 — call Device Monitor and parse response
5. **TODO 5:** Coordinator step 2 — call Diagnostics Agent with sensor data
6. **TODO 6:** Coordinator step 3 — call Command Agent for each issue

## Pre-Written Code
- All 3 tool implementations (read_sensor_data, diagnose_issue, send_device_command)
- Helper functions (clean_response, run_agent_with_retry)
- Sample data (devices, sensor readings, diagnostic rules, corrective actions)
- Main function with test loop and summary output

## Pattern Reference
Follow the same multi-agent coordinator pattern from the demo (healthcare_triage.py):
each agent gets its own BedrockModel, system prompt, and tool.
