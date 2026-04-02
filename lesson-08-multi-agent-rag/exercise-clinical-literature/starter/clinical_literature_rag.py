"""
clinical_literature_rag.py - EXERCISE STARTER (Student-Led)
==============================================================
Module 8 Exercise: Build a Multi-Agent RAG System for Clinical Literature Review

Architecture:
    Doctor asks clinical question
         │
    ┌────┴─────────────────────────────────────────────────┐
    │  Parallel Retrieval (ThreadPoolExecutor)               │
    │  Two specialized retrievers query clinical KBs         │
    └────┬──────────────────┬──────────────────────────────┘
         │                  │
    ┌────┴──────────┐  ┌───┴───────────────┐
    │ DrugInteraction│  │ClinicalGuidelines │
    │ Retriever      │  │Retriever          │
    └────┬──────────┘  └───┬───────────────┘
         │                  │
    ┌────┴──────────────────┴──────────────────────────────┐
    │  Result Aggregation + Deduplication                    │
    │  - Combine passages from both KBs                      │
    │  - Deduplicate near-identical passages (NEW)           │
    │  - Rank by relevance score, select top-10              │
    └────┬─────────────────────────────────────────────────┘
         │
    ┌────┴─────────────────────────────────────────────────┐
    │  SynthesisAgent (structured clinical output)           │
    │  - Drug Interactions section + Guidelines section       │
    │  - Integrated Recommendation                           │
    │  - Mandatory citations + confidence disclaimer          │
    │  - Handles partial results with degradation notice      │
    └──────────────────────────────────────────────────────┘

Same RAG pattern as the demo (research_assistant_rag.py),
with additions:
  1. DEDUPLICATION: Remove near-identical passages before ranking
  2. STRUCTURED OUTPUT: Drug Interactions + Guidelines + Recommendation
  3. GRACEFUL DEGRADATION: Explicit test of one retriever failing
  4. CONFIDENCE DISCLAIMER: For partial results

Instructions:
  - Follow the demo pattern (research_assistant_rag.py)
  - Look for TODO 1-16 below
  - Retriever agents: each owns one clinical KB
  - Aggregation: combine + deduplicate + rank
  - Synthesis: structured output with citations
  - Graceful degradation when one KB fails

Tech Stack:
  - Python 3.11+
  - Strands Agents SDK (Agent class, @tool decorator)
  - Amazon Bedrock (Nova Lite for retrievers, Nova Pro for synthesis)
  - Simulated Knowledge Bases (in-memory; production uses Bedrock KB + S3 Vectors)
"""

import json
import re
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from strands import Agent, tool
from strands.models import BedrockModel

logging.basicConfig(level=logging.WARNING)


def clean_response(text: str) -> str:
    """Strip <thinking>...</thinking> tags from Nova model outputs."""
    return re.sub(r"<thinking>.*?</thinking>\s*", "", str(text), flags=re.DOTALL).strip()


def run_agent_with_retry(agent_builder, prompt: str, max_retries: int = 3) -> float:
    """Run an agent with retry logic for transient Bedrock errors."""
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


AWS_REGION = "us-east-1"
NOVA_LITE_MODEL = "amazon.nova-lite-v1:0"
NOVA_PRO_MODEL = "amazon.nova-pro-v1:0"
TOP_K = 10  # More passages for clinical context


# SIMULATED KNOWLEDGE BASES — Clinical Domain
# Production: bedrock_agent.retrieve(knowledgeBaseId, retrievalQuery, vectorSearchConfiguration)

