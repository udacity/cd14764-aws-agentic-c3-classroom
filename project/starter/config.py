"""
config.py
=========
Central configuration for the Udacity AgentCore project.
Reads resource names/ARNs from CloudFormation stack exports so
students never have to hard-code AWS resource identifiers.

Bedrock Knowledge Base IDs are NOT in CloudFormation - students create
these manually in the AWS Console and supply them via environment variables
(copy from .env.example → .env and fill in).

This file is pre-written. Students do not modify it.
"""

import boto3
import os
from dotenv import load_dotenv

# Load .env file if present (student-supplied KB IDs etc.)
load_dotenv()

# ─────────────────────────────────────────────
# REGION & PROJECT SETTINGS
# ─────────────────────────────────────────────
AWS_REGION   = os.environ.get('AWS_REGION', 'us-east-1')
PROJECT_NAME = os.environ.get('PROJECT_NAME', 'udacity-agentcore')
ACCOUNT_ID   = boto3.client('sts', region_name=AWS_REGION).get_caller_identity()['Account']

# ─────────────────────────────────────────────
# FOUNDATION MODELS
# ─────────────────────────────────────────────
# Orchestrator agent: Claude 3 Haiku - fast, cost-efficient routing decisions
ORCHESTRATOR_MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"

# Worker agents: Claude 3 Sonnet - more capable for reasoning and generation
WORKER_MODEL_ID = "anthropic.claude-3-sonnet-20240229-v1:0"

# ─────────────────────────────────────────────
# CLOUDFORMATION EXPORTS LOADER
# ─────────────────────────────────────────────
def _load_cf_exports() -> dict:
    """Load all CloudFormation stack exports into a dict."""
    cf = boto3.client('cloudformation', region_name=AWS_REGION)
    exports = {}
    paginator = cf.get_paginator('list_exports')
    for page in paginator.paginate():
        for export in page['Exports']:
            exports[export['Name']] = export['Value']
    return exports

_exports = _load_cf_exports()

def _get(key: str, fallback_env: str = None) -> str:
    """Get a CloudFormation export value, with optional env var fallback."""
    value = _exports.get(f"{PROJECT_NAME}-{key}")
    if not value and fallback_env:
        value = os.environ.get(fallback_env)
    if not value:
        raise ValueError(
            f"Could not find CloudFormation export '{PROJECT_NAME}-{key}'. "
            f"Ensure the infrastructure stack is deployed."
        )
    return value

def _get_env(key: str, required: bool = True) -> str:
    """Get a value from environment variables (for resources not in CloudFormation)."""
    value = os.environ.get(key, '')
    if not value and required:
        raise ValueError(
            f"Required environment variable '{key}' is not set. "
            f"Copy .env.example → .env and fill in your values."
        )
    return value


# ─────────────────────────────────────────────
# RESOURCE IDENTIFIERS (loaded from CloudFormation)
# ─────────────────────────────────────────────

# DynamoDB
ORDERS_TABLE         = _get('OrdersTable')
CUSTOMERS_TABLE      = _get('CustomersTable')
WORKFLOW_STATE_TABLE = _get('WorkflowStateTable')

# S3
POLICY_BUCKET      = _get('PolicyBucket')
VECTOR_STORE_BUCKET = _get('VectorBucket')

# IAM
AGENTCORE_ROLE_ARN = _get('AgentCoreRoleArn')

# CloudWatch
AGENT_LOG_GROUP = _get('AgentLogGroup')

# ─────────────────────────────────────────────
# BEDROCK KNOWLEDGE BASE IDs
# Two ways these can be set (tried in order):
#   1. CloudFormation exports - populated automatically when full_stack.yaml is deployed
#   2. .env file - populated manually when pre_deployed_stack.yaml is used (student path)
# ─────────────────────────────────────────────
def _get_kb_id(cf_key: str, env_key: str) -> str:
    """Try CloudFormation export first, then fall back to env var. Never raises."""
    value = _exports.get(f"{PROJECT_NAME}-{cf_key}", '')
    if not value:
        value = os.environ.get(env_key, '')
    return value

RETURNS_KB_ID  = _get_kb_id('ReturnsKbId',  'RETURNS_KB_ID')
SHIPPING_KB_ID = _get_kb_id('ShippingKbId', 'SHIPPING_KB_ID')
WARRANTY_KB_ID = _get_kb_id('WarrantyKbId', 'WARRANTY_KB_ID')

# ─────────────────────────────────────────────
# STUDENT-POPULATED VALUES
# Filled in as students complete each task.
# ─────────────────────────────────────────────

# Task 3: Filled in after deploying AgentCore Runtime
AGENTCORE_RUNTIME_ARN = os.environ.get('AGENTCORE_RUNTIME_ARN', '')

# Task 3: Guardrail - try CloudFormation export first (full_stack.yaml), then .env
GUARDRAIL_ID      = _exports.get(f"{PROJECT_NAME}-GuardrailId",      os.environ.get('GUARDRAIL_ID', ''))
GUARDRAIL_VERSION = _exports.get(f"{PROJECT_NAME}-GuardrailVersion", os.environ.get('GUARDRAIL_VERSION', 'DRAFT'))

# Task 4: AgentCore Memory namespace
MEMORY_NAMESPACE = f"{PROJECT_NAME}-memory"

# ─────────────────────────────────────────────
# GUARDRAIL SETTINGS
# ─────────────────────────────────────────────
GUARDRAIL_NAME = f"{PROJECT_NAME}-guardrail"
GUARDRAIL_BLOCKED_TOPICS = [
    "competitor products",
    "pricing negotiations",
    "legal threats",
]

# ─────────────────────────────────────────────
# UTILITY
# ─────────────────────────────────────────────
def print_config():
    """Pretty-print the current configuration for debugging."""
    def _display(label: str, value: str, placeholder: str = "(not yet set)") -> None:
        print(f"  {label:<26} {value or placeholder}")

    print("\n" + "="*60)
    print("  Udacity AgentCore Project Configuration")
    print("="*60)
    _display("Region:",              AWS_REGION)
    _display("Account ID:",          ACCOUNT_ID)
    _display("Orchestrator Model:",  ORCHESTRATOR_MODEL_ID)
    _display("Worker Model:",        WORKER_MODEL_ID)
    print("  " + "-"*56)
    _display("Orders Table:",        ORDERS_TABLE)
    _display("Customers Table:",     CUSTOMERS_TABLE)
    _display("Workflow State Table:", WORKFLOW_STATE_TABLE)
    _display("Policy Bucket:",       POLICY_BUCKET)
    _display("AgentCore Role:",      AGENTCORE_ROLE_ARN)
    print("  " + "-"*56)
    _display("Returns KB ID:",       RETURNS_KB_ID,  "(not yet created)")
    _display("Shipping KB ID:",      SHIPPING_KB_ID, "(not yet created)")
    _display("Warranty KB ID:",      WARRANTY_KB_ID, "(not yet created)")
    print("  " + "-"*56)
    _display("Runtime ARN:",         AGENTCORE_RUNTIME_ARN, "(not yet deployed)")
    _display("Guardrail ID:",        GUARDRAIL_ID,          "(not yet created)")
    print("="*60 + "\n")


if __name__ == '__main__':
    print_config()
