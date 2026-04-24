"""
smart_home_device_mgmt.py - SOLUTION
======================================
Module 1 Exercise: Build a 3-Agent Smart Home Device Management System

Architecture:
    Sensor Data
         │
    ┌────▼─────┐
    │Coordinator│  (orchestrates the 3 worker agents)
    └──┬──┬──┬─┘
       │  │  │
       ▼  │  │
 ┌─────────┐ │  │
 │ Device   │ │  │   Agent 1: Reads sensor data for a device
 │ Monitor  │─┘  │
 └─────────┘     │
       │         │
       ▼         │
 ┌─────────┐     │
 │Diagnostics│   │   Agent 2: Applies rules to identify issues
 │  Agent   │────┘
 └─────────┘
       │
       ▼
 ┌─────────┐
 │ Command  │        Agent 3: Sends corrective actions
 │  Agent   │
 └─────────┘
       │
       ▼
   Action Report

Pattern: Same multi-agent coordinator pattern as the demo.
Each agent has a single responsibility, its own model, prompt, and tools.
The coordinator calls them in sequence, passing outputs forward.

Tech Stack:
  - Python 3.11+
  - Strands Agents SDK (Agent class, @tool decorator)
  - Amazon Bedrock (Claude 3 Sonnet)
"""

import json
import os
import re
import time
import logging
from datetime import datetime
from dotenv import load_dotenv
from strands import Agent, tool
from strands.models import BedrockModel

