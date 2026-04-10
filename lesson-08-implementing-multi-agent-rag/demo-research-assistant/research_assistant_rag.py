"""
research_assistant_rag.py - DEMO (Instructor-Led)
===================================================
Module 8 Demo: Building a Multi-Agent RAG Research Assistant

Architecture:
    Student asks research question
         │
    ┌────┴─────────────────────────────────────────────────┐
    │  Parallel Retrieval (ThreadPoolExecutor)               │
    │  Two specialized retrievers query domain-specific KBs  │
    └────┬──────────────────┬──────────────────────────────┘
         │                  │
    ┌────┴──────┐    ┌─────┴──────┐
    │ CSRetriever│    │BioRetriever│
    │ (CS KB)    │    │ (Bio KB)   │
    └────┬──────┘    └─────┬──────┘
         │                  │
    ┌────┴──────────────────┴──────────────────────────────┐
    │  Result Aggregation                                    │
    │  - Combine passages from both KBs                      │
    │  - Rank by relevance score                             │
    │  - Select top-K most relevant                          │
    └────┬─────────────────────────────────────────────────┘
         │
    ┌────┴─────────────────────────────────────────────────┐
    │  SynthesisAgent                                        │
    │  - Produces grounded answer with citations              │
    │  - Every claim must reference a specific passage        │
    │  - Handles partial results gracefully                   │
    └──────────────────────────────────────────────────────┘

Key Concepts (Module 8):
  1. SPECIALIZED RETRIEVERS: Each retriever owns one KB, one tool
  2. PARALLEL RETRIEVAL: Both retrievers run simultaneously
  3. RELEVANCE SCORING: Passages ranked by confidence score
  4. TOP-K SELECTION: Only highest-scoring passages go to synthesis
  5. GROUNDED SYNTHESIS: Every claim cites a specific passage
  6. GRACEFUL DEGRADATION: If one retriever fails, use the other

RAG Quality Metrics:
  - Groundedness: every claim has a supporting passage
  - Relevance: passages match the query
  - Completeness: key aspects of the question are covered

Tech Stack:
  - Python 3.11+
  - Strands Agents SDK (Agent class, @tool decorator)
  - Amazon Bedrock (Nova Lite for retrievers, Nova Pro for synthesis)
  - Amazon Bedrock Knowledge Bases (real AWS resources for semantic search)

Note: This lesson uses real Amazon Bedrock Knowledge Bases.
Knowledge Bases are created manually in AWS Console with S3 data sources.
Production-mapping comments show the exact boto3 API calls.
"""

import json
import os
import re
import time
import logging
import boto3
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from strands import Agent, tool
from strands.models import BedrockModel

load_dotenv()

logging.basicConfig(level=logging.WARNING)


def clean_response(text: str) -> str:
    """Strip <thinking>...</thinking> tags from Nova model outputs."""
    return re.sub(r"<thinking>.*?</thinking>\s*", "", str(text), flags=re.DOTALL).strip()


def run_agent_with_retry(agent_builder, prompt: str, max_retries: int = 3) -> float:
    """Run an agent with retry logic for transient Bedrock errors.
    Uses exponential backoff (1s, 2s, 4s) to handle throttling."""
    for attempt in range(max_retries):
        try:
            agent = agent_builder()
            t = time.time()
            agent(prompt)
            return time.time() - t
        except Exception as e:
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                print(f"    [Retry {attempt + 1}/{max_retries}] {e.__class__.__name__}, waiting {wait}s...")
                time.sleep(wait)
            else:
                print(f"    [Failed] {e.__class__.__name__} after {max_retries} attempts")
                raise


# ─────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
NOVA_LITE_MODEL = os.environ.get("NOVA_LITE_MODEL", "amazon.nova-lite-v1:0")
NOVA_PRO_MODEL = os.environ.get("NOVA_PRO_MODEL", "amazon.nova-pro-v1:0")
TOP_K = 5  # Number of top passages to pass to synthesis

