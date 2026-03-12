"""
demo.py
=======
Run one end-to-end customer support request to demonstrate the
multi-agent system locally (no AgentCore deployment needed).

Usage:
    python demo.py

For the full interactive chat experience, run:
    python agent_orchestrator.py chat
"""

import sys
import uuid

from agent_utils import _trace_writer, _real_stdout, _strip_xml_tags
from agent_orchestrator import (
    build_inventory_agent,
    build_refund_agent,
    build_policy_agent,
    build_communication_agent,
    build_orchestrator_agent,
    _read_workflow_state,
    trace,
)

# ── Build the agent graph ─────────────────────────────────────────────────────

print("Initializing agent graph...")
inventory_agent     = build_inventory_agent()
refund_agent        = build_refund_agent()
policy_agent        = build_policy_agent()
communication_agent = build_communication_agent()
orchestrator        = build_orchestrator_agent(
    inventory_agent, refund_agent, policy_agent, communication_agent
)
print("All 5 agents ready.\n")

# ── Demo request - exercises the full pipeline ────────────────────────────────
#   OrchestratorAgent -> InventoryAgent -> RefundAgent -> CommunicationAgent

CUSTOMER_ID = "CUST-001"
QUERY       = "I want to return my wireless headphones from order ORD-27176"

session_id = str(uuid.uuid4())[:8]
prompt     = f"[Session ID: {session_id}] [Customer ID: {CUSTOMER_ID}] {QUERY}"

print(f"Customer : {CUSTOMER_ID}  |  Session : {session_id}")
print(f"Query    : {QUERY}\n")

# ── Run the orchestrator with full trace output ───────────────────────────────
# _trace_writer intercepts Strands SDK output and reformats it:
#   "Tool #N: name"  ->  [TOOL CALL]  name
#   all other text   ->  | <text>      (agent reasoning)

trace.new_turn()
sys.stdout = _trace_writer
try:
    response = orchestrator(prompt)
finally:
    sys.stdout = _real_stdout   # always restore, even on exception

# ── Print workflow summary and final response ─────────────────────────────────

import time
trace.summary(session_id, elapsed=0)

state       = _read_workflow_state(session_id) or {}
comm_result = state.get('communication_agent', '')
text        = _strip_xml_tags(comm_result or str(response))

print(f"\n{'=' * 68}")
print("  AGENT RESPONSE")
print(f"{'=' * 68}")
for line in text.splitlines():
    print(f"  {line}")
print(f"{'=' * 68}\n")