DRUG_INTERACTIONS_KB = [
    {
        "doc_id": "DI-001", "title": "Warfarin-Aspirin Interaction Profile",
        "source": "Clinical Pharmacology & Therapeutics, 2024",
        "content": "Concurrent use of warfarin and aspirin increases bleeding risk by 2.5x. "
                   "The mechanism involves dual anticoagulant/antiplatelet pathways. INR monitoring "
                   "should be increased to weekly when co-prescribing. Consider dose reduction of "
                   "warfarin by 25% with low-dose aspirin (81mg).",
        "keywords": ["warfarin", "aspirin", "bleeding", "anticoagulant", "drug interaction", "INR"],
    },
    {
        "doc_id": "DI-002", "title": "Metformin and Contrast Dye: Lactic Acidosis Risk",
        "source": "Journal of Clinical Pharmacology, 2024",
        "content": "Metformin should be withheld 48 hours before and after iodinated contrast "
                   "procedures. Risk of lactic acidosis is elevated in patients with eGFR < 30. "
                   "For patients with eGFR 30-60, hold metformin 24 hours pre-procedure. "
                   "Monitor serum creatinine 48 hours post-procedure before resuming.",
        "keywords": ["metformin", "contrast dye", "lactic acidosis", "renal", "drug interaction"],
    },
    {
        "doc_id": "DI-003", "title": "SSRI-MAOI Interaction: Serotonin Syndrome",
        "source": "Annals of Pharmacotherapy, 2024",
        "content": "Combining SSRIs with MAOIs can cause life-threatening serotonin syndrome. "
                   "Symptoms include hyperthermia (>40°C), muscle rigidity, and autonomic instability. "
                   "A 14-day washout period is required when switching between these drug classes. "
                   "Fluoxetine requires a 5-week washout due to its long half-life.",
        "keywords": ["SSRI", "MAOI", "serotonin syndrome", "antidepressant", "drug interaction"],
    },
    {
        "doc_id": "DI-004", "title": "Statin-Grapefruit Interaction Mechanisms",
        "source": "Drug Metabolism Reviews, 2024",
        "content": "Grapefruit juice inhibits CYP3A4, increasing statin plasma levels 2-16x. "
                   "Simvastatin and lovastatin are most affected (CYP3A4 substrates). "
                   "Atorvastatin is moderately affected. Pravastatin and rosuvastatin are "
                   "unaffected. Advise patients on statins to avoid grapefruit consumption.",
        "keywords": ["statin", "grapefruit", "CYP3A4", "drug interaction", "metabolism"],
    },
    {
        "doc_id": "DI-005", "title": "Warfarin-Amiodarone: High-Risk Combination",
        "source": "Heart Rhythm, 2024",
        "content": "Amiodarone inhibits CYP2C9 and CYP3A4, increasing warfarin effect by 30-50%. "
                   "Reduce warfarin dose by 33-50% when initiating amiodarone. INR can remain "
                   "elevated for weeks after amiodarone discontinuation due to its 40-55 day "
                   "half-life. Weekly INR monitoring for 3 months recommended.",
        "keywords": ["warfarin", "amiodarone", "CYP2C9", "anticoagulant", "drug interaction"],
    },
    {
        "doc_id": "DI-006", "title": "ACE Inhibitor-Potassium Supplement Hyperkalemia",
        "source": "American Journal of Medicine, 2024",
        "content": "ACE inhibitors reduce aldosterone secretion, causing potassium retention. "
                   "Co-administration with potassium supplements or potassium-sparing diuretics "
                   "increases hyperkalemia risk 3x. Monitor serum potassium within 1 week of "
                   "starting ACE inhibitor. Target K+ level: 3.5-5.0 mEq/L.",
        "keywords": ["ACE inhibitor", "potassium", "hyperkalemia", "drug interaction"],
    },
]

