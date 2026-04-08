# Exercise Solution: Smart Home Device Management

This folder contains the working solution for the Module 1 exercise.

## File
- `smart_home_device_mgmt.py` — Complete implementation of a smart home device management agent.

## What It Demonstrates
- Same 1-agent-3-tools pattern as the demo, applied to a different domain (IoT)
- Tools: read_sensor_data, diagnose_issue, send_device_command
- Keyword-based diagnostic rules with regex fallback parsing

## How to Run
```bash
python smart_home_device_mgmt.py
```

## Expected Output
- DEV-001 (Thermostat) -> Overheating -> restart_device
- DEV-002 (Smart Lock) -> Firmware issue -> push_firmware_update
- DEV-003 (Doorbell Camera) -> Low battery -> send_recharge_notification
