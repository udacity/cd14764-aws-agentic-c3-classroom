"""
hr_onboarding.py - DEMO (Instructor-Led)
Module 4: Orchestrating an HR Employee Onboarding Workflow

6 worker agents in 3 phases: SEQUENTIAL (account→manager) → PARALLEL (laptop+email+building)
→ CONDITIONAL (engineering vs sales). Orchestrator is Python code (deterministic, testable).

Tech: Strands Agents SDK, Amazon Bedrock (Claude/Nova Lite), ThreadPoolExecutor
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


# Configuration
AWS_REGION = "us-east-1"
CLAUDE_MODEL = "anthropic.claude-3-sonnet-20240229-v1:0"     # Orchestrator (reasoning)
NOVA_LITE_MODEL = "amazon.nova-lite-v1:0"                    # Workers (fast execution)

# Sample employees
EMPLOYEES = [
    {
        "id": "EMP-001",
        "name": "Alice Chen",
        "department": "Engineering",
        "role": "Senior Backend Engineer",
        "start_date": "2025-04-01",
        "equipment": "MacBook Pro M3, 32GB RAM",
        "access_level": "L4",
    },
    {
        "id": "EMP-002",
        "name": "Bob Martinez",
        "department": "Sales",
        "role": "Enterprise Account Executive",
        "start_date": "2025-04-01",
        "equipment": "Dell Latitude 15, 16GB RAM",
        "access_level": "L2",
    },
    {
        "id": "EMP-003",
        "name": "Carol Johnson",
        "department": "Engineering",
        "role": "DevOps Engineer",
        "start_date": "2025-04-15",
        "equipment": "MacBook Pro M3, 64GB RAM",
        "access_level": "L5",
        "simulate_failure": True,  # Laptop provisioning will fail on first attempt
    },
]

# ── Pre-defined results for deterministic output ──
MANAGER_ASSIGNMENTS = {
    "Engineering": {"manager": "David Kim", "manager_id": "MGR-ENG-01"},
    "Sales": {"manager": "Sarah Lee", "manager_id": "MGR-SALES-01"},
}

ENGINEERING_ONBOARDING = {
    "tools": ["GitHub Enterprise", "Jira", "AWS Console", "PagerDuty"],
    "slack_channels": ["#engineering", "#deployments", "#incidents"],
    "training": ["AWS Security Fundamentals", "CI/CD Pipeline Overview", "Code Review Guidelines"],
}

SALES_ONBOARDING = {
    "tools": ["Salesforce", "HubSpot", "Gong", "LinkedIn Sales Navigator"],
    "slack_channels": ["#sales", "#deals", "#customer-success"],
    "training": ["Product Deep Dive", "Sales Methodology", "CRM Best Practices"],
}

# Shared workflow state — orchestrator writes, main() reads
workflow_state = {}


# Worker agents — Simple, single-responsibility (orchestrator manages them)

# Phase 1: Sequential Workers

def build_account_creator() -> Agent:
    """Worker: Creates the employee account (must run FIRST)."""
    # STEP 1: BedrockModel (Nova Lite, temperature 0.0)
    model = BedrockModel(model_id=NOVA_LITE_MODEL, region_name=AWS_REGION, temperature=0.0)

    # STEP 2: System prompt
    system_prompt = """You are an account creation agent. Your ONLY job:
1. Call create_account with the employee_id
2. Report: Account created for <name> (ID: <employee_id>)
Do NOT add any other commentary."""

    @tool
    def create_account(employee_id: str) -> str:
        """Create a new employee account in the HR system."""
        emp = next((e for e in EMPLOYEES if e["id"] == employee_id), None)
        if not emp:
            return json.dumps({"error": f"Employee {employee_id} not found"})

        result = {
            "employee_id": employee_id,
            "name": emp["name"],
            "email": f"{emp['name'].lower().replace(' ', '.')}@company.com",
            "department": emp["department"],
            "access_level": emp["access_level"],
            "status": "active",
        }
        workflow_state["account"] = result
        return json.dumps(result, indent=2)

    # STEP 3: Build Agent
    return Agent(model=model, system_prompt=system_prompt, tools=[create_account])


def build_manager_assigner() -> Agent:
    """Worker: Assigns a manager (must run AFTER account creation)."""

    model = BedrockModel(model_id=NOVA_LITE_MODEL, region_name=AWS_REGION, temperature=0.0)

    system_prompt = """You are a manager assignment agent. Your ONLY job:
