# Exercise Solution: Smart Home Device Management

This folder contains the working solution for the Module 1 exercise.

## File
- `smart_home_device_mgmt.py` — Complete 3-agent device management system.

## What It Demonstrates
- Same multi-agent coordinator pattern as the demo, applied to IoT domain
- 3 Agents: DeviceMonitor, DiagnosticsAgent, CommandAgent
- Coordinator calls agents in sequence, passing outputs forward
- Each agent has a single responsibility and its own tool

## How to Run
```bash
python smart_home_device_mgmt.py
```

## Expected Output
- DEV-001 (Thermostat) -> Overheating -> restart_device
- DEV-002 (Smart Lock) -> Firmware issue -> push_firmware_update
- DEV-003 (Doorbell Camera) -> Low battery -> send_recharge_notification
