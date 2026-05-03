# Enterprise Multi-Agent Architecture with Amazon Bedrock AgentCore

**Udacity - School of AI | Course 3.3 | Capstone Project 3.3 NovaMart**

A production-grade multi-agent customer support system built with the [Strands Agents SDK](https://github.com/strands-agents/sdk-python) and Amazon Bedrock AgentCore. The system automatically routes customer support requests to specialist agents, retrieves grounded knowledge via **parallel multi-agent RAG**, enforces enterprise safety guardrails, and maintains shared workflow state across agents - all observable through CloudWatch and X-Ray.

<img width="1140" height="824" alt="image" src="https://github.com/user-attachments/assets/d4495058-cde6-4d7f-beac-d1405ac6ef07" />




---

## Architecture

```
Customer Request
      │
OrchestratorAgent (Claude 3 Haiku - routes requests, manages WorkflowState)
      │
   ┌──┼──────────────────────────┬──────────────────┐
   │  │                          │                  │
InventoryAgent    PolicyAgent    RefundAgent    CommunicationAgent
(DynamoDB)     (Multi-Agent RAG)  (DynamoDB)     (synthesizes response)
                     │
         ┌───────────┼───────────┐
    ReturnsPolicyRetriever  ShippingPolicyRetriever  WarrantyPolicyRetriever
    (Bedrock KB)          (Bedrock KB)              (Bedrock KB)
         └───────── run in PARALLEL ───────────┘

Shared State: DynamoDB WorkflowStateTable (with optimistic locking)
```
### Agent Roles

| Agent | Model | Responsibility | Tools |
|-------|-------|-----------------|-------|
| **OrchestratorAgent** | Claude 3 Haiku | Routes requests, creates/updates WorkflowState | `initialize_session`, `route_to_inventory_agent`, `route_to_policy_agent`, `route_to_refund_agent`, `route_to_communication_agent` |
| **InventoryAgent** | Claude 3 Sonnet | Gathers order and customer facts from DynamoDB | `check_order_status`, `get_customer_tier`, `list_customer_orders` |
| **PolicyAgent** | Claude 3 Sonnet | Coordinates parallel RAG retrieval from 3 KBs, synthesizes results | `search_all_policies` (internally fans out to 3 retriever sub-agents) |
| **RefundAgent** | Claude 3 Sonnet | Makes return/refund eligibility decisions (30-day Standard, 60-day Premium) | `get_inventory_context`, `initiate_refund` |
| **CommunicationAgent** | Claude 3 Sonnet | Drafts final, empathetic customer-facing response | `get_full_workflow_context` |

<img width="1165" height="842" alt="image" src="https://github.com/user-attachments/assets/8eb93bb7-3e04-4551-afe0-cdecc5130fe9" />







### Key Features

- **Multi-Agent RAG**: PolicyAgent runs 3 specialized retriever sub-agents in parallel using ThreadPoolExecutor, merges results, and deduplicates by relevance
- **Shared Workflow State**: DynamoDB `WorkflowStateTable` with optimistic locking (version-based conditional writes) ensures consistency across concurrent agent updates
- **Enterprise Guardrails**: Bedrock Guardrails block harmful content, PII, and off-topic conversations
- **Observability**: Full tracing via CloudWatch Logs and AWS X-Ray for debugging and performance analysis
- **Bedrock Knowledge Bases**: Uses S3-backed vector store for policy retrieval (no custom embeddings)

---
<img width="1164" height="803" alt="image" src="https://github.com/user-attachments/assets/80a022a7-f801-4665-a9ef-72b47403757f" />



## Prerequisites

- Python 3.11+
- AWS account with Bedrock access enabled (`us-east-1` region)
- IAM permissions for: Bedrock, DynamoDB, S3, CloudWatch, X-Ray
- Bedrock Knowledge Bases created manually in AWS Console (Task 5)

---

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
# Copy .env template
cp .env.example .env

# Verify AWS resources
python config.py
```

Expected output: Configuration table showing all resource names. Fields showing `(not yet created)` are expected - they are populated as each task is completed.

### 3. Seed Initial Data (Optional)

The workspace provisioner runs this automatically, but if needed manually:

```bash
python infrastructure/seed_data.py
```

This populates:
- DynamoDB tables with mock customers and orders
- S3 `policy-docs` bucket with sample policy documents

---

## Project Structure

```
starter/
│
├── config.py                              # Central configuration (reads CloudFormation exports + env vars)
├── requirements.txt                       # Python dependencies
├── .env.example                           # Environment variable template
├── README.md                              # This file
│
├── src/                                   # Implementation files
│   ├── agent_orchestrator.py             # Multi-agent orchestration (Tasks 2, 3, 4, 6) ⭐
│   ├── agent_utils.py                    # Pre-written: terminal trace UI utilities
│   ├── bedrock_kb_retrieval.py           # Pre-written: KB retrieval helper
│   └── demo.py                           # Pre-written: demo script
│
├── infrastructure/
│   ├── starter_stack.yaml                 # CloudFormation: foundation infra (DynamoDB, S3, IAM, CloudWatch)
│   └── seed_data.py                       # Data seeding script
│
└── tests/
    └── test_agent.py                      # Automated test suite
```

### Files to Never Modify
- `config.py` - Central configuration
- `tests/test_agent.py` - Automated tests
- `infrastructure/` - Pre-deployed resources
- `src/agent_utils.py` - Terminal trace UI utilities
- `src/bedrock_kb_retrieval.py` - KB retrieval helper
- `src/demo.py` - Demo script

---

## Tasks & Implementation

### Task 2 - Multi-Agent Graph
**File:** `src/agent_orchestrator.py`
**Time:** ~90 minutes

Implement 5 Strands Agents in an Orchestrator → Workers hierarchy:

#### **2.A - InventoryAgent** (TODOs 2.1–2.5)
Gathers order and customer facts from DynamoDB (no decisions).
- **Tools:** `check_order_status`, `get_customer_tier`, `list_customer_orders`
- **Model:** Claude 3 Sonnet | **Temperature:** 0.1

#### **2.B - RefundAgent** (TODOs 2.6–2.10)
Makes return/refund eligibility decisions based on customer tier and dates.
- **Tools:** `get_inventory_context`, `initiate_refund`
- **Model:** Claude 3 Sonnet | **Temperature:** 0.1

#### **2.C - PolicyAgent** (TODOs 2.11–2.17) ⭐
**Multi-Agent RAG Coordinator:** Runs 3 retriever sub-agents in parallel.
```
PolicyAgent
    ├─ ReturnsPolicyRetriever  → config.RETURNS_KB_ID
    ├─ ShippingPolicyRetriever → config.SHIPPING_KB_ID
    └─ WarrantyPolicyRetriever → config.WARRANTY_KB_ID
```
- **Tool:** `search_all_policies` - fans out to all 3 retrievers via ThreadPoolExecutor
- **Output:** Merged, deduplicated results ranked by relevance
- **Model:** Claude 3 Sonnet | **Temperature:** 0.2

#### **2.D - CommunicationAgent** (TODOs 2.18–2.21)
Composes final customer-facing response from accumulated WorkflowState.
- **Tools:** `get_full_workflow_context`
- **Model:** Claude 3 Sonnet | **Temperature:** 0.3

#### **2.E - OrchestratorAgent** (TODOs 2.22–2.29)
Routes requests and manages shared WorkflowState.

- **Tools:** `initialize_session`, `route_to_inventory_agent`, `route_to_policy_agent`, `route_to_refund_agent`, `route_to_communication_agent`
- **Model:** Claude 3 Haiku (fast, cost-efficient) | **Temperature:** 0.0 (deterministic)

The orchestrator system prompt must enforce these routing rules exactly:

| Rule | Trigger | Action |
|------|---------|--------|
| 1 | Every request, always | Call `initialize_session` first |
| 2 | Order status / return / refund requests | Call `route_to_inventory_agent` → then `route_to_refund_agent` |
| 3 | Policy meaning questions (windows, rates, terms) | Call `route_to_policy_agent` |
| 4 | Account questions ("what is my tier?", "am I premium?") | Call `route_to_inventory_agent` - **never** `route_to_policy_agent` (it only knows policy text, not customer data) |
| 5 | Math / calculation questions | Answer directly - no routing needed |
| 6 | Every request, always (last step) | Call `route_to_communication_agent` to compose the final reply |

> **CRITICAL:** The Orchestrator is **never** permitted to write the final customer-facing response itself. It must always delegate to `route_to_communication_agent` as its very last action - no exceptions, even when it believes it already has a complete answer.

**Test:**
```bash
python tests/test_agent.py task2
```

---

### Task 3 - AgentCore Runtime & Guardrails
**File:** `src/agent_orchestrator.py`

- **`create_guardrail()`** - Create Bedrock Guardrail with:
  - Content filtering: SEXUAL, VIOLENCE, HATE (HIGH strength) + INSULTS, MISCONDUCT (MEDIUM strength)
  - PII redaction (emails, phones anonymized; credit cards and SSNs blocked)
  - Topic blocking (competitor products, pricing negotiations, legal threats)
  - Profanity filtering

- **`deploy_to_agentcore_runtime()`** - Deploy orchestrator to AgentCore with guardrail attached

**Deploy & Test:**
```bash
python src/agent_orchestrator.py deploy
```

The deploy command prints the Runtime ARN and Guardrail ID/Version on completion. Copy those values into your `.env` file:

```
AGENTCORE_RUNTIME_ARN=<printed arn>
GUARDRAIL_ID=<printed id>
GUARDRAIL_VERSION=<printed version>
```

Then run the tests:
```bash
python tests/test_agent.py task3
```

---

### Task 4 - Memory
**File:** `src/agent_orchestrator.py`

- **`configure_memory(runtime_arn)`** - Enable AgentCore Memory:
  - Type: SESSION_SUMMARY
  - Storage: 7 days
  - Maintains conversation context across turns so customers don't repeat themselves between turns

**Test:**
```bash
python tests/test_agent.py task4
```

---

### Task 5 - Bedrock Knowledge Bases (Not in starter - done in AWS Console)

Create 3 Knowledge Bases in the AWS Console. The S3 bucket and vector store are the same for all three - only the prefix differs:

| Setting | Returns KB | Shipping KB | Warranty KB |
|---|---|---|---|
| S3 bucket | `udacity-agentcore-policy-docs-{ACCOUNT_ID}` | same | same |
| S3 prefix | `policies/returns/` | `policies/shipping/` | `policies/warranty/` |
| Embedding model | `amazon.titan-embed-text-v2:0` | same | same |
| Vector store bucket | `udacity-agentcore-vectors-{ACCOUNT_ID}` | same | same |

After creating all three KBs, add their IDs to `.env`:
```
RETURNS_KB_ID=
SHIPPING_KB_ID=
WARRANTY_KB_ID=
```

**Test:**
```bash
python tests/test_agent.py task5
```

---

### Task 6 - Observability
**File:** `src/agent_orchestrator.py`

- **`configure_observability(runtime_arn)`** - Enable logging and tracing:
  - **CloudWatch:** INFO-level logs to `/aws/bedrock/agentcore/udacity-agentcore`
  - **X-Ray:** 100% sampling (100% in dev, reduce to 5% in prod)
  - Use `agentcore_control.put_agent_runtime_logging_configuration()` wrapped in `try/except`

**After testing, verify end-to-end tracing:**
```bash
python tests/test_agent.py task6

# Then run a live test
python src/agent_orchestrator.py test

# View traces in AWS Console → X-Ray → Service map
```

---

### Deployment Pipeline

When you run `python src/agent_orchestrator.py deploy`, it executes a 6-step pipeline:

| Step | What it does |
|------|-------------|
| 1/6 | Build the 5-agent graph locally |
| 2/6 | Create the Bedrock Guardrail |
| 3/6 | Deploy to AgentCore Runtime |
| 4/6 | Configure AgentCore Memory |
| 5/6 | Configure Observability (CloudWatch + X-Ray) |
| 6/6 | Deploy AgentCore Gateway *(skipped if Lambda tool functions not deployed)* |

Step 6 is pre-written scaffolding — it registers your Lambda-backed tool APIs on a managed MCP endpoint so agents can discover and invoke them at runtime. It requires Lambda functions to be deployed separately and their names set as `ORDERS_FUNCTION`, `POLICY_FUNCTION`, `CUSTOMERS_FUNCTION` in your `.env`. If those aren't set, Step 6 prints a note and the rest of the deployment completes normally.

---

### Task 7 - End-to-End Submission Test

After completing all tasks, run the full deployment and verify these three scenarios manually:

| Scenario | Expected Routing |
|----------|-----------------|
| `"I want to return my order ORD-12345"` | Orchestrator → Inventory → Refund → Communication |
| `"What is the return policy for premium customers?"` | Orchestrator → Policy (3 parallel KB retrievers) → Communication |
| `"How much are 5 items at $29.99 with 10% off?"` | Orchestrator answers directly (no sub-agent routing needed) |

**Required deliverable:** Take a screenshot of your **X-Ray Service Map** after running a live request (`python src/agent_orchestrator.py test`). Navigate to **AWS Console → X-Ray → Service map** and capture the full trace graph showing the Orchestrator → Worker call chain.

---

## Testing

### Automated Tests

Run individual task tests:
```bash
python tests/test_agent.py task2   # Multi-agent orchestration
python tests/test_agent.py task3   # AgentCore deployment
python tests/test_agent.py task4   # Memory
python tests/test_agent.py task5   # Knowledge base retrieval
python tests/test_agent.py task6   # Observability
```

Run full suite:
```bash
python tests/test_agent.py all
```

Expected output:
- Color-coded test results (✓ pass, ✗ fail)
- Summary at the end

### Live Testing

Run 3 hardcoded end-to-end scenarios against your local agent:
```bash
python src/agent_orchestrator.py test
```

Launch an interactive terminal session with step-by-step trace output:
```bash
python src/agent_orchestrator.py chat
```

The `chat` command opens a conversation loop where you type queries and watch the orchestrator route them in real time - colour-coded by agent (Inventory, Policy, Refund, Communication). It uses a pre-written terminal UI (`AgentTrace` / `_TraceWriter`) built into `agent_orchestrator.py`. **This scaffolding is pre-implemented and requires no modification.**

---

## Infrastructure

The foundation infrastructure is defined in `infrastructure/starter_stack.yaml` and provisions DynamoDB tables, S3 buckets, IAM roles, and CloudWatch log groups.

> The Udacity workspace comes with this stack pre-deployed. The student workflow does not involve running the stack - the AI layer is built on top via code.

---

## Deployment

Full end-to-end deployment:
```bash
python src/agent_orchestrator.py deploy
```

This:
1. Builds all 5 agents
2. Creates guardrail
3. Deploys to AgentCore Runtime
4. Configures memory
5. Enables observability

---

## Key Concepts

### Strands Agents
```python
from strands import Agent, tool
from strands.models import BedrockModel

@tool
def my_tool(param: str) -> str:
    """Agent reads this docstring to understand when to use the tool."""
    return f"Result: {param}"

model = BedrockModel(model_id="...", region_name="us-east-1", temperature=0.1)
agent = Agent(model=model, system_prompt="You are...", tools=[my_tool])
response = agent("Hello!")  # Call agent like a function
```

### WorkflowState Pattern
```python
# Create at session start
state = _create_workflow_state(session_id)

# Read in tools
current_state = _read_workflow_state(session_id)

# Update with optimistic locking
updated_state = _update_workflow_state(
    session_id,
    updates={'inventory_agent': agent_response},
    expected_version=current_state['version']
)
```

### Parallel Execution (Multi-Agent RAG)
```python
from concurrent.futures import ThreadPoolExecutor, as_completed

with ThreadPoolExecutor(max_workers=3) as executor:
    futures = {
        executor.submit(returns_retriever, query): 'returns',
        executor.submit(shipping_retriever, query): 'shipping',
        executor.submit(warranty_retriever, query): 'warranty',
    }
    for future in as_completed(futures):
        policy_type = futures[future]
        results[policy_type] = future.result()
```

---

## Documentation & Resources

- [Strands Agents SDK](https://github.com/strands-agents/sdk-python)
- [Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/)
- [Bedrock Knowledge Bases](https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base.html)
- [Bedrock Guardrails](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-create.html)
- [DynamoDB Optimistic Locking](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis.html)

---

## Environment Variables

The `.env` file holds values that are populated progressively as each task is completed:

```bash
# AWS Settings
AWS_REGION=us-east-1
PROJECT_NAME=udacity-agentcore

# Most AWS resource names/ARNs (DynamoDB tables, S3 buckets, IAM role, log group)
# are loaded automatically from CloudFormation exports - no entries needed here.

# Bedrock Knowledge Base IDs (Task 5) - create manually in AWS Console
RETURNS_KB_ID=
SHIPPING_KB_ID=
WARRANTY_KB_ID=

# AgentCore Runtime (Task 3) - populated by: python src/agent_orchestrator.py deploy
AGENTCORE_RUNTIME_ARN=

# Guardrail (Task 3) - populated by the deploy command above
GUARDRAIL_ID=
GUARDRAIL_VERSION=DRAFT
```

---

## Troubleshooting

**Config loading errors?**
```bash
python config.py
```
`config.py` resolves values differently depending on the variable type - always run `python config.py` first to see exactly what is and isn't loaded.

| Variable | Where it comes from | What to do if missing |
|---|---|---|
| DynamoDB tables, S3 buckets, IAM role, log group | CloudFormation exports only - no `.env` fallback | Verify stack `udacity-agentcore` is deployed; contact your workspace administrator |
| `RETURNS_KB_ID`, `SHIPPING_KB_ID`, `WARRANTY_KB_ID` | `.env` file (student path) | Complete Task 5 - create KBs in AWS Console, then paste IDs into `.env` |
| `AGENTCORE_RUNTIME_ARN` | `.env` file only | Complete Task 3 - run `python src/agent_orchestrator.py deploy`, then paste the output ARN into `.env` |
| `GUARDRAIL_ID`, `GUARDRAIL_VERSION` | `.env` file (student path) | Complete Task 3 - the deploy command prints these values; paste them into `.env` |

> **Note:** KB ID fields showing `(not yet created)` in `config.py` output is **expected** before Task 5 is completed. This is not an error - it indicates Knowledge Bases have not yet been created.

**Agent tool errors?**
Check agent system prompts and tool docstrings - agents read docstrings to understand tools.

**WorkflowState conflicts?**
Review `_update_workflow_state()` logic - optimistic locking retries on version conflicts.

**X-Ray traces not appearing?**
Ensure `configure_observability()` is called and sampling rate is > 0.

---

## License

[License](../../LICENSE.md)