1. Call assign_manager with the employee_id
2. Report: Manager <name> assigned to <employee_name>
Do NOT add any other commentary."""

    @tool
    def assign_manager(employee_id: str) -> str:
        """
        Assign a department manager to the new employee.

        Args:
            employee_id: The employee ID

        Returns:
            JSON with manager assignment details
        """
        emp = next((e for e in EMPLOYEES if e["id"] == employee_id), None)
        if not emp:
            return json.dumps({"error": f"Employee {employee_id} not found"})

        mgr = MANAGER_ASSIGNMENTS.get(emp["department"], {})
        result = {
            "employee_id": employee_id,
            "manager": mgr.get("manager", "Unassigned"),
            "manager_id": mgr.get("manager_id", "N/A"),
            "department": emp["department"],
        }
        workflow_state["manager"] = result
        return json.dumps(result, indent=2)

    return Agent(model=model, system_prompt=system_prompt, tools=[assign_manager])


# ── Phase 2: Parallel Workers ───────────────────────

def build_laptop_provisioner() -> Agent:
    """Worker: Provisions laptop (can run in PARALLEL with email/building)."""

    model = BedrockModel(model_id=NOVA_LITE_MODEL, region_name=AWS_REGION, temperature=0.0)

    system_prompt = """You are a laptop provisioning agent. Your ONLY job:
1. Call provision_laptop with the employee_id
2. Report: Laptop provisioned for <name>: <equipment>
Do NOT add any other commentary."""

    @tool
    def provision_laptop(employee_id: str) -> str:
        """
        Provision a laptop for the new employee.

        Args:
            employee_id: The employee ID

        Returns:
            JSON with laptop provisioning details
        """
        emp = next((e for e in EMPLOYEES if e["id"] == employee_id), None)
        if not emp:
            return json.dumps({"error": f"Employee {employee_id} not found"})

        # Simulate failure for EMP-003 on first attempt
        if emp.get("simulate_failure") and "laptop_attempts" not in workflow_state:
            workflow_state["laptop_attempts"] = 1
            return json.dumps({"error": "Provisioning system temporarily unavailable", "retry": True})

        result = {
            "employee_id": employee_id,
            "equipment": emp["equipment"],
            "asset_tag": f"ASSET-{employee_id[-3:]}-LP",
            "status": "provisioned",
            "ship_date": emp["start_date"],
        }
        workflow_state["laptop"] = result
        return json.dumps(result, indent=2)

    return Agent(model=model, system_prompt=system_prompt, tools=[provision_laptop])


def build_email_setup() -> Agent:
    """Worker: Sets up email (can run in PARALLEL with laptop/building)."""

    model = BedrockModel(model_id=NOVA_LITE_MODEL, region_name=AWS_REGION, temperature=0.0)

    system_prompt = """You are an email setup agent. Your ONLY job:
1. Call setup_email with the employee_id
2. Report: Email configured for <name>: <email>
Do NOT add any other commentary."""

    @tool
    def setup_email(employee_id: str) -> str:
        """
        Set up email and calendar for the new employee.

        Args:
            employee_id: The employee ID

        Returns:
            JSON with email setup details
        """
        emp = next((e for e in EMPLOYEES if e["id"] == employee_id), None)
        if not emp:
            return json.dumps({"error": f"Employee {employee_id} not found"})

        email = f"{emp['name'].lower().replace(' ', '.')}@company.com"
        result = {
            "employee_id": employee_id,
            "email": email,
            "calendar": True,
            "distribution_lists": [f"{emp['department'].lower()}-all@company.com"],
            "storage_quota": "50GB",
            "status": "active",
        }
        workflow_state["email"] = result
        return json.dumps(result, indent=2)

    return Agent(model=model, system_prompt=system_prompt, tools=[setup_email])


def build_building_access() -> Agent:
    """Worker: Grants building access (can run in PARALLEL with laptop/email)."""

    model = BedrockModel(model_id=NOVA_LITE_MODEL, region_name=AWS_REGION, temperature=0.0)

    system_prompt = """You are a building access agent. Your ONLY job:
