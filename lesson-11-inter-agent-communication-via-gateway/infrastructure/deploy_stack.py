"""
deploy_stack.py
===============
Deploys the Lesson 11 CloudFormation infrastructure using boto3.
Run this ONCE before the demo or exercise scripts.

No AWS CLI required — uses boto3 directly.

Usage:
    cd lesson-11-inter-agent-communication-via-gateway/infrastructure
    python deploy_stack.py

What it creates:
    - Lambda functions  : lesson-11-gateway-{inventory,shipping,supplier,quality-inspection,
                          weather,currency,news,stock-price}
    - IAM Role          : lesson-11-gateway-agentcore-role  (for AgentCore Gateway)

The AgentCore Role ARN is printed at the end — paste it into your .env as
AGENTCORE_ROLE_ARN so the gateway scripts can use it.
"""

import boto3
import os
import time
from dotenv import load_dotenv

# ── Credential loading ─────────────────────────────────────────────────────────
# Use abspath so this works regardless of where the script is invoked from.
_THIS_DIR   = os.path.dirname(os.path.abspath(__file__))
_LESSON_DIR = os.path.dirname(_THIS_DIR)

# Load .env from lesson root first (AWS creds live there),
# then infrastructure/ for any local overrides.
load_dotenv(os.path.join(_LESSON_DIR, ".env"))
load_dotenv(os.path.join(_THIS_DIR,   ".env"))

AWS_REGION    = os.environ.get("AWS_REGION", "us-east-1")
STACK_NAME    = "lesson-11-gateway"
TEMPLATE_FILE = os.path.join(_THIS_DIR, "stack.yaml")


def deploy():
    cf = boto3.client("cloudformation", region_name=AWS_REGION)

    with open(TEMPLATE_FILE) as f:
        template_body = f.read()

    # ── Check if stack already exists ─────────────────────────────────────
    existing = False
    try:
        stacks = cf.describe_stacks(StackName=STACK_NAME)["Stacks"]
        status = stacks[0]["StackStatus"]
        existing = True
        print(f"Stack '{STACK_NAME}' already exists (status: {status})")

        if status in ("CREATE_COMPLETE", "UPDATE_COMPLETE"):
            print("Stack is healthy — checking for template changes...")
            existing = True   # fall through to update path below
        elif "ROLLBACK" in status or "FAILED" in status:
            print("Stack is in a failed state. Deleting and redeploying...")
            cf.delete_stack(StackName=STACK_NAME)
            _wait(cf, STACK_NAME, "DELETE")
            existing = False
        elif "IN_PROGRESS" in status:
            print("Stack operation already in progress — waiting...")
            _wait(cf, STACK_NAME, "any")
            stacks = cf.describe_stacks(StackName=STACK_NAME)["Stacks"]
            _print_outputs(stacks[0])
            return
    except cf.exceptions.ClientError as e:
        if "does not exist" in str(e):
            existing = False
        else:
            raise

    # ── Create or update ───────────────────────────────────────────────────
    params = dict(
        StackName=STACK_NAME,
        TemplateBody=template_body,
        Parameters=[
            {"ParameterKey": "ProjectName", "ParameterValue": STACK_NAME},
        ],
        Capabilities=["CAPABILITY_NAMED_IAM"],
    )

    if existing:
        print(f"Updating stack '{STACK_NAME}'...")
        try:
            cf.update_stack(**params)
            _wait(cf, STACK_NAME, "UPDATE")
        except cf.exceptions.ClientError as e:
            if "No updates are to be performed" in str(e):
                print("No changes needed — stack is already up to date.")
            else:
                raise
    else:
        print(f"Creating stack '{STACK_NAME}'...")
        cf.create_stack(**params)
        _wait(cf, STACK_NAME, "CREATE")

    stacks = cf.describe_stacks(StackName=STACK_NAME)["Stacks"]
    _print_outputs(stacks[0])


def _wait(cf, stack_name: str, operation: str):
    """Poll until stack operation completes."""
    dots = 0
    while True:
        try:
            stacks = cf.describe_stacks(StackName=stack_name)["Stacks"]
            status = stacks[0]["StackStatus"]
        except cf.exceptions.ClientError:
            # Stack deleted successfully
            print(" done.")
            return

        if "IN_PROGRESS" in status:
            print("." if dots % 60 else f"\n  Waiting ({status})", end="", flush=True)
            dots += 1
            time.sleep(5)
        elif "COMPLETE" in status and "ROLLBACK" not in status:
            print(f"\n  Done: {status}")
            return
        else:
            print(f"\n  Stack operation failed: {status}")
            events = cf.describe_stack_events(StackName=stack_name)["StackEvents"]
            for e in events[:5]:
                if "FAILED" in e.get("ResourceStatus", ""):
                    print(f"  Reason: {e.get('ResourceStatusReason', '')}")
            raise RuntimeError(f"Stack '{stack_name}' failed with status: {status}")


def _print_outputs(stack: dict):
    """Print stack outputs."""
    outputs = {o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])}

    role_arn = outputs.get("AgentCoreGatewayRoleArn", "(not found)")

    print("\n" + "=" * 60)
    print("  Lesson 11 Infrastructure — Ready")
    print("=" * 60)
    print(f"\n  AgentCore Gateway Role ARN:")
    print(f"    {role_arn}")
    print(f"\n  Lambda Functions:")
    for key in ["InventoryFunctionArn", "ShippingFunctionArn", "SupplierFunctionArn",
                "QualityInspectionFunctionArn", "WeatherFunctionArn",
                "CurrencyFunctionArn", "NewsFunctionArn", "StockPriceFunctionArn"]:
        arn = outputs.get(key, "(not found)")
        label = key.replace("FunctionArn", "").replace("Function", "")
        print(f"    {label:26s} {arn}")

    print(f"\n  Next step — paste the Role ARN into your .env:")
    print(f"    AGENTCORE_ROLE_ARN={role_arn}")
    print(f"\n  You are ready to run:")
    print(f"    python demo-supply-chain-gateway/supply_chain_gateway.py")
    print(f"    python exercise-analytics-gateway/solution/analytics_gateway.py\n")


if __name__ == "__main__":
    deploy()
