# Lesson 3: Implementing Agentic Parallelization Workflows

This lesson teaches how to run multiple independent specialist agents in parallel using Python's `ThreadPoolExecutor`, then combine their findings with a SynthesizerAgent.

## Folder Structure

```
lesson-03-implementing-agentic-parallelization-workflows/
├── README.md
├── demo-parallel-document-analysis/
│   ├── README.md
│   └── document_analysis.py
└── exercise-contract-compliance/
    ├── solution/
    │   ├── README.md
    │   └── contract_compliance.py
    └── starter/
        ├── README.md
        └── contract_compliance.py
```

## Demo: Parallel Document Analysis with Specialist Agents (Instructor-led)
- **Domain:** System Design Review
- **Architecture:** 3 specialists (parallel) + 1 synthesizer — SecurityReviewer (Nova Lite), ScalabilityReviewer (Claude), CostReviewer (Nova Pro), SynthesizerAgent (Claude)
- **Test cases:** DOC-001 (e-commerce platform → BLOCK), DOC-002 (HR portal → APPROVE)
- **Key insight:** ThreadPoolExecutor gives ~3x speedup when agents are independent

## Exercise: Parallel Contract Compliance Analysis (Student-led)
- **Domain:** Legal / Contract Review
- **Architecture:** 3 specialists (parallel) + 1 synthesizer — RegulatoryComplianceAgent (Nova Lite), FinancialRiskAgent (Claude), IPProtectionAgent (Nova Pro), SynthesizerAgent (Claude)
- **Test cases:** CONTRACT-001 (clean vendor agreement → APPROVE), CONTRACT-002 (risky outsourcing → REJECT)
- **Key insight:** Regulatory, financial, and IP concerns are orthogonal — natural fit for parallelization
