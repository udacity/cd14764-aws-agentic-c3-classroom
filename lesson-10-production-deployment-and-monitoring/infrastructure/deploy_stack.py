"""
deploy_stack.py
===============
Deploys the Lesson 10 CloudFormation infrastructure using boto3.
Run this ONCE before the demo or exercise scripts.

No AWS CLI required — uses boto3 directly.

Usage:
    cd lesson-10-production-deployment-and-monitoring/infrastructure
    python deploy_stack.py

What it creates:
    - IAM Role  : lesson-10-runtime-agentcore-role
    - S3 Bucket : lesson-10-runtime-artifacts-<ACCOUNT_ID>

Outputs are exported as CloudFormation exports so the lesson scripts
discover them automatically via _load_cf_exports().
"""

import boto3
import os
import time
from dotenv import load_dotenv

# Load .env from infrastructure/ first, then parent (lesson-10 root)
load_dotenv()
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

AWS_REGION   = os.environ.get("AWS_REGION", "us-east-1")
STACK_NAME   = "lesson-10-runtime"
TEMPLATE_FILE = os.path.join(os.path.dirname(__file__), "stack.yaml")


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
            print("Stack is healthy — printing outputs and exiting.\n")
            _print_outputs(stacks[0])
            return
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
            # Print failure reason
            events = cf.describe_stack_events(StackName=stack_name)["StackEvents"]
            for e in events[:5]:
                if "FAILED" in e.get("ResourceStatus", ""):
                    print(f"  Reason: {e.get('ResourceStatusReason', '')}")
            raise RuntimeError(f"Stack '{stack_name}' failed with status: {status}")


def _print_outputs(stack: dict):
    """Print stack outputs — these are the values lesson scripts use."""
    outputs = {o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])}

    print("\n" + "=" * 60)
    print("  Lesson 10 Infrastructure — Ready")
    print("=" * 60)
    print(f"\n  AgentCore Role ARN:")
    print(f"    {outputs.get('AgentCoreRoleArn', '(not found)')}")
    print(f"\n  S3 Artifact Bucket:")
    print(f"    {outputs.get('ArtifactBucket', '(not found)')}")
    print(f"\n  These values are exported as CloudFormation exports.")
    print(f"  The lesson scripts discover them automatically.\n")
    print(f"  You are ready to run:")
    print(f"    python demo-deployment-walkthrough/deployment_walkthrough.py")
    print(f"    python exercise-vectrabank-architecture/solution/vectrabank_architecture.py\n")


if __name__ == "__main__":
    deploy()
