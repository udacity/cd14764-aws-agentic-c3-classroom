# Lesson 8: Multi-Agent RAG with Specialized Retrievers

This lesson teaches the Multi-Agent RAG (Retrieval-Augmented Generation) pattern where multiple specialized retriever agents each own a distinct Knowledge Base. Retrievers run in parallel via ThreadPoolExecutor, their results are aggregated and ranked, and a synthesis agent produces a grounded answer with citations.

The lesson uses **real Amazon Bedrock Knowledge Bases** backed by S3 Vectors in **us-west-2** (Oregon) or **us-east-1** (N. Virginia). Knowledge Bases cannot be created via CloudFormation today, so the demo and exercise each include a manual console step. Each activity folder below has its own `infrastructure/`, `seed_documents.py`, `.env.example`, and `README.md` — open the one you're working on for setup steps.

## Folder Structure

```
lesson-08-implementing-multi-agent-rag/
├── README.md
├── demo-research-assistant/
│   ├── README.md
│   ├── .env.example
│   ├── infrastructure/stack.yaml         ← S3 bucket for CS + Bio docs
│   ├── seed_documents.py                 ← seeds cs/ and bio/ prefixes
│   └── research_assistant_rag.py
└── exercise-clinical-literature/
    ├── starter/
    │   ├── README.md
    │   ├── .env.example
    │   ├── infrastructure/stack.yaml     ← S3 bucket for Drug + Guidelines docs
    │   ├── seed_documents.py             ← seeds drugs/ and guidelines/ prefixes
    │   └── clinical_literature_rag.py
    └── solution/
        ├── README.md
        ├── .env.example
        ├── infrastructure/stack.yaml     ← same as starter; deploy only if you skipped the starter
        ├── seed_documents.py             ← same as starter
        └── clinical_literature_rag.py
```

- **Demo (research assistant):** 2 retrievers — Computer Science papers + Biology papers — parallel retrieval, synthesis with `[DOC_ID]` citations.
- **Exercise (clinical literature):** 2 retrievers — Drug Interactions + Clinical Guidelines — same RAG pattern with deduplication, structured clinical output, and graceful degradation when a KB fails.

> **Cost note:** Titan v2 embeddings and S3 Vectors are inexpensive, but the KBs and their source buckets do incur small ongoing charges. Delete the KBs from the console and run the per-activity cleanup commands when you finish.
