"""
smart_home_device_mgmt.py - SOLUTION
======================================
Module 1 Exercise: Smart Home Device Management System

Architecture:
    Device ID
        │
    DeviceManager Agent (single agent with 3 specialized tools)
        │
    ┌───┼───────────────────┐
    │   │                   │
read_sensor_data  diagnose_issue  send_device_command
(reads sensors)   (identifies issues)  (sends commands)

Tech Stack:
  - Python 3.11+
  - Strands Agents SDK (Agent class, @tool decorator)
  - Amazon Bedrock (Claude 3 Sonnet)
"""

import json
import logging
from datetime import datetime
from strands import Agent, tool
from strands.models import BedrockModel

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────
AWS_REGION = "us-east-1"
MODEL_ID = "anthropic.claude-3-sonnet-20240229-v1:0"

# ─────────────────────────────────────────────────────
# SAMPLE DATA
# ─────────────────────────────────────────────────────
DEVICE_REGISTRY = {
    "DEV-001": {"name": "Living Room Thermostat", "type": "thermostat", "location": "living room"},
    "DEV-002": {"name": "Front Door Smart Lock",  "type": "smart_lock", "location": "front door"},
    "DEV-003": {"name": "Doorbell Camera",         "type": "camera",     "location": "front porch"},
}

SENSOR_READINGS = [
    {
        "device_id": "DEV-001",
        "timestamp": "2025-01-15T14:30:00Z",
        "readings": {"temperature": 92.5, "humidity": 35, "connectivity": 85, "battery": 100},
    },
    {
        "device_id": "DEV-002",
        "timestamp": "2025-01-15T14:30:00Z",
        "readings": {"temperature": 68.0, "humidity": 45, "connectivity": 12, "battery": 72},
    },
    {
        "device_id": "DEV-003",
        "timestamp": "2025-01-15T14:30:00Z",
        "readings": {"temperature": 55.0, "humidity": 60, "connectivity": 90, "battery": 7},
    },
]

DIAGNOSTIC_RULES = {
    "overheating":    {"threshold": 85, "field": "temperature",  "operator": ">"},
    "firmware_issue": {"threshold": 20, "field": "connectivity", "operator": "<"},
    "low_battery":    {"threshold": 10, "field": "battery",      "operator": "<"},
}

CORRECTIVE_ACTIONS = {
    "overheating":    {"action": "restart_device",             "message": "Restarting device to cool down and recalibrate sensors."},
    "firmware_issue": {"action": "push_firmware_update",       "message": "Pushing firmware update v2.1.3 to restore connectivity."},
    "low_battery":    {"action": "send_recharge_notification", "message": "Sending low-battery alert to homeowner's phone."},
}


# ═══════════════════════════════════════════════════════
#  DEVICE MANAGER AGENT — 1 Agent with 3 tools
# ═══════════════════════════════════════════════════════