load_dotenv()

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-sonnet-4-20250514-v1:0")

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
        "timestamp": "2026-01-15T14:30:00Z",
        "readings": {"temperature": 92.5, "humidity": 35, "connectivity": 85, "battery": 100},
    },
    {
        "device_id": "DEV-002",
        "timestamp": "2026-01-15T14:30:00Z",
        "readings": {"temperature": 68.0, "humidity": 45, "connectivity": 12, "battery": 72},
    },
    {
        "device_id": "DEV-003",
        "timestamp": "2026-01-15T14:30:00Z",
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


def clean_response(text: str) -> str:
    """Strip Nova/Claude thinking tags from agent responses."""
    cleaned = re.sub(r'<thinking>.*?</thinking>', '', str(text), flags=re.DOTALL)
    return cleaned.strip()


def run_agent_with_retry(agent_builder, prompt: str, max_retries: int = 3) -> str:
    """Run an agent with retry logic for transient Bedrock errors.
    Uses exponential backoff (1s, 2s, 4s) to handle throttling."""
    for attempt in range(max_retries):
        try:
            agent = agent_builder()
            result = agent(prompt)
            return clean_response(result)
        except Exception as e:
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                print(f"    [Retry {attempt + 1}/{max_retries}] {e.__class__.__name__}, waiting {wait}s...")
                time.sleep(wait)
            else:
                print(f"    [Failed] {e.__class__.__name__} after {max_retries} attempts")
                raise


# ═══════════════════════════════════════════════════════
#  AGENT 1: DEVICE MONITOR
#  Single responsibility: read sensor data for a device
# ═══════════════════════════════════════════════════════

def build_device_monitor() -> Agent:
    """Build the Device Monitor agent with a read_sensor_data tool."""

    model = BedrockModel(
        model_id=MODEL_ID,
        region_name=AWS_REGION,
        temperature=0.0,
    )

    @tool
    def read_sensor_data(device_id: str) -> str:
        """Read the latest sensor data for a device.

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

    system_prompt = """You are a Device Monitor agent. Your ONLY job is reading sensor data.
Call the read_sensor_data tool with the device_id.
After the tool returns, output ONLY the raw JSON result. Do not diagnose issues or send commands."""

    return Agent(
        model=model,
        system_prompt=system_prompt,
        tools=[read_sensor_data],
    )


# ═══════════════════════════════════════════════════════
#  AGENT 2: DIAGNOSTICS AGENT
#  Single responsibility: identify issues from sensor data
# ═══════════════════════════════════════════════════════

def build_diagnostics_agent() -> Agent:
    """Build the Diagnostics agent with a diagnose_issue tool."""

    model = BedrockModel(
        model_id=MODEL_ID,
        region_name=AWS_REGION,
        temperature=0.0,
    )

    @tool
    def diagnose_issue(sensor_data_json: str) -> str:
        """Apply diagnostic rules to sensor readings to identify issues.

        Rules:
        - temperature > 85 = overheating
        - connectivity < 20 = firmware_issue
        - battery < 10 = low_battery

        Args:
            sensor_data_json: JSON string from the Device Monitor

        Returns:
            JSON string with device_id, issues found, and status
        """
        data = {}
        readings = {}
        try:
            data = json.loads(sensor_data_json)
            readings = data.get("readings", {})
        except (json.JSONDecodeError, AttributeError, TypeError):
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

    system_prompt = """You are a Diagnostics agent. Your ONLY job is diagnosing device issues.
You will receive sensor data JSON. Call the diagnose_issue tool with that JSON.
After the tool returns, output ONLY the raw JSON result. Do not read sensors or send commands."""

    return Agent(
        model=model,
        system_prompt=system_prompt,
        tools=[diagnose_issue],
    )


# ═══════════════════════════════════════════════════════
#  AGENT 3: COMMAND AGENT
#  Single responsibility: send corrective commands
# ═══════════════════════════════════════════════════════

def build_command_agent() -> Agent:
    """Build the Command agent with a send_device_command tool."""

    model = BedrockModel(
        model_id=MODEL_ID,
        region_name=AWS_REGION,
        temperature=0.0,
    )

    @tool
    def send_device_command(device_id: str, issue_type: str) -> str:
        """Send a corrective command to a device based on the diagnosed issue.

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

    system_prompt = """You are a Command agent. Your ONLY job is sending corrective commands to devices.
You will receive a device_id and issue_type. Call the send_device_command tool with those values.
After the tool returns, output ONLY the raw JSON result. Do not read sensors or diagnose issues."""

    return Agent(
        model=model,
        system_prompt=system_prompt,
        tools=[send_device_command],
    )


# ═══════════════════════════════════════════════════════
#  COORDINATOR — Wires the 3 agents together
#  Calls each in sequence: Monitor → Diagnostics → Command
# ═══════════════════════════════════════════════════════

def run_device_pipeline(device_id: str) -> dict:
    """Run the 3-agent device management pipeline.

    Flow: DeviceMonitor → DiagnosticsAgent → CommandAgent

    Each agent is instantiated fresh to avoid context bleed between devices.
    The coordinator passes the output of one agent as input to the next.
    """

    # Agent 1: Device Monitor — read sensor data
    print("    [1/3] Device Monitor...")
    monitor_result = run_agent_with_retry(
        build_device_monitor,
        f"Read sensor data for device_id={device_id}"
    )
    try:
        sensor_json = json.loads(monitor_result)
        sensor_str = json.dumps(sensor_json)
    except (json.JSONDecodeError, TypeError):
        json_match = re.search(r'\{[\s\S]*\}', str(monitor_result))
        sensor_str = json_match.group(0) if json_match else str(monitor_result)
        try:
            sensor_json = json.loads(sensor_str)
        except Exception:
            sensor_json = {"raw": sensor_str}
    print(f"          Device: {sensor_json.get('device_name', '?')}")

    # Agent 2: Diagnostics — identify issues from sensor data
    print("    [2/3] Diagnostics Agent...")
    diag_result = run_agent_with_retry(
        build_diagnostics_agent,
        f"Diagnose issues from this sensor data: {sensor_str}"
    )
    try:
        diag_json = json.loads(diag_result)
        diag_str = json.dumps(diag_json)
    except (json.JSONDecodeError, TypeError):
        json_match = re.search(r'\{[\s\S]*\}', str(diag_result))
        diag_str = json_match.group(0) if json_match else str(diag_result)
        try:
            diag_json = json.loads(diag_str)
        except Exception:
            diag_json = {"raw": diag_str}
    issues = diag_json.get("issues", [])
    print(f"          Issues: {len(issues)} found")

    # Agent 3: Command — send corrective actions for each issue
    commands = []
    if issues:
        for issue in issues:
            issue_type = issue.get("issue", "unknown")
            print(f"    [3/3] Command Agent ({issue_type})...")
            cmd_result = run_agent_with_retry(
                build_command_agent,
                f"Send command for device_id={device_id} with issue_type={issue_type}"
            )
            try:
                cmd_json = json.loads(cmd_result)
            except (json.JSONDecodeError, TypeError):
                json_match = re.search(r'\{[\s\S]*\}', str(cmd_result))
                if json_match:
                    try:
                        cmd_json = json.loads(json_match.group(0))
                    except Exception:
                        cmd_json = {"raw": str(cmd_result)}
                else:
                    cmd_json = {"raw": str(cmd_result)}
            commands.append(cmd_json)
            print(f"          Action: {cmd_json.get('action', '?')}")
    else:
        print("    [3/3] Command Agent — skipped (device healthy)")

    return {
        "device_id": device_id,
        "sensor_data": sensor_json,
        "diagnosis": diag_json,
        "commands": commands,
    }


# ═══════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("  Smart Home Device Management — Module 1 Exercise")
    print("  3-Agent Architecture: Monitor → Diagnostics → Command")
    print("=" * 70)

    test_scenarios = [
        {"device_id": "DEV-001", "expected": "overheating",    "desc": "Thermostat at 92.5°F"},
        {"device_id": "DEV-002", "expected": "firmware_issue",  "desc": "Smart lock at 12% connectivity"},
        {"device_id": "DEV-003", "expected": "low_battery",     "desc": "Doorbell camera at 7% battery"},
    ]

    for s in test_scenarios:
        print(f"\n{'─' * 70}")
        print(f"  Scenario: {s['desc']}")
        print(f"  Device: {s['device_id']} | Expected: {s['expected']}")
        print(f"{'─' * 70}")

        result = run_device_pipeline(s["device_id"])

        print(f"\n  Summary:")
        print(f"    Device: {result['sensor_data'].get('device_name', '?')}")
        print(f"    Status: {result['diagnosis'].get('status', '?')}")
        issues = result['diagnosis'].get('issues', [])
        if issues:
            for issue in issues:
                print(f"    Issue: {issue.get('issue', '?')} ({issue.get('field', '?')}={issue.get('value', '?')})")
        for cmd in result['commands']:
            print(f"    Action: {cmd.get('action', '?')} — {cmd.get('message', '')}")


if __name__ == "__main__":
    main()