# Bedrock Knowledge Base IDs (created manually in AWS Console)
CS_KB_ID = os.environ.get("CS_KB_ID", "")
BIO_KB_ID = os.environ.get("BIO_KB_ID", "")

# Bedrock Agent Runtime client for KB retrieval
bedrock_agent_runtime = boto3.client("bedrock-agent-runtime", region_name=AWS_REGION)


# STEP 1: KNOWLEDGE BASE DATA — Reference data showing what's indexed in Bedrock KBs via S3
# Production: bedrock_agent.retrieve(knowledgeBaseId, retrievalQuery, vectorSearchConfiguration)
# Returns: retrievalResults[].content.text, .score, .location
# Here: In-memory docs + keyword matching

CS_PAPERS = [
    {
        "doc_id": "CS-001", "title": "Deep Learning for Genomic Sequence Analysis",
        "source": "Journal of ML Research, 2024",
        "content": "We present a transformer-based architecture for predicting gene expression "
                   "levels from DNA sequences. Our model achieves 94% accuracy on the benchmark "
                   "GenomeBERT dataset, outperforming previous CNN-based approaches by 12%. "
                   "The attention mechanism reveals biologically meaningful motifs.",
        "keywords": ["machine learning", "deep learning", "genomics", "transformer", "gene expression", "DNA"],
    },
    {
        "doc_id": "CS-002", "title": "Federated Learning in Healthcare: Privacy-Preserving ML",
        "source": "IEEE Transactions on AI, 2024",
        "content": "Federated learning enables hospitals to collaboratively train ML models "
                   "without sharing patient data. We demonstrate a federated approach for "
                   "predicting drug interactions that achieves 91% accuracy while maintaining "
                   "HIPAA compliance. Communication overhead is reduced 60% via gradient compression.",
        "keywords": ["federated learning", "healthcare", "privacy", "drug interactions", "machine learning"],
    },
    {
        "doc_id": "CS-003", "title": "Reinforcement Learning for Protein Folding Optimization",
        "source": "NeurIPS 2024 Proceedings",
        "content": "We apply deep reinforcement learning to optimize protein folding simulations. "
                   "Our RL agent explores conformational space 50x faster than molecular dynamics. "
                   "The approach discovers novel folding pathways for 3 previously unsolved proteins, "
                   "validated against experimental X-ray crystallography data.",
        "keywords": ["reinforcement learning", "protein folding", "optimization", "molecular dynamics"],
    },
    {
        "doc_id": "CS-004", "title": "Natural Language Processing for Biomedical Literature Mining",
        "source": "ACL 2024 Proceedings",
        "content": "Our NLP pipeline extracts gene-disease associations from 2 million PubMed "
                   "abstracts with 89% F1 score. We fine-tune BioBERT on a curated dataset of "
                   "10,000 annotated abstracts. The system identifies 340 novel gene-disease "
                   "associations not present in existing databases.",
        "keywords": ["NLP", "biomedical", "text mining", "gene-disease", "BioBERT", "machine learning"],
    },
    {
        "doc_id": "CS-005", "title": "Graph Neural Networks for Drug Discovery",
        "source": "ICML 2024 Workshop",
        "content": "We introduce MolGNN, a graph neural network for predicting molecular "
                   "properties relevant to drug discovery. MolGNN achieves state-of-the-art "
                   "results on 8 of 12 MoleculeNet benchmarks. The model identifies 15 "
                   "candidate compounds for malaria treatment, 3 of which show promise in vitro.",
        "keywords": ["graph neural networks", "drug discovery", "molecular properties", "machine learning"],
    },
    {
        "doc_id": "CS-006", "title": "Quantum Computing Algorithms for Cryptography",
        "source": "ACM Computing Surveys, 2024",
        "content": "We survey post-quantum cryptographic algorithms resistant to Shor's algorithm. "
                   "Lattice-based schemes show the best balance of security and performance. "
                   "We benchmark 5 NIST finalist algorithms on current quantum simulators.",
        "keywords": ["quantum computing", "cryptography", "post-quantum", "lattice"],
    },
]