1. Call grant_building_access with the employee_id
2. Report: Building access granted for <name>: Badge <badge_id>
Do NOT add any other commentary."""

    @tool
    def grant_building_access(employee_id: str) -> str:
        """
        Grant building and facility access to the new employee.

        Args:
            employee_id: The employee ID

        Returns:
            JSON with building access details
        """
        emp = next((e for e in EMPLOYEES if e["id"] == employee_id), None)
        if not emp:
            return json.dumps({"error": f"Employee {employee_id} not found"})

        result = {
            "employee_id": employee_id,
            "badge_id": f"BADGE-{employee_id[-3:]}",
            "access_zones": ["Main Lobby", "Floor 3", f"{emp['department']} Wing"],
            "parking": True,
            "status": "active",
        }
        workflow_state["building"] = result
        return json.dumps(result, indent=2)

    return Agent(model=model, system_prompt=system_prompt, tools=[grant_building_access])


# ── Phase 3: Conditional Workers ────────────────────

def build_engineering_onboarding() -> Agent:
    """Worker: Engineering-specific onboarding (conditional — only for engineers)."""

    model = BedrockModel(model_id=NOVA_LITE_MODEL, region_name=AWS_REGION, temperature=0.0)

    system_prompt = """You are an engineering onboarding agent. Your ONLY job:
1. Call onboard_engineer with the employee_id
2. Report: Engineering onboarding complete for <name>
Do NOT add any other commentary."""

    @tool
    def onboard_engineer(employee_id: str) -> str:
        """
        Run engineering-specific onboarding: dev tools, repos, Slack channels.

        Args:
            employee_id: The employee ID

        Returns:
            JSON with engineering onboarding details
        """
        emp = next((e for e in EMPLOYEES if e["id"] == employee_id), None)
        if not emp:
            return json.dumps({"error": f"Employee {employee_id} not found"})

        result = {
            "employee_id": employee_id,
            "tools_provisioned": ENGINEERING_ONBOARDING["tools"],
            "slack_channels": ENGINEERING_ONBOARDING["slack_channels"],
            "training_enrolled": ENGINEERING_ONBOARDING["training"],
            "department_path": "Engineering",
        }
        workflow_state["department_onboarding"] = result
        return json.dumps(result, indent=2)

    return Agent(model=model, system_prompt=system_prompt, tools=[onboard_engineer])


def build_sales_onboarding() -> Agent:
    """Worker: Sales-specific onboarding (conditional — only for sales)."""

    model = BedrockModel(model_id=NOVA_LITE_MODEL, region_name=AWS_REGION, temperature=0.0)

    system_prompt = """You are a sales onboarding agent. Your ONLY job:
