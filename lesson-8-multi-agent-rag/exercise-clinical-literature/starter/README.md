# Exercise Starter: Multi-Agent RAG for Clinical Literature

## Overview
Build a clinical literature RAG system following the same pattern from the demo (research_assistant_rag.py). Two specialized retrievers query Drug Interactions and Clinical Guidelines Knowledge Bases in parallel. Add deduplication, structured clinical output, and graceful degradation when a KB is unavailable.

## Your Task
Complete **16 TODOs** in `clinical_literature_rag.py`:

### Retriever Agent TODOs (6 = 3 per retriever x 2 retrievers)
| Agent | TODOs | What to implement |
|-------|-------|-------------------|
| DrugInteractionRetriever | 1, 2, 3 | BedrockModel, system prompt, return Agent |
| GuidelinesRetriever | 4, 5, 6 | BedrockModel, system prompt, return Agent |

Each retriever needs: BedrockModel (TODO), system prompt (TODO), return Agent (TODO). The @tool functions are provided.

### Aggregation TODOs (2) — NEW pattern
| TODO | What to implement | Hint |
|------|-------------------|------|
| TODO 7 | `deduplicate_passages()` — remove duplicate doc_ids | Track seen IDs in a set |
| TODO 8 | `aggregate_results()` — combine + dedup + rank + top-K | Same as demo, plus dedup call |

### Synthesis Agent TODOs (5)
| TODO | What to implement | Hint |
|------|-------------------|------|
| TODO 9 | BedrockModel for synthesis | Use NOVA_PRO_MODEL, temperature=0.1 |
| TODO 10 | Format passages into string | Same as demo |
| TODO 11 | Partial notice for degradation | Conditional warning if partial=True |
| TODO 12 | System prompt for structured output | Drug Interactions + Guidelines + Recommendation sections |
| TODO 13 | Return Agent | Same as demo |

### Orchestrator TODOs (3)
| TODO | What to implement | Hint |
|------|-------------------|------|
| TODO 14 | Parallel retrieval with ThreadPoolExecutor | Same as demo |
| TODO 15 | Call aggregate_results | Combine drug + guideline passages |
| TODO 16 | Run synthesis agent | Same as demo, with partial flag |

## What's Already Done
- Simulated Knowledge Bases (DRUG_INTERACTIONS_KB, CLINICAL_GUIDELINES_KB)
- `retrieve_from_kb()` function (keyword-based relevance scoring)
- All `@tool` functions for both retrievers
- Sample clinical queries (3 scenarios including degradation test)
- Helper functions (clean_response, run_agent_with_retry)
- Main function with output formatting

## Expected Results
- Query 1: Warfarin — hits both KBs, structured output with citations
- Query 2: SSRI/MAOI — high relevance across both KBs
- Query 3: Metformin (degradation) — Drug KB fails, partial results with disclaimer

## Running
```bash
python clinical_literature_rag.py
```