BIO_PAPERS = [
    {
        "doc_id": "BIO-001", "title": "CRISPR-Cas9 Applications in Crop Genomics",
        "source": "Nature Biotechnology, 2024",
        "content": "We demonstrate CRISPR-Cas9 gene editing for drought resistance in wheat. "
                   "Targeted knockout of the TaDREB2 gene increases water-use efficiency by 40%. "
                   "Field trials across 3 climate zones confirm yield improvements of 15-25% "
                   "under water-stressed conditions.",
        "keywords": ["CRISPR", "genomics", "crop science", "gene editing", "drought resistance"],
    },
    {
        "doc_id": "BIO-002", "title": "Machine Learning Identifies Novel Cancer Biomarkers",
        "source": "Cancer Research, 2024",
        "content": "Using ML-based analysis of single-cell RNA sequencing data, we identify "
                   "7 novel biomarkers for early-stage pancreatic cancer. A random forest classifier "
                   "achieves 96% sensitivity and 88% specificity. Three biomarkers show promise "
                   "for liquid biopsy detection, enabling non-invasive screening.",
        "keywords": ["machine learning", "cancer", "biomarkers", "RNA sequencing", "genomics"],
    },
    {
        "doc_id": "BIO-003", "title": "Microbiome-Host Interactions in Inflammatory Disease",
        "source": "Cell, 2024",
        "content": "We map the gut microbiome's influence on inflammatory bowel disease using "
                   "metagenomic sequencing of 500 patients. Specific Bacteroides species correlate "
                   "with disease remission (p<0.001). Fecal transplant from remission patients "
                   "reduces inflammation markers by 65% in mouse models.",
        "keywords": ["microbiome", "inflammatory disease", "metagenomics", "gut health"],
    },
    {
        "doc_id": "BIO-004", "title": "Genomic Analysis of Antibiotic Resistance Evolution",
        "source": "Science, 2024",
        "content": "Whole-genome sequencing of 1,200 MRSA isolates reveals 4 novel resistance "
                   "mechanisms involving horizontal gene transfer. We trace resistance gene "
                   "flow across hospital networks using phylogenetic analysis. ML-based prediction "
                   "of resistance patterns achieves 93% accuracy.",
        "keywords": ["genomics", "antibiotic resistance", "MRSA", "gene transfer", "machine learning"],
    },
    {
        "doc_id": "BIO-005", "title": "Protein Engineering for Enzyme Optimization",
        "source": "Nature Chemical Biology, 2024",
        "content": "Directed evolution combined with computational protein design yields enzymes "
                   "with 100x improved catalytic efficiency for biofuel production. Deep learning "
                   "models predict beneficial mutations with 78% accuracy, reducing screening "
                   "cycles from 12 to 3.",
        "keywords": ["protein engineering", "enzyme", "directed evolution", "deep learning", "biofuel"],
    },
    {
        "doc_id": "BIO-006", "title": "Neural Circuit Mapping in Drosophila",
        "source": "Neuron, 2024",
        "content": "Using electron microscopy and connectomics, we map the complete neural circuit "
                   "for olfactory learning in Drosophila melanogaster. The circuit contains 347 "
                   "neurons and 2,891 synapses. Ablation experiments confirm the critical role "
                   "of mushroom body output neurons in associative memory.",
        "keywords": ["neuroscience", "neural circuits", "connectomics", "Drosophila", "olfactory"],
    },
]

