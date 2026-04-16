"""
healthcare_triage.py
====================
Module 1 Demo: Building a 3-Agent Healthcare Triage System

Architecture:
    Patient Complaint
          │
    ┌─────▼──────┐
    │ Coordinator │  (orchestrates the 3 worker agents)
    └──┬───┬───┬─┘
       │   │   │
       ▼   │   │
 ┌──────────┐  │   │
 │ Symptom   │  │   │   Agent 1: Maps complaint → conditions
 │ Analyzer  │──┘   │
 └──────────┘       │
       │            │
       ▼            │
 ┌──────────┐       │
 │ Urgency   │      │   Agent 2: Maps conditions → priority
 │Classifier │──────┘
 └──────────┘
       │
       ▼
 ┌──────────┐
 │Appointment│           Agent 3: Maps priority → time slot
 │ Scheduler │
 └──────────┘
       │
       ▼
    Triage Result

Key Pattern: Each agent is a separate Agent instance with its own model,
system prompt, and tools. The coordinator invokes worker agents as tool
calls, passing context as function arguments. This enforces single-responsibility:
SymptomAnalyzer never schedules, AppointmentScheduler never diagnoses.

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
# SAMPLE DATA — Patient complaints and available slots
# ─────────────────────────────────────────────────────
PATIENT_COMPLAINTS = [
    {
        "patient_id": "P-1001",
        "name": "Alice Johnson",
        "complaint": "I've been having sharp chest pain for the past 2 hours, "
                     "along with shortness of breath and dizziness.",
        "age": 58,
    },
    {
        "patient_id": "P-1002",
        "name": "Bob Smith",
        "complaint": "I have a mild headache and a runny nose that started yesterday. "
                     "No fever.",
        "age": 32,
    },
    {
        "patient_id": "P-1003",
        "name": "Carol Davis",
        "complaint": "My ankle is swollen and painful after I twisted it while jogging "
                     "this morning. I can still put some weight on it.",
        "age": 27,
    },
]

AVAILABLE_SLOTS = {
    "urgent":   ["09:00 AM (Emergency)", "09:15 AM (Emergency)"],
    "standard": ["10:30 AM", "11:00 AM", "11:30 AM"],
    "routine":  ["02:00 PM", "02:30 PM", "03:00 PM", "03:30 PM"],
}

# ─────────────────────────────────────────────────────
# SYMPTOM KNOWLEDGE BASE (simulated)
# ─────────────────────────────────────────────────────
SYMPTOM_CONDITIONS = {
    "chest pain":          {"condition": "Possible cardiac event", "severity": "high",   "keywords": ["chest pain", "chest"]},
    "shortness of breath": {"condition": "Respiratory distress",   "severity": "high",   "keywords": ["shortness of breath", "breathing", "breath"]},
    "dizziness":           {"condition": "Circulatory issue",      "severity": "medium", "keywords": ["dizziness", "dizzy", "lightheaded"]},
    "headache":            {"condition": "Tension headache",       "severity": "low",    "keywords": ["headache", "head pain"]},
    "runny nose":          {"condition": "Upper respiratory infection", "severity": "low", "keywords": ["runny nose", "congestion", "nasal"]},
    "swollen ankle":       {"condition": "Possible sprain",        "severity": "medium", "keywords": ["swollen", "ankle", "twisted", "sprain"]},
}


def clean_response(text: str) -> str:
    """Strip Nova/Claude thinking tags from agent responses."""
    cleaned = re.sub(r'<thinking>.*?</thinking>', '', str(text), flags=re.DOTALL)
    return cleaned.strip()


# Shared dict for capturing tool results directly.
# Why: LLMs may rephrase or modify tool output in their text response,
# so we capture the raw tool result here for reliable downstream use.
_tool_results = {}


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
#  STEP 1: SYMPTOM ANALYZER AGENT
#  Single responsibility: map complaint text → conditions
# ═══════════════════════════════════════════════════════

def build_symptom_analyzer() -> Agent:
    """Build the Symptom Analyzer agent with a lookup_symptoms tool."""

    model = BedrockModel(
        model_id=MODEL_ID,
        region_name=AWS_REGION,
        temperature=0.0,
    )

    @tool
    def lookup_symptoms(complaint_text: str) -> str:
        """Parse a patient complaint and match symptoms against the knowledge base.

        Args:
            complaint_text: The raw patient complaint text

        Returns:
            JSON string with matched symptoms, conditions, and severity levels
        """
        complaint_lower = complaint_text.lower()
        matches = []
        for symptom, info in SYMPTOM_CONDITIONS.items():
            if any(kw in complaint_lower for kw in info["keywords"]):
                matches.append({
                    "symptom": symptom,
                    "condition": info["condition"],
                    "severity": info["severity"],
                })
        result = json.dumps({
            "matched_symptoms": matches,
            "total_matches": len(matches),
        }, indent=2)
        _tool_results["symptoms"] = result  # Capture for coordinator
        return result

    system_prompt = """You are a Symptom Analyzer agent. Your ONLY job is symptom analysis.
