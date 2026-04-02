# Exercise Solution: VectraBank Deployment Architecture

## Overview
This exercise creates a production deployment plan for VectraBank's financial services multi-agent system. Same planning pattern as the demo, with additions: VPC network mode, operational runbooks, stricter compliance thresholds, and a 4-agent architecture preview.

## Architecture Plan
- **4 agents:** QueryRouter, MarketDataRetriever, ComplianceRetriever, FinancialAdvisor
- **3 Knowledge Bases:** Market Data, Compliance/Regulations, Financial Products
- **VPC network mode:** Financial services stay internal
- **Operational runbook (NEW):** 4 procedures for deploy, rollback, kill switch, latency

## Running
```bash
python vectrabank_architecture.py
```

## Key Differences from Demo
- **VPC network mode** — financial services = internal only (vs PUBLIC in demo)
- **Operational runbook** — NEW: 4 step-by-step incident procedures
- **Stricter thresholds** — 2% error rate, 10% X-Ray sampling for audit
- **4 agents** — router + 2 retrievers + synthesizer (capstone preview)