def build_device_manager() -> Agent:
    """
    Build the Device Manager Agent with three specialized tools.
    """

    model = BedrockModel(
        model_id=MODEL_ID,
        region_name=AWS_REGION,
        temperature=0.0,
    )

    system_prompt = """You are a smart home device manager agent. For each device, call these 3 tools in EXACT order:

1. read_sensor_data — pass the device_id
2. diagnose_issue — pass the EXACT JSON string returned by read_sensor_data
3. send_device_command — pass the device_id AND each issue_type from diagnose_issue's "issues" array

CRITICAL RULES:
- When calling diagnose_issue, pass the raw JSON from read_sensor_data as-is
- When calling send_device_command, use the exact "issue" field values from the diagnosis (e.g., "overheating", "firmware_issue", "low_battery")
- If diagnose_issue finds NO issues, skip send_device_command and report the device is healthy
- After all tools complete, write a 3-line summary: readings, diagnosis, actions taken"""

    @tool
    def read_sensor_data(device_id: str) -> str:
        """
        Read the latest sensor data for a device.

        Args:
            device_id: The device's unique identifier (e.g., "DEV-001")

        Returns:
            JSON string with device info and current sensor readings
        """
        device_info = DEVICE_REGISTRY.get(device_id)
        if not device_info:
            return json.dumps({"error": f"Device {device_id} not found in registry"})

        reading = None
        for r in SENSOR_READINGS:
            if r["device_id"] == device_id:
                reading = r
                break

        if not reading:
            return json.dumps({"error": f"No sensor data available for {device_id}"})

        return json.dumps({
            "device_id": device_id,
            "device_name": device_info["name"],
            "device_type": device_info["type"],
            "location": device_info["location"],
            "timestamp": reading["timestamp"],
            "readings": reading["readings"],
        }, indent=2)

    @tool
    def diagnose_issue(sensor_data_json: str) -> str:
        """
        Apply diagnostic rules to sensor readings to identify issues.

        Rules:
        - temperature > 85 = overheating
        - connectivity < 20 = firmware_issue
        - battery < 10 = low_battery

        Args:
            sensor_data_json: The JSON string returned by read_sensor_data

        Returns:
            JSON string with device_id, issues found, and status
        """
        data = {}
        readings = {}

        try:
            data = json.loads(sensor_data_json)
            readings = data.get("readings", {})
        except (json.JSONDecodeError, AttributeError, TypeError):
            import re
            text_lower = sensor_data_json.lower()
            temp_match = re.search(r'temperature["\s:]*(\d+\.?\d*)', text_lower)
            if temp_match:
                readings["temperature"] = float(temp_match.group(1))
            conn_match = re.search(r'connectivity["\s:]*(\d+\.?\d*)', text_lower)
            if conn_match:
                readings["connectivity"] = float(conn_match.group(1))
            batt_match = re.search(r'battery["\s:]*(\d+\.?\d*)', text_lower)
            if batt_match:
                readings["battery"] = float(batt_match.group(1))

        issues = []
        for issue_name, rule in DIAGNOSTIC_RULES.items():
            value = readings.get(rule["field"], 0)
            if rule["operator"] == ">" and value > rule["threshold"]:
                issues.append({"issue": issue_name, "field": rule["field"], "value": value, "threshold": rule["threshold"]})
            elif rule["operator"] == "<" and value < rule["threshold"]:
                issues.append({"issue": issue_name, "field": rule["field"], "value": value, "threshold": rule["threshold"]})

        return json.dumps({
            "device_id": data.get("device_id", "unknown"),
            "issues_found": len(issues),
            "issues": issues,
            "status": "issues_detected" if issues else "healthy",
        }, indent=2)

    @tool
    def send_device_command(device_id: str, issue_type: str) -> str:
        """
        Send a corrective command to a device based on the diagnosed issue.

        Args:
            device_id: The device's unique identifier
            issue_type: The type of issue ("overheating", "firmware_issue", "low_battery")

        Returns:
            JSON string with command confirmation and action taken
        """
        action_info = CORRECTIVE_ACTIONS.get(issue_type)
        if not action_info:
            return json.dumps({"status": "error", "message": f"No action for: {issue_type}"})

        device_info = DEVICE_REGISTRY.get(device_id, {"name": "Unknown"})

        return json.dumps({
            "status": "command_sent",
            "device_id": device_id,
            "device_name": device_info.get("name", "Unknown"),
            "issue": issue_type,
            "action": action_info["action"],
            "message": action_info["message"],
            "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }, indent=2)

    return Agent(
        model=model,
        system_prompt=system_prompt,
        tools=[read_sensor_data, diagnose_issue, send_device_command],
    )


# ═══════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("  Smart Home Device Management — Module 1 Exercise")
    print("  Strands Agents SDK: Agent + @tool + BedrockModel")
    print("=" * 60)

    test_scenarios = [
        {"device_id": "DEV-001", "expected": "overheating",   "desc": "Thermostat at 92.5°F"},
        {"device_id": "DEV-002", "expected": "firmware_issue", "desc": "Smart lock at 12% connectivity"},
        {"device_id": "DEV-003", "expected": "low_battery",    "desc": "Doorbell camera at 7% battery"},
    ]

    for s in test_scenarios:
        print(f"\n{'─' * 60}")
        print(f"  Scenario: {s['desc']}")
        print(f"  Device: {s['device_id']} | Expected: {s['expected']}")
        print(f"{'─' * 60}")

        # Fresh agent per device to avoid context accumulation
        manager = build_device_manager()

        response = manager(f"Check device {s['device_id']}. Read sensors, diagnose issues, send corrective commands.")
        print(f"\n  Result:\n  {response}\n")


if __name__ == "__main__":
    main()