CLINICAL_GUIDELINES_KB = [
    {
        "doc_id": "CG-001", "title": "AHA/ACC Guideline: Anticoagulation for Atrial Fibrillation",
        "source": "Circulation, 2024 AHA/ACC Guidelines",
        "content": "For non-valvular AF with CHA2DS2-VASc ≥ 2, recommend DOACs over warfarin "
                   "(Class I, Level A). If warfarin is used, target INR 2.0-3.0 with time in "
                   "therapeutic range ≥ 70%. Bleeding risk assessment using HAS-BLED score "
                   "should guide anticoagulation decisions. Annual reassessment required.",
        "keywords": ["anticoagulation", "atrial fibrillation", "warfarin", "DOAC", "guideline", "bleeding"],
    },
    {
        "doc_id": "CG-002", "title": "ADA Standards: Metformin as First-Line for Type 2 Diabetes",
        "source": "Diabetes Care, 2024 ADA Standards",
        "content": "Metformin remains first-line pharmacotherapy for type 2 diabetes (Grade A). "
                   "Start at 500mg daily, titrate to 2000mg over 4 weeks. Monitor renal function "
                   "(eGFR) at baseline and annually. Contraindicated if eGFR < 30. Reduce dose "
                   "to 1000mg/day if eGFR 30-45.",
        "keywords": ["metformin", "diabetes", "first-line", "renal", "guideline"],
    },
    {
        "doc_id": "CG-003", "title": "APA Guidelines: SSRI Prescribing for Major Depression",
        "source": "American Journal of Psychiatry, 2024 APA Guidelines",
        "content": "SSRIs recommended as first-line for moderate-severe MDD (Level I evidence). "
                   "Start at lowest effective dose. Allow 4-6 weeks for full response. "
                   "If inadequate response, augment with bupropion or switch to SNRI. "
                   "MAOIs reserved for treatment-resistant cases with 14-day washout from SSRIs.",
        "keywords": ["SSRI", "depression", "antidepressant", "MAOI", "guideline", "prescribing"],
    },
    {
        "doc_id": "CG-004", "title": "ACC/AHA Statin Therapy Guidelines",
        "source": "Journal of the ACC, 2024 Guidelines",
        "content": "High-intensity statins (atorvastatin 40-80mg, rosuvastatin 20-40mg) recommended "
                   "for patients with ASCVD or LDL ≥ 190mg/dL (Class I, Level A). Moderate-intensity "
                   "for primary prevention in adults 40-75 with diabetes. Monitor LDL 4-12 weeks "
                   "after initiation. Target ≥ 50% LDL reduction for high-intensity.",
        "keywords": ["statin", "cholesterol", "ASCVD", "LDL", "guideline", "prevention"],
    },
    {
        "doc_id": "CG-005", "title": "JNC 8: Hypertension Management with ACE Inhibitors",
        "source": "JAMA, 2024 JNC Guidelines Update",
        "content": "ACE inhibitors first-line for hypertension in patients with diabetes or CKD. "
                   "Start lisinopril 10mg daily, target BP < 130/80. Monitor potassium and "
                   "creatinine within 1-2 weeks of initiation. Contraindicated in pregnancy. "
                   "If persistent cough, switch to ARB.",
        "keywords": ["ACE inhibitor", "hypertension", "guideline", "potassium", "renal"],
    },
    {
        "doc_id": "CG-006", "title": "WHO Guidelines: Antibiotic Stewardship",
        "source": "WHO Essential Medicines, 2024",
        "content": "Narrow-spectrum antibiotics preferred over broad-spectrum when pathogen is "
                   "identified (Strong recommendation). Culture and sensitivity testing before "
                   "empiric therapy when feasible. De-escalation within 48-72 hours based on "
                   "culture results. Duration: shortest effective course.",
        "keywords": ["antibiotic", "stewardship", "resistance", "guideline", "prescribing"],
    },
]

CLINICAL_QUERIES = [
    {
        "query": "warfarin drug interactions and anticoagulation guidelines",
        "description": "Straightforward query — should hit BOTH Drug Interactions and Guidelines KBs",
        "expected_domains": ["Drug Interactions", "Guidelines"],
        "simulate_failure": None,
    },
    {
        "query": "SSRI MAOI interaction serotonin syndrome antidepressant prescribing",
        "description": "Complex multi-drug query — spans both KBs with high relevance",
        "expected_domains": ["Drug Interactions", "Guidelines"],
        "simulate_failure": None,
    },
    {
        "query": "metformin diabetes renal drug interaction guidelines",
        "description": "Graceful degradation test — Drug Interactions KB will FAIL",
        "expected_domains": ["Guidelines only (partial)"],
        "simulate_failure": "drug_interactions",
    },
]