1. Call onboard_sales with the employee_id
2. Report: Sales onboarding complete for <name>
Do NOT add any other commentary."""

    @tool
    def onboard_sales(employee_id: str) -> str:
        """
        Run sales-specific onboarding: CRM access, Slack channels, training.

        Args:
            employee_id: The employee ID

        Returns:
            JSON with sales onboarding details
        """
        emp = next((e for e in EMPLOYEES if e["id"] == employee_id), None)
        if not emp:
            return json.dumps({"error": f"Employee {employee_id} not found"})

        result = {
            "employee_id": employee_id,
            "tools_provisioned": SALES_ONBOARDING["tools"],
            "slack_channels": SALES_ONBOARDING["slack_channels"],
            "training_enrolled": SALES_ONBOARDING["training"],
            "department_path": "Sales",
        }
        workflow_state["department_onboarding"] = result
        return json.dumps(result, indent=2)

    return Agent(model=model, system_prompt=system_prompt, tools=[onboard_sales])


# Orchestrator — Manages entire workflow with Python code (deterministic, testable, debuggable)

def orchestrate_onboarding(employee_id: str) -> dict:
    """
    Run the complete onboarding workflow for a new employee.

    Flow:
        Phase 1 (SEQUENTIAL):  AccountCreator → ManagerAssigner
        Phase 2 (PARALLEL):    LaptopProvisioner + EmailSetup + BuildingAccess
        Phase 3 (CONDITIONAL): EngineeringOnboarding OR SalesOnboarding

    Includes failure handling with retries and backoff.

    Args:
        employee_id: The employee ID to onboard

    Returns:
        Dict with phase timings and results
    """
    emp = next((e for e in EMPLOYEES if e["id"] == employee_id), None)
    if not emp:
        return {"error": f"Employee {employee_id} not found"}

    timings = {}

    # ══════════════════════════════════════════════════
    # PHASE 1: SEQUENTIAL — Account must exist before manager assignment
    # These steps DEPEND on each other: manager needs the account ID.
    # ══════════════════════════════════════════════════
    print(f"\n  ── Phase 1: SEQUENTIAL (account → manager) ──")

    print(f"    [1/2] Creating account...")
    timings["account"] = run_agent_with_retry(
        build_account_creator,
        f"Create account for employee {employee_id}",
    )
    print(f"    Account created ({timings['account']:.1f}s)")

    print(f"    [2/2] Assigning manager...")
    timings["manager"] = run_agent_with_retry(
        build_manager_assigner,
        f"Assign manager for employee {employee_id}",
    )
    mgr = workflow_state.get("manager", {})
    print(f"    Manager: {mgr.get('manager', '?')} ({timings['manager']:.1f}s)")

    phase1_time = timings["account"] + timings["manager"]
    print(f"    Phase 1 total: {phase1_time:.1f}s")

    # ══════════════════════════════════════════════════
    # PHASE 2: PARALLEL — Laptop, email, building access
    # These are INDEPENDENT: none needs the other's output.
    # Same ThreadPoolExecutor pattern from Module 3.
    # ══════════════════════════════════════════════════
    print(f"\n  ── Phase 2: PARALLEL (laptop + email + building) ──")

    def run_laptop():
        return run_agent_with_retry(
            build_laptop_provisioner,
            f"Provision laptop for employee {employee_id}",
        )

    def run_email():
        return run_agent_with_retry(
            build_email_setup,
            f"Set up email for employee {employee_id}",
        )

    def run_building():
        return run_agent_with_retry(
            build_building_access,
            f"Grant building access for employee {employee_id}",
        )

    t_parallel_start = time.time()
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(run_laptop): "laptop",
            executor.submit(run_email): "email",
            executor.submit(run_building): "building",
        }
        for future in as_completed(futures):
            name = futures[future]
            timings[name] = future.result()

    phase2_time = time.time() - t_parallel_start
    print(f"    Laptop: {timings.get('laptop', 0):.1f}s | Email: {timings.get('email', 0):.1f}s | Building: {timings.get('building', 0):.1f}s")
    print(f"    Phase 2 total: {phase2_time:.1f}s (parallel)")

    # ══════════════════════════════════════════════════
    # PHASE 3: CONDITIONAL — Route based on department
    # This is a CODE decision, not an LLM decision.
    # Deterministic routing: department field → specific agent.
    # ══════════════════════════════════════════════════
    print(f"\n  ── Phase 3: CONDITIONAL (department routing) ──")
    department = emp["department"]

    if department == "Engineering":
        print(f"    Routing to Engineering onboarding...")
        timings["dept_onboarding"] = run_agent_with_retry(
            build_engineering_onboarding,
            f"Run engineering onboarding for employee {employee_id}",
        )
    elif department == "Sales":
        print(f"    Routing to Sales onboarding...")
        timings["dept_onboarding"] = run_agent_with_retry(
            build_sales_onboarding,
            f"Run sales onboarding for employee {employee_id}",
        )
    else:
        print(f"    Unknown department: {department} — skipping department onboarding")
        timings["dept_onboarding"] = 0

    dept = workflow_state.get("department_onboarding", {})
    print(f"    {department} onboarding complete ({timings['dept_onboarding']:.1f}s)")
    print(f"    Tools: {', '.join(dept.get('tools_provisioned', []))}")

    phase3_time = timings["dept_onboarding"]

    return {
        "phase1_sequential": phase1_time,
        "phase2_parallel": phase2_time,
        "phase3_conditional": phase3_time,
        "total": phase1_time + phase2_time + phase3_time,
        "timings": timings,
    }


# Main

def main():
    print("=" * 65)
    print("  HR Employee Onboarding — Module 4 Demo")
    print("  Sequential + Parallel + Conditional Orchestration")
    print("  6 Worker Agents managed by Python orchestrator")
    print("=" * 65)

    results = []

    for emp in EMPLOYEES:
        emp_id = emp["id"]
        print(f"\n{'━' * 65}")
        print(f"  Employee: {emp_id} — {emp['name']}")
        print(f"  Department: {emp['department']} | Role: {emp['role']}")
        print(f"  Start Date: {emp['start_date']}")
        if emp.get("simulate_failure"):
            print(f"  ⚠ Simulated failure: laptop provisioning will fail first attempt")
        print(f"{'━' * 65}")

        # Clear workflow state for this employee
        workflow_state.clear()

        result = orchestrate_onboarding(emp_id)

        # Display summary
        acct = workflow_state.get("account", {})
        mgr = workflow_state.get("manager", {})
        laptop = workflow_state.get("laptop", {})
        email = workflow_state.get("email", {})
        building = workflow_state.get("building", {})
        dept = workflow_state.get("department_onboarding", {})

        print(f"\n  ┌─── Onboarding Summary ─────────────────────────┐")
        print(f"  │ Account:  {acct.get('email', '?')} ({acct.get('access_level', '?')})")
        print(f"  │ Manager:  {mgr.get('manager', '?')}")
        print(f"  │ Laptop:   {laptop.get('equipment', '?')} ({laptop.get('asset_tag', '?')})")
        print(f"  │ Email:    {email.get('email', '?')}")
        print(f"  │ Building: Badge {building.get('badge_id', '?')} — {', '.join(building.get('access_zones', []))}")
        print(f"  │ Path:     {dept.get('department_path', '?')} onboarding")
        print(f"  │ Training: {', '.join(dept.get('training_enrolled', []))}")
        print(f"  └────────────────────────────────────────────────┘")
        print(f"  Phase 1 (sequential): {result['phase1_sequential']:.1f}s")
        print(f"  Phase 2 (parallel):   {result['phase2_parallel']:.1f}s")
        print(f"  Phase 3 (conditional):{result['phase3_conditional']:.1f}s")
        print(f"  Total:                {result['total']:.1f}s")

        results.append({
            "employee": emp_id,
            "name": emp["name"],
            "department": emp["department"],
            "path": emp["department"],
            "total_s": round(result["total"], 1),
            "seq_s": round(result["phase1_sequential"], 1),
            "par_s": round(result["phase2_parallel"], 1),
            "cond_s": round(result["phase3_conditional"], 1),
        })

    # ── Summary Table ────────────────────────────────────
    print(f"\n{'═' * 65}")
    print("  ORCHESTRATION SUMMARY")
    print(f"{'═' * 65}")
    print(f"  {'Employee':<10} {'Name':<18} {'Path':<12} {'Seq.':<7} {'Par.':<7} {'Cond.':<7} {'Total':<7}")
    print(f"  {'─' * 63}")
    for r in results:
        print(f"  {r['employee']:<10} {r['name']:<18} {r['path']:<12} {r['seq_s']:<7.1f} {r['par_s']:<7.1f} {r['cond_s']:<7.1f} {r['total_s']:<7.1f}")

    print(f"\n  Key Insight: Orchestration combines three patterns in one workflow:")
    print(f"  1. SEQUENTIAL — when steps depend on each other (account → manager)")
    print(f"  2. PARALLEL   — when steps are independent (laptop + email + building)")
    print(f"  3. CONDITIONAL — when the path depends on data (department routing)")
    print(f"  The orchestrator is Python code, not an LLM — deterministic, debuggable,")
    print(f"  and testable. Worker agents stay simple and stateless.\n")


if __name__ == "__main__":
    main()
