# Demo: Parallel Document Analysis — Solution

## File
- `document_analysis.py` — Complete parallel document analysis system

## What This Demonstrates
- **3 specialist agents** reviewing a system design document in parallel
- **SynthesizerAgent** combining findings into a unified launch-readiness assessment
- **ThreadPoolExecutor** for parallel execution of independent agents
- **Performance comparison** between parallel and sequential execution
- **Shared caches** for passing data from specialists to synthesizer

## Architecture
| Agent | Model | Role | Temperature |
|-------|-------|------|-------------|
| SecurityReviewer | Nova Lite | Vulnerabilities, auth, encryption | 0.0 |
| ScalabilityReviewer | Claude 3 Sonnet | Bottlenecks, auto-scaling, SPOFs | 0.1 |
| CostReviewer | Nova Pro | Infrastructure costs, optimization | 0.1 |
| SynthesizerAgent | Claude 3 Sonnet | Combines findings → launch decision | 0.2 |

## Execution Flow
1. **Parallel phase**: All 3 specialists run simultaneously via ThreadPoolExecutor
2. **Synthesis phase**: SynthesizerAgent reads all specialist caches, produces unified report
3. **Comparison**: Same analysis runs sequentially to demonstrate speedup

## How to Run
```bash
python document_analysis.py
```

## Expected Output
- 2 documents analyzed (e-commerce platform + internal HR portal)
- Each gets a unified launch-readiness assessment (APPROVE / APPROVE-WITH-CONDITIONS / BLOCK)
- Performance comparison showing ~2-3x speedup from parallelization
- DOC-001 (e-commerce): BLOCK — critical security issues
- DOC-002 (HR portal): APPROVE — low risk across all dimensions