Call the lookup_symptoms tool with the patient's complaint text.
After the tool returns, output ONLY the raw JSON result. Do not classify urgency or book appointments."""

    return Agent(
        model=model,
        system_prompt=system_prompt,
        tools=[lookup_symptoms],
    )


# ═══════════════════════════════════════════════════════
#  STEP 2: URGENCY CLASSIFIER AGENT
#  Single responsibility: map symptom data → urgency level
# ═══════════════════════════════════════════════════════

def build_urgency_classifier() -> Agent:
    """Build the Urgency Classifier agent with a classify_urgency tool."""

    model = BedrockModel(
        model_id=MODEL_ID,
        region_name=AWS_REGION,
        temperature=0.0,
    )

    @tool
    def classify_urgency(symptom_json: str) -> str:
        """Classify triage urgency based on symptom analysis results.

        Rules:
        - If ANY severity is "high" → urgency = "urgent"
        - If ANY severity is "medium" (none high) → urgency = "standard"
        - If all severities are "low" → urgency = "routine"

        Args:
            symptom_json: JSON string from the Symptom Analyzer

        Returns:
            JSON string with urgency level and reasoning
        """
        severities = []
        try:
            data = json.loads(symptom_json)
            symptoms = data.get("matched_symptoms", [])
            severities = [s.get("severity", "low") for s in symptoms]
        except (json.JSONDecodeError, AttributeError, TypeError):
            text_lower = symptom_json.lower()
            if "high" in text_lower:
                severities.append("high")
            if "medium" in text_lower:
                severities.append("medium")
            if "low" in text_lower:
                severities.append("low")
            if not severities:
                severities.append("low")

        if "high" in severities:
            urgency = "urgent"
            reason = "High-severity symptoms detected — possible cardiac or respiratory event"
        elif "medium" in severities:
            urgency = "standard"
            reason = "Medium-severity symptoms — requires same-day attention"
        else:
            urgency = "routine"
            reason = "Low-severity symptoms — suitable for routine appointment"

        result = json.dumps({
            "urgency": urgency,
            "reason": reason,
            "severity_breakdown": severities,
        }, indent=2)
        _tool_results["urgency"] = result  # Capture for coordinator
        return result

    system_prompt = """You are an Urgency Classifier agent. Your ONLY job is urgency classification.
You will receive symptom analysis JSON. Call the classify_urgency tool with that JSON.
After the tool returns, output ONLY the raw JSON result. Do not analyze symptoms or book appointments."""

    return Agent(
        model=model,
        system_prompt=system_prompt,
        tools=[classify_urgency],
    )


# ═══════════════════════════════════════════════════════
#  STEP 3: APPOINTMENT SCHEDULER AGENT
#  Single responsibility: map urgency level → time slot
# ═══════════════════════════════════════════════════════

def build_appointment_scheduler() -> Agent:
    """Build the Appointment Scheduler agent with a book_appointment tool."""

    model = BedrockModel(
        model_id=MODEL_ID,
        region_name=AWS_REGION,
        temperature=0.0,
    )

    @tool
    def book_appointment(patient_id: str, urgency_level: str) -> str:
        """Book an appointment slot based on urgency level.

        Args:
            patient_id: The patient's unique identifier
            urgency_level: One of "urgent", "standard", or "routine"

        Returns:
            JSON string with booking confirmation and assigned time slot
        """
        urgency_key = urgency_level.lower().strip()
        slots = AVAILABLE_SLOTS.get(urgency_key, AVAILABLE_SLOTS["routine"])
        if not slots:
            return json.dumps({
                "status": "no_availability",
                "message": f"No {urgency_key} slots available.",
            })
        assigned_slot = slots[0]
        today = datetime.now().strftime("%Y-%m-%d")
        result = json.dumps({
            "status": "booked",
            "patient_id": patient_id,
            "date": today,
            "time_slot": assigned_slot,
            "urgency": urgency_key,
            "instructions": {
                "urgent": "Proceed to emergency intake immediately.",
                "standard": "Please arrive 15 minutes early for intake.",
                "routine": "Please arrive 10 minutes before your appointment.",
            }.get(urgency_key, "Please arrive on time."),
        }, indent=2)
        _tool_results["booking"] = result  # Capture for coordinator
        return result

    system_prompt = """You are an Appointment Scheduler agent. Your ONLY job is booking appointments.
