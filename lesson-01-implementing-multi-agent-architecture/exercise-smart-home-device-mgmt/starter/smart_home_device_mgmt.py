"""
smart_home_device_mgmt.py - STARTER
======================================
Module 1 Exercise: Build a 3-Agent Smart Home Device Management System

Follow the same multi-agent coordinator pattern from the demo:
  - 3 separate Agent instances (DeviceMonitor, DiagnosticsAgent, CommandAgent)
  - Each agent has its own model, system prompt, and tool
  - A coordinator calls them in sequence, passing outputs forward

You have 6 TODOs to complete:
  TODO 1: Build the Device Monitor agent (model + prompt + tool)
  TODO 2: Build the Diagnostics agent (model + prompt + tool)
  TODO 3: Build the Command agent (model + prompt + tool)
  TODO 4: Coordinator step 1 — call Device Monitor
  TODO 5: Coordinator step 2 — call Diagnostics Agent
  TODO 6: Coordinator step 3 — call Command Agent for each issue

Architecture:
    Sensor Data → DeviceMonitor → DiagnosticsAgent → CommandAgent → Action Report

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
# SAMPLE DATA — Pre-written, do not modify.
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


# NOTE: In production, extract shared helpers like run_agent_with_retry() and
# clean_response() to a common utils.py module to avoid code duplication.
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
#  TOOL IMPLEMENTATIONS — Pre-written, do not modify.
#  You will use these tools inside your agent builders.
# ═══════════════════════════════════════════════════════

def _make_read_sensor_data_tool():
    """Returns the read_sensor_data tool for the Device Monitor agent."""
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
    return read_sensor_data


def _make_diagnose_issue_tool():
    """Returns the diagnose_issue tool for the Diagnostics agent."""
    @tool
    def diagnose_issue(sensor_data_json: str) -> str:
        """Apply diagnostic rules to sensor readings to identify issues.

        Rules: temperature > 85 = overheating, connectivity < 20 = firmware_issue, battery < 10 = low_battery

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
    return diagnose_issue


def _make_send_device_command_tool():
    """Returns the send_device_command tool for the Command agent."""
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
    return send_device_command


# ═══════════════════════════════════════════════════════
#  TODO 1: BUILD THE DEVICE MONITOR AGENT
#  Follow the 3-step pattern from the demo's build_symptom_analyzer():
#  model → system_prompt → Agent
# ═══════════════════════════════════════════════════════

def build_device_monitor() -> Agent:
    """Build the Device Monitor agent with a read_sensor_data tool."""
    # --- YOUR CODE HERE ---
    pass


# ═══════════════════════════════════════════════════════
#  TODO 2: BUILD THE DIAGNOSTICS AGENT
#  Follow the 3-step pattern from the demo's build_urgency_classifier():
#  model → system_prompt → Agent
# ═══════════════════════════════════════════════════════

def build_diagnostics_agent() -> Agent:
    """Build the Diagnostics agent with a diagnose_issue tool."""
    # --- YOUR CODE HERE ---
    pass


# ═══════════════════════════════════════════════════════
#  TODO 3: BUILD THE COMMAND AGENT
#  Build the Command Agent following the same pattern as TODOs 1-2.
# ═══════════════════════════════════════════════════════

def build_command_agent() -> Agent:
    """Build the Command agent with a send_device_command tool."""
    # --- YOUR CODE HERE ---
    pass


# ═══════════════════════════════════════════════════════
#  COORDINATOR — Wire the 3 agents together
#  Complete TODOs 4-6 to call each agent in sequence.
# ═══════════════════════════════════════════════════════

def run_device_pipeline(device_id: str) -> dict:
    """Run the 3-agent device management pipeline.

    Flow: DeviceMonitor → DiagnosticsAgent → CommandAgent
    """

    # TODO 4: Call the Device Monitor agent
    #   - Use run_agent_with_retry(build_device_monitor, prompt)
    #   - Parse the JSON response to get sensor data
    #   - Print the device name
    #   Hint: prompt should ask to read sensor data for the device_id
    print("    [1/3] Device Monitor...")
    # --- YOUR CODE HERE ---
    sensor_json = {}
    sensor_str = "{}"

    # TODO 5: Call the Diagnostics Agent
    #   - Use run_agent_with_retry(build_diagnostics_agent, prompt)
    #   - Pass the sensor_str from TODO 4 in the prompt
    #   - Parse the JSON response to get diagnosis
    #   - Extract the list of issues
    print("    [2/3] Diagnostics Agent...")
    # --- YOUR CODE HERE ---
    diag_json = {}
    issues = []

    # TODO 6: Call the Command Agent for each issue
    #   - Loop through the issues list from TODO 5
    #   - For each issue, call run_agent_with_retry(build_command_agent, prompt)
    #   - Pass device_id and issue_type in the prompt
    #   - If no issues, print "skipped (device healthy)"
    commands = []
    if issues:
        for issue in issues:
            issue_type = issue.get("issue", "unknown")
            print(f"    [3/3] Command Agent ({issue_type})...")
            # --- YOUR CODE HERE ---
    else:
        print("    [3/3] Command Agent — skipped (device healthy)")

    return {
        "device_id": device_id,
        "sensor_data": sensor_json,
        "diagnosis": diag_json,
        "commands": commands,
    }


# ═══════════════════════════════════════════════════════
#  MAIN — Pre-written, do not modify.
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
