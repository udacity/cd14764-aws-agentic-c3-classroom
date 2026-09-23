"""Provided lesson infrastructure: configure and deploy through AgentCore CLI."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import boto3

ROOT = Path(__file__).resolve().parent


def load_resources(prefix):
    """Read only this activity's foundation stack; propagate AWS errors."""
    region = os.environ.get("AWS_REGION", "us-east-1")
    stack = boto3.client("cloudformation", region_name=region).describe_stacks(
        StackName=f"{prefix}-runtime"
    )["Stacks"][0]
    return {item["OutputKey"]: item["OutputValue"] for item in stack.get("Outputs", [])}


def configure_runtime(config, account, region):
    """Translate the lesson dictionary to CLI settings; never copy local credentials."""
    name = config.get("agentRuntimeName", "").replace("-", "_")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,47}", name):
        raise ValueError("Set a valid agentRuntimeName in the runtime configuration.")
    if config.get("networkConfiguration", {}).get("networkMode") != "PUBLIC":
        raise ValueError("This lab uses PUBLIC networking. Document VPC settings in the production plan.")
    if config.get("protocolConfiguration", {}).get("serverProtocol") != "HTTP":
        raise ValueError("The provided runtime endpoint requires the HTTP protocol.")
    role = config.get("roleArn", "")
    if not re.fullmatch(rf"arn:aws:iam::{account}:role/.+", role):
        raise ValueError("The execution role must belong to the current student account.")
    env = config.get("environmentVariables", {})
    if not isinstance(env, dict):
        raise ValueError("environmentVariables must be a dictionary.")
    if any(k.startswith("AWS_") and k not in ("AWS_REGION", "AWS_DEFAULT_REGION") for k in env):
        raise ValueError("Do not put AWS credentials or profiles in runtime environment variables.")
    guardrail = config.get("guardrailConfiguration", {})
    env = {**env, "AWS_REGION": region,
           "GUARDRAIL_ID": guardrail.get("guardrailIdentifier", ""),
           "GUARDRAIL_VERSION": guardrail.get("guardrailVersion", "DRAFT")}
    path = ROOT / "agentcore" / "agentcore.json"
    spec = json.loads(path.read_text())
    runtime = spec["runtimes"][0]
    runtime.update(name=name, description=config.get("description", "Lesson 10 deployment smoke test"),
                   executionRoleArn=role, networkMode="PUBLIC", protocol="HTTP",
                   envVars=[{"name": k, "value": str(v)} for k, v in env.items() if v is not None])
    targets_path = path.with_name("aws-targets.json")
    targets = [{"name": "default", "account": account, "region": region}]
    previous = json.loads(targets_path.read_text())
    if previous and previous != targets:
        raise ValueError("This folder targets another account/region. Use a fresh activity copy.")
    path.write_text(json.dumps(spec, indent=2) + "\n")
    targets_path.write_text(json.dumps(targets, indent=2) + "\n")
    return name


def deploy(config):
    """Run the CLI from this activity directory and return its deployed runtime ARN."""
    cli = shutil.which("agentcore")
    if not cli:
        raise RuntimeError("AgentCore CLI must be available in the prepared workspace.")
    version = subprocess.run([cli, "--version"], check=True, capture_output=True, text=True).stdout.strip()
    if version != "0.30.0":
        raise RuntimeError(f"This lesson is validated with AgentCore CLI 0.30.0; found {version}.")
    region = os.environ.get("AWS_REGION", "us-east-1")
    account = boto3.client("sts", region_name=region).get_caller_identity()["Account"]
    name = configure_runtime(config, account, region)
    print(f"  AgentCore CLI deployment: account {account}, region {region}", flush=True)
    env = {**os.environ, "AWS_REGION": region, "AWS_DEFAULT_REGION": region}
    subprocess.run([cli, "validate"], cwd=ROOT, env=env, check=True)
    subprocess.run([cli, "deploy", "-y", "--target", "default"], cwd=ROOT, env=env, check=True)
    state = json.loads((ROOT / "agentcore/.cli/deployed-state.json").read_text())
    arns = {target.get("resources", {}).get("runtimes", {}).get(name, {}).get("runtimeArn", "")
            for target in state.get("targets", {}).values()}
    arns = {arn for arn in arns if arn.startswith(f"arn:aws:bedrock-agentcore:{region}:{account}:runtime/")}
    if len(arns) != 1:
        raise RuntimeError("CLI deployment completed, but its runtime ARN was missing or ambiguous.")
    arn = arns.pop()
    print(f"  Runtime ARN: {arn}")
    print("  Endpoint: deployment smoke test only; business agents and monitoring are architecture plans.")
    return arn
