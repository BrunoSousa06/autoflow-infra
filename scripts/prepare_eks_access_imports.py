"""Gera imports declarativos apenas para recursos EKS existentes e fora do State."""

import argparse
import json
import os
import re
import subprocess
from pathlib import Path


POLICY_ARN = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
ENTRY_ADDRESS = 'aws_eks_access_entry.access_entry[0]'
ASSOCIATION_ADDRESS = 'aws_eks_access_policy_association.labrole_admin[0]'


def run_json(command):
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as error:
        raise RuntimeError(
            "Falha ao consultar políticas de acesso EKS; verifique validade das credenciais AWS e permissões de leitura"
        ) from error
    return json.loads(result.stdout or "{}")


def access_entry_exists(aws, cluster, principal, region):
    result = subprocess.run([*aws, "eks", "describe-access-entry", "--cluster-name", cluster,
                             "--principal-arn", principal, "--region", region],
                            capture_output=True, text=True)
    if result.returncode:
        if "ResourceNotFoundException" in result.stderr:
            return False
        raise RuntimeError("Falha ao consultar Access Entry EKS; verifique credenciais e permissões AWS")
    return bool(json.loads(result.stdout or "{}").get("accessEntry"))


def discover_imports(aws, state_addresses, cluster, principal, region):
    entry_exists = access_entry_exists(aws, cluster, principal, region)
    if not entry_exists:
        return []
    associations = run_json([*aws, "eks", "list-associated-access-policies", "--cluster-name", cluster,
                              "--principal-arn", principal, "--region", region])
    association_exists = any(item.get("policyArn") == POLICY_ARN
                              for item in associations.get("associatedAccessPolicies", []))
    imports = []
    if entry_exists and ENTRY_ADDRESS not in state_addresses:
        imports.append((ENTRY_ADDRESS, f"{cluster}:{principal}"))
    if association_exists and ASSOCIATION_ADDRESS not in state_addresses:
        imports.append((ASSOCIATION_ADDRESS, f"{cluster}#{principal}#{POLICY_ARN}"))
    return imports


def render_imports(imports):
    return "\n".join(
        f'import {{\n  to = {address}\n  id = "{resource_id}"\n}}'
        for address, resource_id in imports
    ) + ("\n" if imports else "")


def state_addresses():
    try:
        state = subprocess.run(["terraform", "-chdir=infra", "state", "list"], check=True,
                               capture_output=True, text=True)
    except subprocess.CalledProcessError as error:
        output = "\n".join((error.stdout or "", error.stderr or "")).lower()
        output = re.sub(r"\x1b\[[0-9;]*m", "", output)
        if "no state file was found" in output or "no state found" in output:
            return set()
        bucket = os.environ.get("TF_STATE_BUCKET")
        key = os.environ.get("TF_STATE_KEY")
        if bucket and key:
            try:
                subprocess.run(["aws", "s3api", "head-object", "--bucket", bucket, "--key", key],
                               check=True, capture_output=True, text=True)
            except subprocess.CalledProcessError as state_error:
                state_output = "\n".join((state_error.stdout or "", state_error.stderr or "")).lower()
                if "nosuchkey" in state_output or re.search(r"\b404\b", state_output):
                    return set()
                raise RuntimeError(
                    "Falha ao verificar a ausência do Terraform State no S3; verifique credenciais e permissões"
                ) from state_error
        raise RuntimeError(
            "Falha ao consultar Terraform State; verifique validade das credenciais AWS e acesso ao bucket de State"
        ) from error
    return set(state.stdout.splitlines())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cluster", required=True)
    parser.add_argument("--principal", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--output", default="eks-access-imports.auto.tf")
    args = parser.parse_args()
    addresses = state_addresses()
    imports = discover_imports(["aws"], addresses, args.cluster, args.principal, args.region)
    Path(args.output).write_text(render_imports(imports), encoding="utf-8")
    print(f"Imports declarativos necessários: {len(imports)}")


if __name__ == "__main__":
    main()
