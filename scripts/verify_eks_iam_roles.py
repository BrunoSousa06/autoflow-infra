"""Valida, sem mutações, IAM Roles requeridas por EKS e managed node groups."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Callable


ACCOUNT_ID_PATTERN = re.compile(r"[0-9]{12}\Z")
ROLE_ARN_PATTERN = re.compile(r"arn:([^:]+):iam::([0-9]{12}):role/(.+)\Z")
CLUSTER_SERVICE = "eks.amazonaws.com"
NODE_SERVICE = "ec2.amazonaws.com"


class RolePreflightError(ValueError):
    """A configuração ou a role IAM não satisfaz os pré-requisitos do EKS."""


@dataclass(frozen=True)
class RoleReference:
    arn: str
    partition: str
    account_id: str
    role_name: str


REQUIRED_POLICIES = {
    "cluster": ("AmazonEKSClusterPolicy",),
    "node": (
        "AmazonEKSWorkerNodePolicy",
        "AmazonEC2ContainerRegistryReadOnly",
        "AmazonEKS_CNI_Policy",
    ),
}


def parse_role_reference(arn: str, expected_account: str, variable_name: str) -> RoleReference:
    value = arn.strip()
    match = ROLE_ARN_PATTERN.fullmatch(value)
    if match is None:
        raise RolePreflightError(f"{variable_name} ausente ou não é um ARN de IAM Role válido.")
    partition, account_id, role_path = match.groups()
    if account_id != expected_account:
        raise RolePreflightError(f"{variable_name}: o ARN da role não pertence à conta AWS esperada.")
    role_name = role_path.rsplit("/", 1)[-1]
    if not role_name:
        raise RolePreflightError(f"{variable_name}: o ARN não contém nome de IAM Role.")
    return RoleReference(value, partition, account_id, role_name)


def validate_role_configuration(
    cluster_role_arn: str | None,
    node_role_arn: str | None,
    expected_account: str | None,
) -> tuple[RoleReference, RoleReference]:
    if expected_account is None or ACCOUNT_ID_PATTERN.fullmatch(expected_account) is None:
        raise RolePreflightError("AWS_EXPECTED_ACCOUNT_ID ausente ou inválido.")
    if not cluster_role_arn or not cluster_role_arn.strip():
        raise RolePreflightError("AWS_EKS_CLUSTER_ROLE_ARN ausente.")
    if not node_role_arn or not node_role_arn.strip():
        raise RolePreflightError("AWS_EKS_NODE_ROLE_ARN ausente.")

    cluster = parse_role_reference(cluster_role_arn, expected_account, "AWS_EKS_CLUSTER_ROLE_ARN")
    node = parse_role_reference(node_role_arn, expected_account, "AWS_EKS_NODE_ROLE_ARN")
    if cluster.arn == node.arn:
        raise RolePreflightError("AWS_EKS_CLUSTER_ROLE_ARN e AWS_EKS_NODE_ROLE_ARN devem ser roles diferentes.")
    return cluster, node


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _action_matches_assume_role(action: Any) -> bool:
    return any(str(item).lower() in {"sts:assumerole", "sts:*", "*"} for item in _as_list(action))


def _service_principal_matches(principal: Any, service: str) -> bool:
    if principal == "*":
        return True
    if not isinstance(principal, dict):
        return False
    services = {str(item).lower() for item in _as_list(principal.get("Service"))}
    return service in services or "*" in services


def validate_trust_policy(policy: Any, service: str, label: str) -> None:
    if not isinstance(policy, dict):
        raise RolePreflightError(f"{label}: trust policy ausente ou inválida.")
    statements = _as_list(policy.get("Statement"))
    allows = []
    for statement in statements:
        if not isinstance(statement, dict) or not _action_matches_assume_role(statement.get("Action")):
            continue
        if not _service_principal_matches(statement.get("Principal"), service):
            continue
        if str(statement.get("Effect", "")).lower() == "deny":
            raise RolePreflightError(f"{label}: trust policy contém Deny para sts:AssumeRole de {service}.")
        if str(statement.get("Effect", "")).lower() == "allow":
            service_principals = {
                str(item).lower()
                for item in _as_list(statement.get("Principal", {}).get("Service"))
            } if isinstance(statement.get("Principal"), dict) else set()
            if "*" in service_principals:
                raise RolePreflightError(f"{label}: trust policy usa Service principal wildcard; não é possível confirmar o principal esperado com segurança.")
            allows.append(statement)

    if not allows:
        raise RolePreflightError(f"{label}: trust policy não permite sts:AssumeRole para {service}.")
    if any(statement.get("Condition") for statement in allows):
        raise RolePreflightError(
            f"{label}: trust policy de {service} tem Condition não verificável por este preflight; revisão manual necessária."
        )


def _is_aws_managed_policy(policy: Any, partition: str, required_name: str) -> bool:
    if not isinstance(policy, dict) or policy.get("PolicyName") != required_name:
        return False
    arn = str(policy.get("PolicyArn", ""))
    parts = arn.split(":", 5)
    if len(parts) != 6 or parts[0] != "arn" or parts[1] != partition or parts[2] != "iam" or parts[4] != "aws":
        return False
    return parts[5].startswith("policy/") and parts[5].rsplit("/", 1)[-1] == required_name


def validate_attached_policies(
    policies: Any,
    required: tuple[str, ...],
    partition: str,
    label: str,
) -> None:
    attached = _as_list(policies)
    missing = [
        name for name in required
        if not any(_is_aws_managed_policy(policy, partition, name) for policy in attached)
    ]
    if missing:
        raise RolePreflightError(f"{label}: faltam AWS managed policies obrigatórias: {', '.join(missing)}.")


def cluster_role_matches(configured_arn: str, effective_arn: str) -> None:
    if configured_arn != effective_arn:
        raise RolePreflightError(
            "A Cluster Role configurada diverge da role efetiva do EKS existente; "
            "interrompa o fluxo normal e faça uma reconstrução controlada."
        )


def _run_aws(arguments: list[str], run: Callable[..., Any]) -> dict[str, Any]:
    try:
        result = run(["aws", *arguments], capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or "").lower()
        if "nosuchentity" in detail or "not found" in detail or "resourcenotfoundexception" in detail:
            raise RolePreflightError("O recurso AWS consultado não existe.") from error
        if "accessdenied" in detail or "unauthorizedoperation" in detail:
            raise RolePreflightError("A sessão AWS não tem permissão de leitura para validar IAM/EKS.") from error
        raise RolePreflightError("Falha AWS ao validar IAM/EKS; resultado inconclusivo, operação bloqueada.") from error
    except OSError as error:
        raise RolePreflightError("AWS CLI indisponível para validar IAM/EKS.") from error
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RolePreflightError("Resposta AWS inválida durante validação IAM/EKS.") from error
    if not isinstance(payload, dict):
        raise RolePreflightError("Resposta AWS inesperada durante validação IAM/EKS.")
    return payload


def _validate_role(reference: RoleReference, service: str, kind: str, run: Callable[..., Any]) -> None:
    try:
        role_response = _run_aws(
            ["iam", "get-role", "--role-name", reference.role_name, "--output", "json"], run
        )
    except RolePreflightError as error:
        if "não existe" in str(error).lower():
            raise RolePreflightError(f"{kind}: a IAM Role configurada não existe.") from error
        raise
    role = role_response.get("Role")
    if not isinstance(role, dict) or role.get("Arn") != reference.arn:
        raise RolePreflightError(f"{kind}: a IAM Role configurada não existe ou o ARN retornado diverge.")
    validate_trust_policy(role.get("AssumeRolePolicyDocument"), service, kind)

    policies_response = _run_aws(
        ["iam", "list-attached-role-policies", "--role-name", reference.role_name, "--output", "json"], run
    )
    validate_attached_policies(
        policies_response.get("AttachedPolicies"), REQUIRED_POLICIES[kind], reference.partition, kind
    )


def verify_eks_iam_roles(
    cluster_name: str,
    region: str,
    expected_account: str,
    cluster_role_arn: str,
    node_role_arn: str,
    run: Callable[..., Any] = subprocess.run,
) -> None:
    if not cluster_name.strip():
        raise RolePreflightError("EKS_CLUSTER_NAME ausente.")
    if not region.strip():
        raise RolePreflightError("AWS_REGION ausente.")
    cluster_role, node_role = validate_role_configuration(cluster_role_arn, node_role_arn, expected_account)

    _validate_role(cluster_role, CLUSTER_SERVICE, "cluster", run)
    _validate_role(node_role, NODE_SERVICE, "node", run)

    try:
        cluster_response = _run_aws(
            ["eks", "describe-cluster", "--name", cluster_name, "--region", region, "--output", "json"], run
        )
    except RolePreflightError as error:
        if "não existe" in str(error).lower():
            return
        raise

    cluster = cluster_response.get("cluster")
    if not isinstance(cluster, dict) or not isinstance(cluster.get("roleArn"), str):
        raise RolePreflightError("Não foi possível confirmar a role efetiva do cluster EKS.")
    cluster_role_matches(cluster_role.arn, cluster["roleArn"])


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cluster", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--expected-account", required=True)
    parser.add_argument("--cluster-role-arn", required=True)
    parser.add_argument("--node-role-arn", required=True)
    args = parser.parse_args(arguments)
    try:
        verify_eks_iam_roles(
            args.cluster,
            args.region,
            args.expected_account,
            args.cluster_role_arn,
            args.node_role_arn,
        )
    except RolePreflightError as error:
        print(f"Preflight IAM do EKS bloqueado: {error}", file=sys.stderr)
        return 1
    print("IAM Roles, trust policies, policies requeridas e role do cluster EKS validadas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
