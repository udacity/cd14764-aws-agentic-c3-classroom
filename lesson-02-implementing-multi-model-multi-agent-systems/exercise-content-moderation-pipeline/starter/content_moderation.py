"""
content_moderation.py - STARTER
==================================
Module 2 Exercise: Multi-Model Content Moderation Pipeline

Architecture:
    Social Media Post
         │
    ┌────┴────────────────────┐
    │         │               │
  Screening  Deep Review   Notice
  Agent      Agent         Agent
(Nova Lite) (Claude)     (Nova Pro)
  all posts  borderline   harmful
             only         only

Pipeline:
  1. Nova Lite screens ALL posts (fast: safe/harmful/borderline)
  2. Claude reviews ONLY borderline posts (deep context analysis)
  3. Nova Pro generates notices for harmful posts only

YOUR TASK: Complete the 3 TODOs to build each agent with its model.

  PATTERN: Follow the same 3 steps shown in the demo (incident_response.py):
    Each build function needs:
      Step 1 → BedrockModel(model_id=<MODEL_CONSTANT>, region_name=..., temperature=...)
      Step 2 → system_prompt = "..." (tell agent which tool to call and what to report)
      Step 3 → return Agent(model=model, system_prompt=system_prompt, tools=[...])

Tech Stack:
  - Python 3.11+
  - Strands Agents SDK (Agent class, @tool decorator)
  - Amazon Bedrock (Nova Lite, Claude 3 Sonnet, Nova Pro)
"""

import json
import os
import time
import logging
from dotenv import load_dotenv
from strands import Agent, tool
from strands.models import BedrockModel

load_dotenv()

logging.basicConfig(level=logging.WARNING)

# ─────────────────────────────────────────────────────
# CONFIGURATION — Three different models
# ─────────────────────────────────────────────────────
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
NOVA_LITE_MODEL = os.environ.get("NOVA_LITE_MODEL", "amazon.nova-lite-v1:0")                    # Fast screening
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "us.anthropic.claude-sonnet-4-20250514-v1:0")     # Deep review
NOVA_PRO_MODEL = os.environ.get("NOVA_PRO_MODEL", "amazon.nova-pro-v1:0")                      # Notice drafting

# ─────────────────────────────────────────────────────
# SAMPLE POSTS (9 posts: 3 safe, 3 harmful, 3 borderline)
# ─────────────────────────────────────────────────────
POSTS = [
    # ── Clearly SAFE ──
    {"id": "POST-001", "user": "foodie_fan",    "text": "Just made the best homemade pasta! Garlic, olive oil, fresh basil. Highly recommend trying it this weekend."},
    {"id": "POST-002", "user": "nature_lover",  "text": "The sunset tonight was absolutely breathtaking. Nature never disappoints."},
    {"id": "POST-003", "user": "bookworm42",    "text": "Just finished an amazing book on machine learning. Really opened my mind to how AI works."},

    # ── Clearly HARMFUL ──
    {"id": "POST-004", "user": "angry_troll",   "text": "I will destroy anyone who disagrees with me. You all deserve to suffer for your opinions."},
    {"id": "POST-005", "user": "scammer_99",    "text": "Buy my miracle weight loss pills NOW! Guaranteed 30lbs in 5 days or money back! Click this link immediately!"},
    {"id": "POST-006", "user": "hate_account",  "text": "That entire group of people is subhuman garbage and should be removed from society permanently."},

    # ── BORDERLINE (need deeper analysis) ──
    {"id": "POST-007", "user": "frustrated_cx",  "text": "This new company policy is absolutely terrible. The people who wrote it must be complete idiots who never talked to customers."},
    {"id": "POST-008", "user": "health_tips",    "text": "My friend told me this herbal supplement completely cured their diabetes. You should definitely try it too instead of medication!"},
    {"id": "POST-009", "user": "movie_critic",   "text": "That movie was so bad it made me want to gouge my eyes out. Worst 2 hours of my entire life. The director should be banned from filmmaking."},
]

