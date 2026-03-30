# Exercise: Parallel Contract Compliance — Starter

## File
- `contract_compliance.py` — Starter code with 12 TODOs to complete

## Your Task
Complete 4 build functions, each with 3 TODOs (12 TODOs total):

### build_regulatory_agent() — Specialist 1
- **TODO 1**: Create BedrockModel with Nova Lite (temperature=0.0)
- **TODO 2**: Write system prompt for regulatory compliance review
- **TODO 3**: Build Agent with model, prompt, and check_regulatory tool

### build_financial_agent() — Specialist 2
- **TODO 4**: Create BedrockModel with Claude (temperature=0.1)
- **TODO 5**: Write system prompt for financial risk assessment
- **TODO 6**: Build Agent with model, prompt, and assess_financial_risk tool

### build_ip_agent() — Specialist 3
- **TODO 7**: Create BedrockModel with Nova Pro (temperature=0.1)
- **TODO 8**: Write system prompt for IP protection review
- **TODO 9**: Build Agent with model, prompt, and review_ip_clauses tool

### build_synthesizer_agent() — Synthesizer (NEW in Module 3)
- **TODO 10**: Create BedrockModel with Claude (temperature=0.2)
- **TODO 11**: Write system prompt for compliance synthesis
- **TODO 12**: Build Agent with model, prompt, and synthesize_compliance tool

## What's Pre-Written
- All 4 tools (check_regulatory, assess_financial_risk, review_ip_clauses, synthesize_compliance)
- Sample contract data and pre-analyzed findings
- Parallel execution engine (ThreadPoolExecutor)
- Main function with reporting and performance comparison

## Pattern Reference
Follow the same 3 steps shown in the demo (`document_analysis.py`):
- STEP 1 → BedrockModel  |  STEP 2 → System Prompt  |  STEP 3 → Agent

## How to Run
```bash
python contract_compliance.py
```
