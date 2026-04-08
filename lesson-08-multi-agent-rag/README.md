# Lesson 8: Multi-Agent RAG with Specialized Retrievers

This lesson teaches the Multi-Agent RAG (Retrieval-Augmented Generation) pattern where multiple specialized retriever agents each own a distinct Knowledge Base. Retrievers run in parallel via ThreadPoolExecutor, their results are aggregated and ranked, and a synthesis agent produces a grounded answer with citations. This architecture scales to any number of knowledge domains while keeping each retriever focused.

The lesson uses in-memory simulated Knowledge Bases with keyword-based relevance scoring so students can focus on the RAG pattern without infrastructure setup. Production-mapping comments throughout the code show the exact `bedrock-agent-runtime.retrieve()` API calls.

## Folder Structure

```
lesson-08-multi-agent-rag/
├── README.md
├── demo-research-assistant/
│   ├── README.md
│   └── research_assistant_rag.py
└── exercise-clinical-literature/
    ├── solution/
    │   ├── README.md
    │   └── clinical_literature_rag.py
    └── starter/
        ├── README.md
        └── clinical_literature_rag.py
```

## Demo: Multi-Agent RAG for Research Assistant (Instructor-led)
- **Domain:** Academic research (Computer Science papers + Biology papers)
- **Architecture:** 2 retriever agents (CS, Bio), each with its own simulated KB, parallel retrieval, result aggregation, synthesis agent
- **Simulated KBs:** 6 CS papers + 6 Bio papers with keyword-based relevance scoring
- **Synthesis:** Nova Pro produces grounded summary with [DOC_ID] citations
- **Test cases:** 3 queries — cross-domain, domain-specific, out-of-scope
- **Key insight:** Each retriever owns exactly one KB — separation of concerns enables independent scaling

## Exercise: Multi-Agent RAG for Clinical Literature (Student-led)
- **Domain:** Clinical decision support (Drug Interactions KB + Clinical Guidelines KB)
- **Architecture:** Same parallel retrieval pattern as demo, plus deduplication, structured output, and graceful degradation
- **Deduplication (NEW):** Remove near-identical passages before ranking
- **Structured Output (NEW):** Drug Interactions + Clinical Guidelines + Integrated Recommendation
- **Graceful Degradation (NEW):** When one KB fails, synthesis uses partial results with confidence disclaimer
- **Test cases:** 3 queries — straightforward, complex multi-drug, degradation test (Drug KB fails)
- **Key insight:** Clinical systems must handle partial knowledge base availability and clearly communicate confidence levels