# ── Screening rules (keyword-based, fast) ──
HARMFUL_KEYWORDS = ["destroy", "suffer", "subhuman", "removed from society", "miracle", "guaranteed", "click this link"]
BORDERLINE_KEYWORDS = ["idiots", "terrible", "cured their", "gouge my eyes", "banned from", "instead of medication"]

# ── Deep review verdicts (pre-analyzed, deterministic) ──
DEEP_REVIEW_VERDICTS = {
    "POST-007": {"verdict": "safe",     "reason": "Strong opinion about company policy — frustration, not a threat. Protected speech."},
    "POST-008": {"verdict": "harmful",  "reason": "Health misinformation — encouraging people to replace medication with unverified supplements. Potential real-world harm."},
    "POST-009": {"verdict": "safe",     "reason": "Hyperbolic movie criticism — figurative language, not actual intent to harm. Common review style."},
}

# ── Moderation notice templates ──
NOTICE_TEMPLATES = {
    "harmful":   {"action": "removed",  "message": "Your post has been removed for violating community guidelines."},
    "warning":   {"action": "flagged",  "message": "Your post has been flagged for review. Please review our community guidelines."},
}

# Shared caches for cross-agent data passing
screening_cache = {}
review_cache = {}


# ═══════════════════════════════════════════════════════
#  AGENT 1: SCREENING AGENT  (Nova Lite — fast triage)
# ═══════════════════════════════════════════════════════

def build_screening_agent() -> Agent:
    """Build the Screening Agent using Nova Lite for fast initial classification."""

    # The tool is pre-written for you ──────────────────────

    @tool
    def screen_post(post_id: str) -> str:
        """
        Perform fast keyword-based screening of a social media post.

        Args:
            post_id: The post ID (e.g., "POST-001")

        Returns:
            JSON with initial classification (safe/harmful/borderline)
        """
        post = next((p for p in POSTS if p["id"] == post_id), None)
        if not post:
            return json.dumps({"error": f"Post {post_id} not found"})

        text_lower = post["text"].lower()

        if any(kw in text_lower for kw in HARMFUL_KEYWORDS):
            classification = "harmful"
            confidence = 0.95
        elif any(kw in text_lower for kw in BORDERLINE_KEYWORDS):
            classification = "borderline"
            confidence = 0.50
        else:
            classification = "safe"
            confidence = 0.90

        result = {
            "post_id": post_id,
            "user": post["user"],
            "classification": classification,
            "confidence": confidence,
            "text_preview": post["text"][:80],
        }
        screening_cache[post_id] = result
        return json.dumps(result, indent=2)

    # ── TODO 1 ─────────────────────────────────────────────
    # Create a BedrockModel using NOVA_LITE_MODEL for fast screening.
    # Then write a system prompt telling the agent to:
    #   - Call screen_post with the post_id
    #   - Report: Classification (SAFE|HARMFUL|BORDERLINE) and Confidence
    # Finally, return an Agent with the model, prompt, and tools=[screen_post]
    #
    # Hint: Use temperature=0.0 for deterministic classification
    # ───────────────────────────────────────────────────────
    pass  # Replace with your implementation


# ═══════════════════════════════════════════════════════
#  AGENT 2: DEEP REVIEW AGENT  (Claude — nuanced analysis)
# ═══════════════════════════════════════════════════════

