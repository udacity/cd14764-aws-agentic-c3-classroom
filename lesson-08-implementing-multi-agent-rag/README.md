# Lesson 8: Multi-Agent RAG with Specialized Retrievers

This lesson teaches the Multi-Agent RAG (Retrieval-Augmented Generation) pattern where multiple specialized retriever agents each own a distinct Knowledge Base. Retrievers run in parallel via ThreadPoolExecutor, their results are aggregated and ranked, and a synthesis agent produces a grounded answer with citations. This architecture scales to any number of knowledge domains while keeping each retriever focused.

The lesson uses **real Amazon Bedrock Knowledge Bases** backed by S3 Vectors. You must create the Knowledge Bases manually before running the demo or exercise — see the **Setup** section below. Production-mapping comments throughout the code show the exact `bedrock-agent-runtime.retrieve()` API calls.

## Setup: Create the Knowledge Bases

Bedrock Knowledge Bases cannot be created via CloudFormation today, so they are the one manual step in this lesson. Budget about 10 minutes the first time.

> **Region note:** Bedrock Knowledge Bases require **us-west-2** (Oregon) or **us-east-1** (N. Virginia). us-west-1 is not supported. All commands below use us-west-2.

**1. Deploy the S3 source bucket (CloudFormation):**

```bash
cd lesson-08-implementing-multi-agent-rag/infrastructure
aws cloudformation deploy \
  --template-file stack.yaml \
  --stack-name lesson-08-rag \
  --capabilities CAPABILITY_IAM
```

Note the `KBSourceBucketName` output — you'll use it as the data source for every KB.

**2. Seed documents into S3:**

```bash
python seed_documents.py
```

This script reads the KB IDs from the CloudFormation outputs automatically and uploads all 24 source documents (6 per KB) to the correct S3 prefixes. No manual file creation needed.

| Demo KB            | S3 prefix              |
|--------------------|------------------------|
| CS Papers          | `s3://<bucket>/cs/`    |
| Biology Papers     | `s3://<bucket>/bio/`   |

| Exercise KB           | S3 prefix                   |
|-----------------------|-----------------------------|
| Drug Interactions     | `s3://<bucket>/drugs/`      |
| Clinical Guidelines   | `s3://<bucket>/guidelines/` |

Any PDFs or `.txt` files in the corresponding domain work — a half-dozen per KB is enough. Sample document sets are referenced at the top of each `*_rag.py` file (the `CS_PAPERS`/`BIO_PAPERS` arrays describe what each KB should contain).

**3. Create each Knowledge Base** in the AWS Console:

1. Open **Amazon Bedrock → Knowledge Bases → Create knowledge base**
2. Data source: **S3**, pointing at the prefix from the table above
3. Embedding model: **amazon.titan-embed-text-v2:0**
4. Vector store: **Amazon S3 Vectors** (creates a vector index in S3 — no OpenSearch cost)
5. Wait for the data source **sync** to finish (few minutes per KB)
6. Copy the Knowledge Base ID (e.g., `ABCD1234EF`) into a `.env` file at the lesson root:

```bash
# .env (not committed)
AWS_REGION=us-east-1
CS_KB_ID=...
BIO_KB_ID=...
DRUG_INTERACTIONS_KB_ID=...
CLINICAL_GUIDELINES_KB_ID=...
```

If a KB ID is missing when you run the demo or exercise, the code fails fast with a clear setup-required message — no silent empty results.

**Cost note:** Titan v2 embeddings and S3 Vectors are inexpensive, but the KBs and their source bucket will incur small ongoing charges. Delete both when you finish the lesson.

## Folder Structure

```
lesson-08-implementing-multi-agent-rag/
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
- **Architecture:** 2 retriever agents (CS, Bio), each with its own Bedrock KB, parallel retrieval, result aggregation, synthesis agent
- **Knowledge Bases:** 2 Bedrock KBs backed by S3 Vectors (created per the Setup section above)
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

## Cleanup

This lesson is the most expensive to leave running because Bedrock Knowledge Bases bill for both vector storage and embedding refreshes. Tear everything down in this order:

1. **Delete the Knowledge Bases manually** (Bedrock cannot delete them via CloudFormation). In the AWS Console:
   - Bedrock → Knowledge Bases → select each KB you created (CS Papers, Biology Papers, Drug Interactions, Clinical Guidelines) → Delete
2. **Delete the CloudFormation stack** (removes the S3 source bucket; you may need to empty it first):
   ```bash
   aws cloudformation delete-stack --stack-name lesson-08-rag
   ```
3. **Optional:** delete the S3 Vectors index from the bucket the KB used (the console KB-deletion step usually does this for you).
