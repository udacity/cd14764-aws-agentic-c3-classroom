"""
clinical_literature_rag.py - EXERCISE SOLUTION (Student-Led)
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


# ─────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────
AWS_REGION = "us-east-1"
NOVA_LITE_MODEL = "amazon.nova-lite-v1:0"
NOVA_PRO_MODEL = "amazon.nova-pro-v1:0"
TOP_K = 10  # More passages for clinical context


# ═══════════════════════════════════════════════════════
#  SIMULATED KNOWLEDGE BASES — Clinical Domain
#
#  Production equivalent:
#    bedrock_agent = boto3.client('bedrock-agent-runtime')
#    response = bedrock_agent.retrieve(
#        knowledgeBaseId='KB_DRUG_INTERACTIONS_ID',
#        retrievalQuery={'text': query},
#        retrievalConfiguration={
#            'vectorSearchConfiguration': {'numberOfResults': 10}
#        }
#    )
# ═══════════════════════════════════════════════════════

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

# ─────────────────────────────────────────────────────
# SAMPLE CLINICAL QUERIES
# ─────────────────────────────────────────────────────
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


# ═══════════════════════════════════════════════════════
#  SIMULATED RETRIEVAL ENGINE
# ═══════════════════════════════════════════════════════

def retrieve_from_kb(documents: list[dict], query: str, kb_name: str,
                     top_k: int = 10) -> list[dict]:
    """Simulated retrieval from a Knowledge Base (keyword-based scoring)."""
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


# ═══════════════════════════════════════════════════════
#  RETRIEVER AGENTS
# ═══════════════════════════════════════════════════════

retrieval_results = {"drug": [], "guidelines": []}


def build_drug_interaction_retriever(query: str,
                                      simulate_failure: bool = False) -> Agent:
    """Drug Interactions retriever — queries the pharmaceutical KB."""

    model = BedrockModel(model_id=NOVA_LITE_MODEL, region_name=AWS_REGION, temperature=0.0)

    system_prompt = f"""You are a drug interaction retrieval agent. Your ONLY job:
1. Call retrieve_drug_interactions with the query
2. Report how many passages were found and their relevance scores
Do NOT add any other commentary."""

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

    return Agent(model=model, system_prompt=system_prompt, tools=[retrieve_drug_interactions])


def build_guidelines_retriever(query: str,
                                simulate_failure: bool = False) -> Agent:
    """Clinical Guidelines retriever — queries the medical guidelines KB."""

    model = BedrockModel(model_id=NOVA_LITE_MODEL, region_name=AWS_REGION, temperature=0.0)

    system_prompt = f"""You are a clinical guidelines retrieval agent. Your ONLY job:
1. Call retrieve_guidelines with the query
2. Report how many passages were found and their relevance scores
Do NOT add any other commentary."""

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

    return Agent(model=model, system_prompt=system_prompt, tools=[retrieve_guidelines])


# ═══════════════════════════════════════════════════════
#  RESULT AGGREGATION + DEDUPLICATION (NEW pattern)
# ═══════════════════════════════════════════════════════

def deduplicate_passages(passages: list[dict], similarity_threshold: float = 0.8) -> list[dict]:
    """
    Remove near-identical passages (NEW — not in demo).

    Simple deduplication based on doc_id overlap.
    Production: Use embedding cosine similarity between passage vectors.
    """
    seen_ids = set()
    unique = []
    for p in passages:
        if p["doc_id"] not in seen_ids:
            seen_ids.add(p["doc_id"])
            unique.append(p)
    return unique


def aggregate_results(drug_passages: list, guideline_passages: list,
                      top_k: int = TOP_K) -> list[dict]:
    """Combine, deduplicate, rank, and select top-K passages."""
    all_passages = drug_passages + guideline_passages
    all_passages = deduplicate_passages(all_passages)
    all_passages.sort(key=lambda x: x["score"], reverse=True)
    return all_passages[:top_k]


# ═══════════════════════════════════════════════════════
#  SYNTHESIS AGENT — Structured clinical output
# ═══════════════════════════════════════════════════════

def build_synthesis_agent(passages: list[dict], query: str,
                          partial: bool = False) -> Agent:
    """Synthesis agent — structured clinical summary with citations."""

    model = BedrockModel(model_id=NOVA_PRO_MODEL, region_name=AWS_REGION, temperature=0.1)

    formatted = "\n\n".join(
        f"[{p['doc_id']}] {p['title']} (Score: {p['score']}, KB: {p['kb']})\n"
        f"Source: {p['source']}\n"
        f"Content: {p['content']}"
        for p in passages
    )

    partial_notice = ""
    if partial:
        partial_notice = """