# STEP 2: BEDROCK KB RETRIEVAL — Real Amazon Bedrock Knowledge Base API calls
def retrieve_from_kb(kb_id: str, query: str, kb_name: str,
                     top_k: int = 5, simulate_failure: bool = False) -> list[dict]:
    """
    Retrieve relevant documents from a Bedrock Knowledge Base.

    Production API: bedrock-agent-runtime.retrieve()

    Args:
        kb_id: The Knowledge Base ID from AWS Console
        query: Natural language search query
        kb_name: Display name for logging
        top_k: Number of results to return
        simulate_failure: If True, raise ConnectionError (for graceful degradation testing)

    Returns:
        List of dicts with {doc_id, title, source, content, score, kb}
    """
    if simulate_failure:
        raise ConnectionError(f"Knowledge Base '{kb_name}' is temporarily unavailable")

    if not kb_id:
        print(f"    WARNING: {kb_name} KB ID not set — returning empty results")
        return []

    response = bedrock_agent_runtime.retrieve(
        knowledgeBaseId=kb_id,
        retrievalQuery={"text": query},
        retrievalConfiguration={
            "vectorSearchConfiguration": {
                "numberOfResults": top_k,
            }
        },
    )

    results = []
    for i, result in enumerate(response.get("retrievalResults", [])):
        content = result.get("content", {}).get("text", "")
        score = result.get("score", 0.0)
        location = result.get("location", {})
        uri = location.get("s3Location", {}).get("uri", "") if location.get("type") == "S3" else ""

        results.append({
            "doc_id": f"{kb_name}-{i+1}",
            "title": uri.split("/")[-1] if uri else f"Result {i+1}",
            "source": uri or kb_name,
            "content": content,
            "score": score,
            "kb": kb_name,
        })

    return results


# ─────────────────────────────────────────────────────
# SAMPLE QUERIES
# ─────────────────────────────────────────────────────
QUERIES = [
    {
        "query": "applications of machine learning in genomics",
        "description": "Cross-domain query — should hit BOTH CS and Bio KBs",
        "expected_domains": ["CS", "Bio"],
    },
    {
        "query": "CRISPR gene editing for crop improvement",
        "description": "Domain-specific query — should primarily hit Bio KB",
        "expected_domains": ["Bio"],
    },
    {
        "query": "blockchain consensus mechanisms for IoT networks",
        "description": "Out-of-scope query — should find no relevant results",
        "expected_domains": [],
    },
]


# STEP 3: RETRIEVER AGENTS — 2 specialized agents for CS and Bio KBs
retrieval_results = {"cs": [], "bio": []}


def build_cs_retriever(query: str) -> Agent:
    """CS Papers retriever agent — queries the Computer Science KB."""
    # STEP 3.1: BedrockModel — Nova Lite for CS KB retrieval (temperature 0.0)
    model = BedrockModel(model_id=NOVA_LITE_MODEL, region_name=AWS_REGION, temperature=0.0)
    # STEP 3.2: System prompt — Query CS papers knowledge base
    system_prompt = f"""You are a Computer Science paper retrieval agent. Your ONLY job:
1. Call retrieve_cs_papers with the query
2. Report how many passages were found and their relevance scores
Do NOT add any other commentary."""

    @tool
    def retrieve_cs_papers(search_query: str) -> str:
        """
        Retrieve relevant passages from the CS papers Knowledge Base.

        Args:
            search_query: The research query to search for

        Returns:
            JSON with retrieved passages and relevance scores
        """
        passages = retrieve_from_kb(CS_KB_ID, search_query, "CS Papers", TOP_K)
        retrieval_results["cs"] = passages

        return json.dumps({
            "kb": "CS Papers",
            "query": search_query,
            "passages_found": len(passages),
            "results": [
                {"doc_id": p["doc_id"], "title": p["title"], "score": p["score"]}
                for p in passages
            ],
        }, indent=2)

    # STEP 3.3: Build Agent — CS retriever with retrieve_cs_papers tool
    return Agent(model=model, system_prompt=system_prompt, tools=[retrieve_cs_papers])


