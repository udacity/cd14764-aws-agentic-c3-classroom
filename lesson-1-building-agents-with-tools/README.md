# Lesson 1: Building Agents with Tools

This lesson covers the fundamentals of the Strands Agents SDK: Agent class, @tool decorator, BedrockModel, and system prompts.

## Folder Structure

```
lesson-1-building-agents-with-tools/
├── README.md
├── demo-healthcare-triage/
│   └── solution/
│       ├── README.md
│       └── healthcare_triage.py
└── exercise-smart-home-device-mgmt/
    ├── solution/
    │   ├── README.md
    │   └── smart_home_device_mgmt.py
    └── starter/
        ├── README.md
        └── smart_home_device_mgmt.py
```

## Demo: Healthcare Triage System (Instructor-led)
- **Domain:** Healthcare
- **Architecture:** 1 Agent with 3 tools (lookup_symptoms -> classify_urgency -> book_appointment)
- **Test cases:** Alice (chest pain -> urgent), Bob (headache -> routine), Carol (ankle -> standard)

## Exercise: Smart Home Device Management (Student-led)
- **Domain:** IoT / Smart Home
- **Architecture:** 1 Agent with 3 tools (read_sensor_data -> diagnose_issue -> send_device_command)
- **Test cases:** DEV-001 (overheating -> restart), DEV-002 (firmware_issue -> update), DEV-003 (low_battery -> notify)