You will receive a patient_id and urgency_level. Call the book_appointment tool with those values.
After the tool returns, output ONLY the raw JSON result. Do not analyze symptoms or classify urgency."""

    return Agent(
        model=model,
        system_prompt=system_prompt,
        tools=[book_appointment],
    )


# ═══════════════════════════════════════════════════════
#  STEP 4: COORDINATOR — Wires the 3 agents together
#  Calls each agent in sequence, passing outputs forward
# ═══════════════════════════════════════════════════════

def run_triage_pipeline(patient: dict) -> dict:
    """Run the 3-agent triage pipeline for a single patient.

    Flow: SymptomAnalyzer → UrgencyClassifier → AppointmentScheduler

    Each agent is instantiated fresh to avoid context bleed between patients.
    The coordinator passes the output of one agent as input to the next.
    """

    # STEP 4.1: Symptom Analyzer — extract conditions from complaint
    print("    [1/3] Symptom Analyzer...")
    _tool_results.clear()  # Reset between patients to avoid stale data
    run_agent_with_retry(
        build_symptom_analyzer,
        f"Analyze these symptoms: {patient['complaint']}"
    )
    # Use captured tool result (reliable) instead of parsing LLM text (fragile)
    symptom_json = json.loads(_tool_results.get("symptoms", '{"total_matches": 0}'))
    symptom_str = json.dumps(symptom_json)
    print(f"          Matched {symptom_json.get('total_matches', 0)} symptoms")

    # STEP 4.2: Urgency Classifier — determine priority from symptoms
    print("    [2/3] Urgency Classifier...")
    run_agent_with_retry(
        build_urgency_classifier,
        f"Classify urgency for this symptom analysis: {symptom_str}"
    )
    urgency_json = json.loads(_tool_results.get("urgency", '{"urgency": "routine"}'))
    urgency_level = urgency_json.get("urgency", "routine")
    print(f"          Urgency: {urgency_level}")

    # STEP 4.3: Appointment Scheduler — book slot based on urgency
    print("    [3/3] Appointment Scheduler...")
    run_agent_with_retry(
        build_appointment_scheduler,
        f"Book an appointment for patient_id={patient['patient_id']} with urgency_level={urgency_level}"
    )
    booking_json = json.loads(_tool_results.get("booking", '{"status": "failed"}'))
    print(f"          Slot: {booking_json.get('time_slot', 'N/A')}")

    return {
        "patient": patient["name"],
        "symptoms": symptom_json,
        "urgency": urgency_json,
        "booking": booking_json,
    }


# ═══════════════════════════════════════════════════════
#  STEP 5: MAIN — Run the triage system
# ═══════════════════════════════════════════════════════

def main():
    """Run the 3-agent healthcare triage system with sample patient complaints."""

    print("=" * 70)
    print("  Healthcare Triage System — Module 1 Demo")
    print("  3-Agent Architecture: Analyzer → Classifier → Scheduler")
    print("=" * 70)

    for patient in PATIENT_COMPLAINTS:
        print(f"\n{'─' * 70}")
        print(f"  Patient: {patient['name']} ({patient['patient_id']}, age {patient['age']})")
        print(f"  Complaint: {patient['complaint']}")
        print(f"{'─' * 70}")

        result = run_triage_pipeline(patient)

        print(f"\n  Summary:")
        print(f"    Symptoms found: {result['symptoms'].get('total_matches', '?')}")
        print(f"    Urgency: {result['urgency'].get('urgency', '?')} — {result['urgency'].get('reason', '')}")
        print(f"    Appointment: {result['booking'].get('time_slot', 'N/A')} ({result['booking'].get('status', '?')})")
        print(f"    Instructions: {result['booking'].get('instructions', 'N/A')}")


if __name__ == "__main__":
    main()