def build_bio_retriever(query: str, simulate_failure: bool = False) -> Agent:
    """Biology Papers retriever agent — queries the Biology KB."""
    # STEP 3.4: BedrockModel — Nova Lite for Bio KB retrieval (temperature 0.0)
    model = BedrockModel(model_id=NOVA_LITE_MODEL, region_name=AWS_REGION, temperature=0.0)
    # STEP 3.5: System prompt — Query Biology papers knowledge base
    system_prompt = f"""You are a Biology paper retrieval agent. Your ONLY job:
1. Call retrieve_bio_papers with the query
2. Report how many passages were found and their relevance scores
Do NOT add any other commentary."""

    @tool
    def retrieve_bio_papers(search_query: str) -> str:
        """
        Retrieve relevant passages from the Biology papers Knowledge Base.

        Args:
            search_query: The research query to search for

        Returns:
            JSON with retrieved passages and relevance scores
        """
        try:
            passages = retrieve_from_kb(BIO_KB_ID, search_query, "Biology Papers", TOP_K, simulate_failure)
            retrieval_results["bio"] = passages
        except ConnectionError as e:
            retrieval_results["bio"] = []
            return json.dumps({
                "kb": "Biology Papers",
                "query": search_query,
                "error": str(e),
                "passages_found": 0,
            }, indent=2)

        return json.dumps({
            "kb": "Biology Papers",
            "query": search_query,
            "passages_found": len(passages),
            "results": [
                {"doc_id": p["doc_id"], "title": p["title"], "score": p["score"]}
                for p in passages
            ],
        }, indent=2)

    # STEP 3.6: Build Agent — Bio retriever with retrieve_bio_papers tool
    return Agent(model=model, system_prompt=system_prompt, tools=[retrieve_bio_papers])


# STEP 4: RESULT AGGREGATION — Combine and rank retrieved passages
def aggregate_results(cs_passages: list, bio_passages: list, top_k: int = TOP_K) -> list[dict]:
    """Combine passages from both KBs, rank by relevance score, select top-K."""
    all_passages = cs_passages + bio_passages
    all_passages.sort(key=lambda x: x["score"], reverse=True)
    return all_passages[:top_k]


# STEP 5: SYNTHESIS AGENT — Grounded answer with citations
def build_synthesis_agent(passages: list[dict], query: str) -> Agent:
    """Produces grounded research summary with citations from top passages."""
    # STEP 5.1: BedrockModel — Nova Pro for synthesis (temperature 0.2)
    model = BedrockModel(model_id=NOVA_PRO_MODEL, region_name=AWS_REGION, temperature=0.2)

    # Format passages for the synthesis prompt
    formatted = "\n\n".join(
        f"[{p['doc_id']}] {p['title']} (Score: {p['score']})\n"
        f"Source: {p['source']}\n"
        f"Content: {p['content']}"
        for p in passages
    )

    # STEP 5.2: System prompt — Synthesis rules for grounded answers with citations
    system_prompt = f"""You are a research synthesis agent. Your job is to answer the research
question using ONLY the retrieved passages below. Rules:
1. Every factual claim MUST cite a specific passage using [DOC_ID] format
2. If passages don't contain relevant information, say so honestly
3. Structure: Brief summary, then key findings with citations
4. Do NOT invent or hallucinate information not in the passages
5. If results are from only one domain, note that the answer is partial

RETRIEVED PASSAGES:
{formatted}

RESEARCH QUESTION: {query}

Provide a grounded research summary with citations."""

    # STEP 5.3: Build Agent — synthesis with no external tools, grounded in passages
    return Agent(model=model, system_prompt=system_prompt, tools=[])