def build_review_agent() -> Agent:
    """Build the Deep Review Agent using Claude for borderline case analysis."""

    # The tool is pre-written for you ──────────────────────

    @tool
    def deep_review_post(post_id: str) -> str:
        """
        Perform deep contextual analysis of a borderline post.

        Considers: satire, cultural context, hyperbole, misinformation risk.

        Args:
            post_id: The post ID flagged as borderline

        Returns:
            JSON with final verdict and reasoning
        """
        post = next((p for p in POSTS if p["id"] == post_id), None)
        if not post:
            return json.dumps({"error": f"Post {post_id} not found"})

        verdict_data = DEEP_REVIEW_VERDICTS.get(post_id, {
            "verdict": "safe",
            "reason": "No specific policy violation identified after deep review.",
        })

        result = {
            "post_id": post_id,
            "user": post["user"],
            "original_text": post["text"],
            "verdict": verdict_data["verdict"],
            "reason": verdict_data["reason"],
        }
        review_cache[post_id] = result
        return json.dumps(result, indent=2)

    # ── TODO 2 ─────────────────────────────────────────────
    # Create a BedrockModel using CLAUDE_MODEL for deep analysis.
    # Then write a system prompt telling the agent to:
    #   - Call deep_review_post with the post_id
    #   - Report: Verdict (SAFE|HARMFUL) and one-sentence Reason
    # Finally, return an Agent with the model, prompt, and tools=[deep_review_post]
    #
    # Hint: Use temperature=0.1 for analytical consistency
    # ───────────────────────────────────────────────────────
    pass  # Replace with your implementation


# ═══════════════════════════════════════════════════════
#  AGENT 3: NOTICE AGENT  (Nova Pro — moderation notices)
# ═══════════════════════════════════════════════════════

def build_notice_agent() -> Agent:
    """Build the Notice Agent using Nova Pro for moderation communications."""

    # The tool is pre-written for you ──────────────────────

    @tool
    def generate_notice(post_id: str, violation_type: str) -> str:
        """
        Generate a moderation notice for a post that violated guidelines.

        Args:
            post_id: The post ID
            violation_type: "harmful" or "warning"

        Returns:
            JSON with moderation action and notice text
        """
        post = next((p for p in POSTS if p["id"] == post_id), None)
        if not post:
            return json.dumps({"error": f"Post {post_id} not found"})

        template = NOTICE_TEMPLATES.get(violation_type, NOTICE_TEMPLATES["warning"])

        return json.dumps({
            "post_id": post_id,
            "user": post["user"],
            "action": template["action"],
            "notice": template["message"],
            "violation_type": violation_type,
            "text_preview": post["text"][:60],
        }, indent=2)

    # ── TODO 3 ─────────────────────────────────────────────
    # Create a BedrockModel using NOVA_PRO_MODEL for notice drafting.
    # Then write a system prompt telling the agent to:
    #   - Call generate_notice with post_id and violation_type
    #   - Report: Action (REMOVED|FLAGGED), Notice text, and Reason
    # Finally, return an Agent with the model, prompt, and tools=[generate_notice]
    #
    # Hint: Use temperature=0.3 for slightly creative communication
    # ───────────────────────────────────────────────────────
    pass  # Replace with your implementation


