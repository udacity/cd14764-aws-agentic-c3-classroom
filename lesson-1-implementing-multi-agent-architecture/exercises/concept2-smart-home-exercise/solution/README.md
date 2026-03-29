# Module 1 Exercise — Solution: 3-Agent Smart Home Device Management System

## Overview

This exercise builds a 3-agent IoT device management system: a DeviceMonitor reads sensor data, a DiagnosticsAgent identifies issues from readings, and a CommandAgent sends corrective actions. The coordinator wires them together in a monitor → diagnose → command pipeline.

## Architecture

```
Sensor Data (JSON)
      │
CoordinatorAgent (orchestrates the pipeline)
      │
  ┌───┼───────────────────┐
  │   │                   │
DeviceMonitor  DiagnosticsAgent  CommandAgent
(reads sensors) (identifies issues) (sends commands)
```

## Test Scenarios

1. **DEV-001** (Thermostat, 92.5°F) → overheating → restart device
2. **DEV-002** (Smart Lock, 12% connectivity) → firmware issue → push update
3. **DEV-003** (Doorbell Camera, 7% battery) → low battery → recharge notification

## Running

```bash
pip install strands-agents boto3
python smart_home_device_mgmt.py
```

## Tech Stack

- Python 3.11+
- Strands Agents SDK (`Agent`, `tool`, `BedrockModel`)
- Amazon Bedrock (Claude 3 Sonnet)