⚠ PARTIAL RESULTS: One knowledge base was unavailable. Include a confidence
disclaimer noting that this answer is based on incomplete data and the doctor
should verify against the unavailable source."""

    system_prompt = f"""You are a clinical literature synthesis agent for a hospital decision
support system. Produce a structured clinical summary using ONLY the retrieved passages.

RULES:
1. Every factual claim MUST cite a specific passage using [DOC_ID] format
2. Structure your answer as:
   - DRUG INTERACTIONS: relevant drug interaction findings
   - CLINICAL GUIDELINES: relevant guideline recommendations
   - INTEGRATED RECOMMENDATION: combined clinical advice
3. Do NOT invent information not in the passages
4. If a section has no relevant passages, state "No relevant data retrieved"
{partial_notice}

RETRIEVED PASSAGES:
{formatted}

CLINICAL QUESTION: {query}

Provide a structured clinical summary."""

    return Agent(model=model, system_prompt=system_prompt, tools=[])


# ═══════════════════════════════════════════════════════
#  RAG ORCHESTRATOR
# ═══════════════════════════════════════════════════════

def run_clinical_rag(query_data: dict):
    """Execute a full RAG pipeline for a clinical query."""
    query = query_data["query"]
    fail_at = query_data.get("simulate_failure")

    retrieval_results["drug"] = []
    retrieval_results["guidelines"] = []

    # ── Parallel Retrieval ───────────────────────────
    print(f"\n  Dispatching 2 retrievers in parallel...")
    t_start = time.time()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(
                run_agent_with_retry,
                lambda: build_drug_interaction_retriever(
                    query, simulate_failure=(fail_at == "drug_interactions")
                ),
                f"Search for: {query}"
            ): "Drug Interactions",
            executor.submit(
                run_agent_with_retry,
                lambda: build_guidelines_retriever(
                    query, simulate_failure=(fail_at == "guidelines")
                ),
                f"Search for: {query}"
            ): "Guidelines",
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

    drug_count = len(retrieval_results["drug"])
    guide_count = len(retrieval_results["guidelines"])
    print(f"    Drug Interactions: {drug_count} passage(s)")
    print(f"    Clinical Guidelines: {guide_count} passage(s)")
    if fail_at:
        print(f"    ⚠ {fail_at} KB was unavailable — using partial results")
    print(f"    Parallel retrieval time: {t_retrieval:.1f}s")

    # ── Aggregation + Deduplication ──────────────────
    print(f"\n  Aggregating + deduplicating results (top-{TOP_K})...")
    top_passages = aggregate_results(retrieval_results["drug"], retrieval_results["guidelines"])

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
        print(f"      [{p['doc_id']}] {p['title'][:50]}... (score: {p['score']}, kb: {p['kb']})")

    avg_score = round(sum(p["score"] for p in top_passages) / len(top_passages), 3)
    print(f"    Average relevance score: {avg_score}")

    # ── Synthesis ────────────────────────────────────
    partial = (fail_at is not None)
    print(f"\n  SynthesisAgent (structured clinical summary{' — PARTIAL' if partial else ''})...")
    t_synth = run_agent_with_retry(
        lambda: build_synthesis_agent(top_passages, query, partial=partial),
        f"Answer the clinical question: {query}"
    )
    print(f"    Synthesis time: {t_synth:.1f}s")

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


# ═══════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════

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

        print(f"\n  ┌─── RAG Quality Metrics ─────────────────────────┐")
        print(f"  │ Query:        \"{result['query'][:40]}...\"")
        print(f"  │ Drug passages:     {result['drug_passages']}")
        print(f"  │ Guideline passages:{result['guideline_passages']}")
        print(f"  │ Top-K used:        {result['top_passages']}")
        print(f"  │ Avg score:         {result['avg_score']}")
        print(f"  │ Partial results:   {'YES ⚠' if result['partial'] else 'No'}")
        print(f"  └────────────────────────────────────────────────┘")

    # ── Summary ──────────────────────────────────────────
    print(f"\n{'═' * 70}")
    print("  CLINICAL RAG SUMMARY")
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