# STEP 6: RAG ORCHESTRATOR — Parallel retrieval + aggregation + synthesis
def run_rag_query(query_data: dict):
    """Execute a full RAG pipeline for a research query."""
    query = query_data["query"]

    retrieval_results["cs"] = []
    retrieval_results["bio"] = []
    print(f"\n  Dispatching 2 retrievers in parallel...")
    t_start = time.time()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(
                run_agent_with_retry,
                lambda: build_cs_retriever(query),
                f"Search for: {query}"
            ): "CS",
            executor.submit(
                run_agent_with_retry,
                lambda: build_bio_retriever(query),
                f"Search for: {query}"
            ): "Bio",
        }

        timings = {}
        for future in as_completed(futures):
            name = futures[future]
            try:
                timings[name] = future.result()
            except Exception as e:
                print(f"    {name} retriever failed: {e}")
                timings[name] = -1

    t_retrieval = time.time() - t_start
    cs_count = len(retrieval_results["cs"])
    bio_count = len(retrieval_results["bio"])
    print(f"    CS: {cs_count} | Bio: {bio_count} | Time: {t_retrieval:.1f}s")
    print(f"\n  Aggregating results (top-{TOP_K})...")
    top_passages = aggregate_results(retrieval_results["cs"], retrieval_results["bio"])

    if not top_passages:
        print(f"    No relevant passages found — skipping synthesis")
        return {
            "query": query,
            "cs_passages": 0,
            "bio_passages": 0,
            "top_passages": 0,
            "synthesis": "No relevant results found for this query.",
            "avg_score": 0,
        }

    for p in top_passages:
        print(f"      [{p['doc_id']}] {p['title'][:50]}... (score: {p['score']})")
    avg_score = round(sum(p["score"] for p in top_passages) / len(top_passages), 3)
    print(f"    Avg score: {avg_score}")
    print(f"\n  SynthesisAgent...")
    t_synth = run_agent_with_retry(
        lambda: build_synthesis_agent(top_passages, query),
        f"Answer the research question: {query}"
    )
    print(f"    Time: {t_synth:.1f}s")

    return {
        "query": query,
        "cs_passages": cs_count,
        "bio_passages": bio_count,
        "top_passages": len(top_passages),
        "avg_score": avg_score,
        "retrieval_time": t_retrieval,
        "synthesis_time": t_synth,
    }


# ═══════════════════════════════════════════════════════
#  STEP 7: DEMO EXECUTION — Run 3 RAG query scenarios
# ═══════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("  Multi-Agent RAG Research Assistant — Module 8 Demo")
    print("  2 Specialized Retrievers + Parallel Retrieval + Synthesis")
    print("  CS Papers KB + Biology Papers KB → Grounded Answers")
    print("=" * 70)

    results = []

    for i, query_data in enumerate(QUERIES):
        print(f"\n{'━' * 70}")
        print(f"  QUERY {i + 1}: \"{query_data['query']}\"")
        print(f"  {query_data['description']}")
        print(f"  Expected: {', '.join(query_data['expected_domains']) or 'no results'}")
        print(f"{'━' * 70}")

        result = run_rag_query(query_data)
        results.append(result)

        print(f"\n  Results: CS={result['cs_passages']} Bio={result['bio_passages']} Top-K={result['top_passages']} Score={result['avg_score']}")

    print(f"\n{'═' * 70}")
    print("SUMMARY")
    print(f"{'═' * 70}")

    for r in results:
        total = r['cs_passages'] + r['bio_passages']
        status = "✓" if total > 0 else "○"
        print(f"  {status} \"{r['query'][:50]}...\"")
        print(f"    Passages: {total} (CS={r['cs_passages']}, Bio={r['bio_passages']}), "
              f"Top-K: {r['top_passages']}, Avg score: {r['avg_score']}")

    print(f"\n  Key Insights:")
    print(f"  1. SPECIALIZED RETRIEVERS — each owns one KB with focused embeddings")
    print(f"  2. PARALLEL RETRIEVAL — both KBs searched simultaneously")
    print(f"  3. RELEVANCE SCORING — passages ranked by confidence score")
    print(f"     Production: Bedrock KB returns score per retrievalResult")
    print(f"  4. TOP-K SELECTION — only best passages go to synthesis")
    print(f"  5. GROUNDED SYNTHESIS — every claim cites [DOC_ID]")
    print(f"     Production: SynthesisAgent's system prompt enforces citations")
    print(f"  6. GRACEFUL DEGRADATION — partial results > no results")
    print(f"     If one retriever fails, synthesis uses available passages\n")


if __name__ == "__main__":
    main()
