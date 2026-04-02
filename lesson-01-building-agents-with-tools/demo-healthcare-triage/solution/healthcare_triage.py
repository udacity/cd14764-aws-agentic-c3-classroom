"""
healthcare_triage.py - SOLUTION
================================
Module 1 Demo: Building a Healthcare Triage System with Strands Agents SDK

Architecture:
    Patient Complaint
          │
    TriageAgent (single agent with 3 specialized tools)
          │
    ┌─────┼──────────────────┐
    │     │                  │
lookup_symptoms  classify_urgency  book_appointment
(symptoms→conditions) (condition→priority) (priority→time slot)

Each tool has a single responsibility. The agent calls them in sequence,
passing the output of one tool as input to the next.

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


# ═══════════════════════════════════════════════════════
#  TRIAGE AGENT — 1 Agent with 3 specialized tools
# ═══════════════════════════════════════════════════════

def build_triage_agent() -> Agent:
    """
    Build the Triage Agent with three specialized tools.

    Each tool handles one step of the triage pipeline:
    1. lookup_symptoms — maps complaint text to conditions
    2. classify_urgency — assigns priority from symptom JSON
    3. book_appointment — reserves a slot based on urgency
    """

    # STEP 1: Create the model
    # - BedrockModel wraps Amazon Bedrock's Converse API
    # - temperature=0.0 makes output deterministic (no randomness)
    model = BedrockModel(
        model_id=MODEL_ID,
        region_name=AWS_REGION,
        temperature=0.0,
    )

    # STEP 2: Write the system prompt
    # - This controls HOW the agent uses its tools
    # - Be explicit about tool calling order and data passing
    # - Without strict instructions, the LLM may skip tools or add unwanted commentary
    system_prompt = """You are a healthcare triage agent. For each patient, call these 3 tools in EXACT order:

1. lookup_symptoms — pass the patient's complaint text
2. classify_urgency — pass the EXACT JSON string returned by lookup_symptoms
3. book_appointment — pass the patient_id AND the "urgency" value from classify_urgency's JSON output

CRITICAL RULES:
- When calling classify_urgency, pass the raw JSON from lookup_symptoms as-is
- When calling book_appointment, extract the "urgency" field from classify_urgency's JSON (it will be "urgent", "standard", or "routine") and pass that as urgency_level
- After all 3 tools complete, write a 3-line summary: symptoms, urgency, appointment"""

    # ─── TOOL 1: Symptom Analysis ───

    @tool
    def lookup_symptoms(complaint_text: str) -> str:
        """
        Parse a patient complaint and match symptoms against the knowledge base.

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

        return json.dumps({
            "matched_symptoms": matches,
            "total_matches": len(matches),
        }, indent=2)

    # ─── TOOL 2: Urgency Classification ───

    @tool
    def classify_urgency(symptom_json: str) -> str:
        """
        Classify triage urgency based on symptom analysis results.

        Rules:
        - If ANY severity is "high" → urgency = "urgent"
        - If ANY severity is "medium" (none high) → urgency = "standard"
        - If all severities are "low" → urgency = "routine"

        Args:
            symptom_json: The JSON string returned by lookup_symptoms

        Returns:
            JSON string with urgency level (urgent/standard/routine) and reasoning
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

        return json.dumps({
            "urgency": urgency,
            "reason": reason,
            "severity_breakdown": severities,
        }, indent=2)

    # ─── TOOL 3: Appointment Scheduling ───

    @tool
    def book_appointment(patient_id: str, urgency_level: str) -> str:
        """
        Book an appointment slot based on urgency level.

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

        return json.dumps({
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

    # STEP 3: Build the Agent
    # - Bind the model, system prompt, and tools together
    # - The agent will use the LLM to decide when/how to call each tool
    return Agent(
        model=model,
        system_prompt=system_prompt,
        tools=[lookup_symptoms, classify_urgency, book_appointment],
    )


# ═══════════════════════════════════════════════════════
#  MAIN — Run the triage system
# ═══════════════════════════════════════════════════════

def main():
    """Run the healthcare triage system with sample patient complaints."""

    print("=" * 60)
    print("  Healthcare Triage System — Module 1 Demo")
    print("  Strands Agents SDK: Agent + @tool + BedrockModel")
    print("=" * 60)

    for patient in PATIENT_COMPLAINTS:
        print(f"\n{'─' * 60}")
        print(f"  Patient: {patient['name']} ({patient['patient_id']})")
        print(f"  Complaint: {patient['complaint'][:80]}...")
        print(f"{'─' * 60}")

        # KEY PATTERN: Fresh agent per test case to avoid context accumulation
        # If you reuse one agent across patients, the 3rd+ patient gets
        # confused by prior conversation history and may loop or repeat.
        triage_agent = build_triage_agent()

        prompt = (
            f"Triage this patient:\n"
            f"Patient ID: {patient['patient_id']}\n"
            f"Name: {patient['name']}\n"
            f"Age: {patient['age']}\n"
            f"Complaint: {patient['complaint']}"
        )

        response = triage_agent(prompt)
        print(f"\n  Result:\n  {response}\n")


if __name__ == "__main__":
    main()