# ═══════════════════════════════════════════════════════
#  MAIN  (fully provided — do not modify)
# ═══════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("  Content Moderation Pipeline — Module 2 Exercise")
    print("  Nova Lite (screen) + Claude (review) + Nova Pro (notice)")
    print("=" * 70)

    latency_report = []
    results_summary = []

    for post in POSTS:
        post_id = post["id"]
        print(f"\n{'━' * 70}")
        print(f"  Post: {post_id} by @{post['user']}")
        print(f"  Text: {post['text'][:70]}...")
        print(f"{'━' * 70}")

        # ── Step 1: Screen with Nova Lite (ALL posts) ───────
        print(f"\n  [Agent 1] Screening (Nova Lite)")
        screening_agent = build_screening_agent()
        t1 = time.time()
        screen_result = screening_agent(f"Screen post {post_id}")
        screening_time = time.time() - t1
        classification = screening_cache.get(post_id, {}).get("classification", "safe")
        print(f"  Initial: {classification.upper()} ({screening_time:.1f}s)")

        review_time = 0.0
        notice_time = 0.0
        final_verdict = classification

        # ── Step 2: Deep review with Claude (BORDERLINE only) ──
        if classification == "borderline":
            print(f"\n  [Agent 2] Deep Review (Claude) — escalated")
            review_agent = build_review_agent()
            t2 = time.time()
            review_result = review_agent(f"Deep review post {post_id}")
            review_time = time.time() - t2
            final_verdict = review_cache.get(post_id, {}).get("verdict", "safe")
            reason = review_cache.get(post_id, {}).get("reason", "")
            print(f"  Verdict: {final_verdict.upper()} ({review_time:.1f}s)")
            print(f"  Reason: {reason}")
        elif classification == "safe":
            print(f"  >> Fast-tracked as SAFE (no Claude needed)")
            final_verdict = "safe"

        # ── Step 3: Notice with Nova Pro (HARMFUL only) ─────
        if final_verdict == "harmful":
            print(f"\n  [Agent 3] Notice (Nova Pro)")
            notice_agent = build_notice_agent()
            t3 = time.time()
            notice_result = notice_agent(
                f"Generate moderation notice for post {post_id}. Violation type is harmful."
            )
            notice_time = time.time() - t3
            print(f"  Notice sent ({notice_time:.1f}s)")

        total = screening_time + review_time + notice_time
        latency_report.append({
            "post": post_id,
            "path": "full" if classification == "borderline" else ("screen+notice" if classification == "harmful" else "fast-track"),
            "screen_s": round(screening_time, 1),
            "review_s": round(review_time, 1),
            "notice_s": round(notice_time, 1),
            "total_s": round(total, 1),
        })

        results_summary.append({
            "post_id": post_id,
            "user": post["user"],
            "initial": classification,
            "final": final_verdict,
        })

    # ── Results Summary ─────────────────────────────────────
    print(f"\n{'═' * 70}")
    print("  MODERATION RESULTS")
    print(f"{'═' * 70}")
    print(f"  {'Post':<10} {'User':<16} {'Screen':<12} {'Final':<10}")
    print(f"  {'─' * 48}")
    for r in results_summary:
        print(f"  {r['post_id']:<10} @{r['user']:<15} {r['initial']:<12} {r['final'].upper():<10}")

    safe_count = sum(1 for r in results_summary if r["final"] == "safe")
    harmful_count = sum(1 for r in results_summary if r["final"] == "harmful")
    print(f"\n  Safe: {safe_count} | Harmful: {harmful_count} | Total: {len(results_summary)}")

    # ── Latency Comparison ──────────────────────────────────
    print(f"\n{'═' * 70}")
    print("  LATENCY COMPARISON BY PATH")
    print(f"{'═' * 70}")
    print(f"  {'Post':<10} {'Path':<15} {'Screen':<9} {'Review':<9} {'Notice':<9} {'Total':<8}")
    print(f"  {'─' * 56}")
    for r in latency_report:
        print(f"  {r['post']:<10} {r['path']:<15} {r['screen_s']:<9.1f} {r['review_s']:<9.1f} {r['notice_s']:<9.1f} {r['total_s']:<8.1f}")

    fast_track = [r for r in latency_report if r["path"] == "fast-track"]
    full_pipeline = [r for r in latency_report if r["path"] == "full"]
    if fast_track and full_pipeline:
        avg_fast = sum(r["total_s"] for r in fast_track) / len(fast_track)
        avg_full = sum(r["total_s"] for r in full_pipeline) / len(full_pipeline)
        if avg_fast > 0:
            speedup = avg_full / avg_fast
            print(f"\n  Fast-track avg: {avg_fast:.1f}s | Full pipeline avg: {avg_full:.1f}s")
            print(f"  Fast-track is {speedup:.1f}x faster than full pipeline")

    print(f"\n  Key Insight: Safe posts (fast-track) skip Claude entirely,")
    print(f"  processing in Nova Lite only. This is the multi-model advantage:")
    print(f"  use the cheapest/fastest model for easy cases, reserve the")
    print(f"  expensive model for cases that truly need deep reasoning.\n")


if __name__ == "__main__":
    main()