# SIMULATED RETRIEVAL ENGINE
def retrieve_from_kb(documents: list[dict], query: str, kb_name: str,
                     top_k: int = 10) -> list[dict]:
    """Simulated KB retrieval with keyword-based scoring."""
    query_terms = set(query.lower().split())
    results = []

    for doc in documents:
        doc_terms = set(word.lower() for kw in doc["keywords"] for word in kw.split())
        title_terms = set(doc["title"].lower().split())
        all_doc_terms = doc_terms | title_terms

        overlap = query_terms & all_doc_terms
        if overlap:
            score = round(len(overlap) / len(query_terms), 3)
            keyword_matches = sum(1 for kw in doc["keywords"]
                                if any(qt in kw.lower() for qt in query_terms))
            score = min(round(score + keyword_matches * 0.05, 3), 0.99)

            results.append({
                "doc_id": doc["doc_id"],
                "title": doc["title"],
                "source": doc["source"],
                "content": doc["content"],
                "score": score,
                "kb": kb_name,
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]


# RETRIEVER AGENTS
retrieval_results = {"drug": [], "guidelines": []}


def build_drug_interaction_retriever(query: str,
                                      simulate_failure: bool = False) -> Agent:
    """Drug Interactions retriever — queries the pharmaceutical KB."""

    # TODO 1: Create a BedrockModel for the retriever
    # Hint: Same as demo — use NOVA_LITE_MODEL, temperature=0.0
    model = None  # Replace with BedrockModel(...)

    # TODO 2: Write a system prompt for this retriever
    # Hint: Tell the agent to call retrieve_drug_interactions and report results
    system_prompt = ""  # Replace with retriever instructions

    @tool
    def retrieve_drug_interactions(search_query: str) -> str:
        """
        Retrieve relevant passages from the Drug Interactions Knowledge Base.

        Args:
            search_query: The clinical query to search for

        Returns:
            JSON with retrieved passages and relevance scores
        """
        if simulate_failure:
            retrieval_results["drug"] = []
            return json.dumps({
                "kb": "Drug Interactions",
                "query": search_query,
                "error": "Drug Interactions KB temporarily unavailable — service degraded",
                "passages_found": 0,
            }, indent=2)

        passages = retrieve_from_kb(DRUG_INTERACTIONS_KB, search_query, "Drug Interactions")
        retrieval_results["drug"] = passages

        return json.dumps({
            "kb": "Drug Interactions",
            "query": search_query,
            "passages_found": len(passages),
            "results": [
                {"doc_id": p["doc_id"], "title": p["title"], "score": p["score"]}
                for p in passages
            ],
        }, indent=2)

    # TODO 3: Return an Agent with the model, system_prompt, and tools
    # Hint: Agent(model=model, system_prompt=system_prompt, tools=[retrieve_drug_interactions])
    pass  # Replace with return Agent(...)


def build_guidelines_retriever(query: str,
                                simulate_failure: bool = False) -> Agent:
    """Clinical Guidelines retriever — queries the medical guidelines KB."""

    # TODO 4: Create a BedrockModel for the retriever
    # Hint: Same as TODO 1 — use NOVA_LITE_MODEL, temperature=0.0
    model = None  # Replace with BedrockModel(...)

    # TODO 5: Write a system prompt for this retriever
    # Hint: Tell the agent to call retrieve_guidelines and report results
    system_prompt = ""  # Replace with retriever instructions

    @tool
    def retrieve_guidelines(search_query: str) -> str:
        """
        Retrieve relevant passages from the Clinical Guidelines Knowledge Base.

        Args:
            search_query: The clinical query to search for

        Returns:
            JSON with retrieved passages and relevance scores
        """
        if simulate_failure:
            retrieval_results["guidelines"] = []
            return json.dumps({
                "kb": "Clinical Guidelines",
                "query": search_query,
                "error": "Clinical Guidelines KB temporarily unavailable",
                "passages_found": 0,
            }, indent=2)

        passages = retrieve_from_kb(CLINICAL_GUIDELINES_KB, search_query, "Clinical Guidelines")
        retrieval_results["guidelines"] = passages

        return json.dumps({
            "kb": "Clinical Guidelines",
            "query": search_query,
            "passages_found": len(passages),
            "results": [
                {"doc_id": p["doc_id"], "title": p["title"], "score": p["score"]}
                for p in passages
            ],
        }, indent=2)

    # TODO 6: Return an Agent with the model, system_prompt, and tools
    # Hint: Agent(model=model, system_prompt=system_prompt, tools=[retrieve_guidelines])
    pass  # Replace with return Agent(...)


# RESULT AGGREGATION + DEDUPLICATION
def deduplicate_passages(passages: list[dict], similarity_threshold: float = 0.8) -> list[dict]:
    """
    Remove near-identical passages (NEW — not in demo).

    TODO 7: Implement deduplication by doc_id
    - Track seen doc_ids in a set
    - Only keep passages with doc_ids not seen before
    - Return the unique list

    Production: Use embedding cosine similarity between passage vectors.
    """
    # Replace with deduplication logic
    return passages  # Currently returns all — implement filtering


def aggregate_results(drug_passages: list, guideline_passages: list,
                      top_k: int = TOP_K) -> list[dict]:
    """
    Combine, deduplicate, rank, and select top-K passages.

    TODO 8: Implement the aggregation pipeline
    - Combine drug_passages + guideline_passages into one list
    - Call deduplicate_passages() to remove duplicates
    - Sort by score (descending)
    - Return top_k results

    Hint: Same as demo's aggregate_results, plus the deduplication call
    """
    # Replace with aggregation logic
    return []


# SYNTHESIS AGENT — Structured clinical output
def build_synthesis_agent(passages: list[dict], query: str,
                          partial: bool = False) -> Agent:
    """Structured clinical summary with citations."""

    # TODO 9: Create a BedrockModel for synthesis
    # Hint: Use NOVA_PRO_MODEL, temperature=0.1
    model = None  # Replace with BedrockModel(...)

    # TODO 10: Format the passages into a string for the system prompt
    # Hint: Same as demo — format each passage with doc_id, title, score, kb, source, content
    formatted = ""  # Replace with passage formatting

    # TODO 11: Build the partial_notice string for degradation scenarios
    # Hint: If partial=True, include a warning about incomplete data
    partial_notice = ""  # Replace with conditional warning

    # TODO 12: Write the system prompt for structured clinical synthesis
    # Hint: Instruct the agent to produce:
    #   - DRUG INTERACTIONS section
    #   - CLINICAL GUIDELINES section
    #   - INTEGRATED RECOMMENDATION section
    #   - Citations using [DOC_ID] format
    #   - Include partial_notice if applicable
    #   - Include the formatted passages
    system_prompt = ""  # Replace with synthesis instructions

    # TODO 13: Return an Agent with the model, system_prompt, and empty tools list
    # Hint: Agent(model=model, system_prompt=system_prompt, tools=[])
    pass  # Replace with return Agent(...)


# RAG ORCHESTRATOR
def run_clinical_rag(query_data: dict):
    """Execute a full RAG pipeline for a clinical query."""
    query = query_data["query"]
    fail_at = query_data.get("simulate_failure")

    retrieval_results["drug"] = []
    retrieval_results["guidelines"] = []

    # TODO 14: Run both retrievers in parallel using ThreadPoolExecutor
    # Hint: Same as demo — submit both retriever builders to executor
    # - build_drug_interaction_retriever(query, simulate_failure=(fail_at == "drug_interactions"))
    # - build_guidelines_retriever(query, simulate_failure=(fail_at == "guidelines"))
    # - Use run_agent_with_retry as the callable
    # - Collect timings from as_completed()
    print(f"\n  Dispatching 2 retrievers in parallel...")
    t_start = time.time()

    t_retrieval = time.time() - t_start
    drug_count = len(retrieval_results["drug"])
    guide_count = len(retrieval_results["guidelines"])
    print(f"    Drug Interactions: {drug_count} passage(s)")
    print(f"    Clinical Guidelines: {guide_count} passage(s)")
    if fail_at:
        print(f"    ⚠ {fail_at} KB unavailable — partial results")
    # TODO 15: Call aggregate_results to combine and rank passages
    print(f"  Aggregating + deduplicating (top-{TOP_K})...")
    top_passages = []  # Replace with aggregate_results call

    if not top_passages:
        print(f"    No relevant passages found — skipping synthesis")
        return {
            "query": query, "drug_passages": 0, "guideline_passages": 0,
            "top_passages": 0, "avg_score": 0,
            "synthesis": "No relevant results found.",
            "partial": False,
        }

    print(f"    Selected {len(top_passages)} passages after deduplication:")
    for p in top_passages:
        print(f"      [{p['doc_id']}] {p['title'][:50]}... (score: {p['score']})")
    avg_score = round(sum(p["score"] for p in top_passages) / len(top_passages), 3)
    # TODO 16: Run the synthesis agent with run_agent_with_retry
    partial = (fail_at is not None)
    print(f"  SynthesisAgent{' (PARTIAL)' if partial else ''}...")
    t_synth = 0  # Replace with run_agent_with_retry call

    return {
        "query": query,
        "drug_passages": drug_count,
        "guideline_passages": guide_count,
        "top_passages": len(top_passages),
        "avg_score": avg_score,
        "retrieval_time": t_retrieval,
        "synthesis_time": t_synth,
        "partial": partial,
    }


def main():
    print("=" * 70)
    print("  Clinical Literature RAG — Module 8 Exercise")
    print("  2 Specialized Retrievers + Parallel Retrieval + Synthesis")
    print("  Drug Interactions KB + Clinical Guidelines KB")
    print("=" * 70)

    results = []

    for i, query_data in enumerate(CLINICAL_QUERIES):
        print(f"\n{'━' * 70}")
        print(f"  QUERY {i + 1}: \"{query_data['query']}\"")
        print(f"  {query_data['description']}")
        print(f"  Expected: {', '.join(query_data['expected_domains'])}")
        if query_data.get("simulate_failure"):
            print(f"  ⚠ Simulated failure: {query_data['simulate_failure']} KB will be unavailable")
        print(f"{'━' * 70}")

        result = run_clinical_rag(query_data)
        results.append(result)

        print(f"\n  Results: Drug={result['drug_passages']} Guide={result['guideline_passages']} Top-K={result['top_passages']} Score={result['avg_score']} Partial={'YES ⚠' if result['partial'] else 'No'}")

    print(f"\n{'═' * 70}")
    print("SUMMARY")
    print(f"{'═' * 70}")

    for r in results:
        total = r['drug_passages'] + r['guideline_passages']
        status = "⚠" if r['partial'] else ("✓" if total > 0 else "○")
        print(f"  {status} \"{r['query'][:50]}...\"")
        print(f"    Passages: {total} (Drug={r['drug_passages']}, Guide={r['guideline_passages']}), "
              f"Top-K: {r['top_passages']}, Avg: {r['avg_score']}"
              f"{', PARTIAL' if r['partial'] else ''}")

    print(f"\n  Key Insights (exercise adds DEDUP + STRUCTURED OUTPUT + DEGRADATION):")
    print(f"  1. SPECIALIZED RETRIEVERS — each owns one clinical KB (same as demo)")
    print(f"  2. PARALLEL RETRIEVAL — both KBs searched simultaneously (same as demo)")
    print(f"  3. DEDUPLICATION — remove near-identical passages before ranking (NEW)")
    print(f"  4. STRUCTURED OUTPUT — Drug Interactions + Guidelines + Recommendation (NEW)")
    print(f"  5. GRACEFUL DEGRADATION — partial results with confidence disclaimer (NEW)")
    print(f"     If one KB fails, synthesis uses available passages + warns doctor")
    print(f"  6. GROUNDED SYNTHESIS — every claim cites [DOC_ID] (same as demo)\n")


if __name__ == "__main__":
    main()
