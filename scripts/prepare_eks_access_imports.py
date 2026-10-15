"""Gera imports declarativos apenas para recursos EKS existentes e fora do State."""

import argparse
import json
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cluster", required=True)
    parser.add_argument("--principal", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--output", default="eks-access-imports.auto.tf")
    args = parser.parse_args()
    try:
        state = subprocess.run(["terraform", "-chdir=infra", "state", "list"], check=True,
                               capture_output=True, text=True)
    except subprocess.CalledProcessError as error:
        raise RuntimeError(
            "Falha ao consultar Terraform State; verifique validade das credenciais AWS e acesso ao bucket de State"
        ) from error
    addresses = set(state.stdout.splitlines())
    imports = discover_imports(["aws"], addresses, args.cluster, args.principal, args.region)
    Path(args.output).write_text(render_imports(imports), encoding="utf-8")
    print(f"Imports declarativos necessários: {len(imports)}")


if __name__ == "__main__":
    main()
