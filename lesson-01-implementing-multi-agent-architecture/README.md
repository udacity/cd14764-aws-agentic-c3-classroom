# Lesson 1: Implementing Multi-Agent Architecture

This lesson covers building multi-agent systems with the Strands Agents SDK: separate Agent instances with single responsibilities, inter-agent communication through a coordinator, and the Agent class, @tool decorator, and BedrockModel.

## Folder Structure

```
lesson-01-implementing-multi-agent-architecture/
├── README.md
├── demo-healthcare-triage/
│   ├── README.md
│   ├── architecture.svg
│   └── healthcare_triage.py
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
- **Architecture:** 3 Agents (SymptomAnalyzer → UrgencyClassifier → AppointmentScheduler) + Coordinator
- **Pattern:** Each agent has its own model, system prompt, and tool. Coordinator calls them in sequence.
- **Test cases:** Alice (chest pain → urgent), Bob (headache → routine), Carol (ankle → standard)

## Exercise: Smart Home Device Management (Student-led)
- **Domain:** IoT / Smart Home
- **Architecture:** 3 Agents (DeviceMonitor → DiagnosticsAgent → CommandAgent) + Coordinator
- **Pattern:** Same multi-agent coordinator pattern as demo
- **Test cases:** DEV-001 (overheating → restart), DEV-002 (firmware_issue → update), DEV-003 (low_battery → notify)
