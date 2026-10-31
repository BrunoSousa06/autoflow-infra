"""Valida, sem mutações, IAM Roles requeridas por EKS e managed node groups."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
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


def _has_exclusive_service_trust(policy: Any, service: str) -> bool:
    """Identifica trust de serviço dedicado, sem ampliar para outros principals."""
    if not isinstance(policy, dict):
        return False
    statements = _as_list(policy.get("Statement"))
    allows = [
        statement for statement in statements
        if isinstance(statement, dict)
        and str(statement.get("Effect", "")).lower() == "allow"
        and _action_matches_assume_role(statement.get("Action"))
    ]
    if not allows:
        return False
    for statement in allows:
        principal = statement.get("Principal")
        if not isinstance(principal, dict) or set(principal) != {"Service"}:
            return False
        services = {str(item).lower() for item in _as_list(principal.get("Service"))}
        if services != {service} or statement.get("Condition"):
            return False
    return True


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


def discover_eks_iam_roles(
    expected_account: str,
    cluster_name: str,
    region: str,
    run: Callable[..., Any] = subprocess.run,
) -> tuple[str, str]:
    """Descobre uma única Cluster Role e Node Role válidas na conta do caller."""
    if ACCOUNT_ID_PATTERN.fullmatch(expected_account or "") is None:
        raise RolePreflightError("AWS_EXPECTED_ACCOUNT_ID ausente ou inválido.")
    if not cluster_name.strip() or not region.strip():
        raise RolePreflightError("EKS_CLUSTER_NAME ou AWS_REGION ausente durante descoberta IAM.")

    caller = _run_aws(["sts", "get-caller-identity", "--output", "json"], run)
    if caller.get("Account") != expected_account:
        raise RolePreflightError("Caller STS pertence a uma conta diferente da esperada.")
    caller_arn = caller.get("Arn")
    arn_parts = caller_arn.split(":", 5) if isinstance(caller_arn, str) else []
    if len(arn_parts) != 6 or arn_parts[0] != "arn" or arn_parts[4] != expected_account:
        raise RolePreflightError("Caller STS não identifica uma partição e conta AWS válidas.")
    partition = arn_parts[1]

    active_cluster_role = None
    try:
        cluster_response = _run_aws(
            ["eks", "describe-cluster", "--name", cluster_name, "--region", region, "--output", "json"],
            run,
        )
    except RolePreflightError as error:
        if "não existe" not in str(error).lower():
            raise
    else:
        cluster = cluster_response.get("cluster")
        active_cluster_role = cluster.get("roleArn") if isinstance(cluster, dict) else None
        if not isinstance(active_cluster_role, str):
            raise RolePreflightError("Não foi possível ler a Cluster Role efetiva do EKS existente.")
        parse_role_reference(active_cluster_role, expected_account, "Cluster Role efetiva")

    roles_response = _run_aws(["iam", "list-roles", "--output", "json"], run)
    roles = roles_response.get("Roles")
    if not isinstance(roles, list):
        raise RolePreflightError("iam:ListRoles retornou uma resposta incompleta.")

    candidates: dict[str, list[str]] = {"cluster": [], "node": []}
    dedicated_cluster_candidates: list[str] = []
    service_by_kind = {"node": NODE_SERVICE} if active_cluster_role else {
        "cluster": CLUSTER_SERVICE,
        "node": NODE_SERVICE,
    }
    for role in roles:
        if not isinstance(role, dict):
            continue
        arn = role.get("Arn")
        try:
            reference = parse_role_reference(str(arn or ""), expected_account, "IAM Role")
        except RolePreflightError:
            continue
        if reference.partition != partition:
            continue
        path = role.get("Path")
        if not isinstance(path, str) or path.startswith("/aws-service-role/"):
            continue

        for kind, service in service_by_kind.items():
            try:
                validate_trust_policy(role.get("AssumeRolePolicyDocument"), service, kind)
            except RolePreflightError:
                continue
            policies = _run_aws(
                ["iam", "list-attached-role-policies", "--role-name", reference.role_name, "--output", "json"],
                run,
            )
            try:
                validate_attached_policies(
                    policies.get("AttachedPolicies"), REQUIRED_POLICIES[kind], partition, kind
                )
            except RolePreflightError:
                continue
            candidates[kind].append(reference.arn)
            if kind == "cluster" and _has_exclusive_service_trust(
                role.get("AssumeRolePolicyDocument"), service
            ):
                dedicated_cluster_candidates.append(reference.arn)

    discovered: dict[str, str] = {}
    if active_cluster_role:
        # A role efetiva é fonte de verdade para preservar o cluster existente.
        # Sua ausência no IAM é tratada somente como role imutável/no-op durante validação.
        discovered["cluster"] = active_cluster_role
    else:
        if len(dedicated_cluster_candidates) > 1:
            raise RolePreflightError(
                "Mais de uma IAM Role dedicada válida para cluster; revisão manual necessária."
            )
        matches = dedicated_cluster_candidates or candidates["cluster"]
        if len(matches) != 1:
            raise RolePreflightError(
                f"Esperada exatamente uma IAM Role válida para cluster; encontradas {len(matches)}."
            )
        discovered["cluster"] = matches[0]

    for kind in ("node",):
        matches = candidates[kind]
        if len(matches) != 1:
            raise RolePreflightError(
                f"Esperada exatamente uma IAM Role válida para {kind}; encontradas {len(matches)}."
            )
        discovered[kind] = matches[0]
    if discovered["cluster"] == discovered["node"]:
        raise RolePreflightError("A descoberta retornou a mesma IAM Role para cluster e node.")
    return discovered["cluster"], discovered["node"]


def role_arns_from_plan(plan: Any) -> tuple[str, str]:
    """Extrai as roles planejadas para validar o mesmo plano durante Apply."""
    if not isinstance(plan, dict) or not isinstance(plan.get("resource_changes"), list):
        raise RolePreflightError("JSON do Plan sem resource_changes válido.")
    attributes = {
        "aws_eks_cluster.autoflow": "role_arn",
        "aws_eks_node_group.node_group": "node_role_arn",
    }
    found: dict[str, str] = {}
    for item in plan["resource_changes"]:
        if not isinstance(item, dict) or item.get("address") not in attributes:
            continue
        change = item.get("change")
        after = change.get("after") if isinstance(change, dict) else None
        value = after.get(attributes[item["address"]]) if isinstance(after, dict) else None
        if not isinstance(value, str) or not value.strip():
            raise RolePreflightError(f"O Plan não contém uma role conhecida em {item['address']}.")
        if item["address"] in found:
            raise RolePreflightError(f"O Plan contém múltiplas entradas para {item['address']}.")
        found[item["address"]] = value
    if len(found) != len(attributes):
        missing = sorted(set(attributes) - set(found))
        raise RolePreflightError("O Plan não contém roles EKS completas: " + ", ".join(missing) + ".")
    return found["aws_eks_cluster.autoflow"], found["aws_eks_node_group.node_group"]


def require_cluster_noop(plan: Any) -> None:
    """Impede que um Plan dependa de uma Cluster Role ausente via alteração do cluster."""
    if not isinstance(plan, dict) or not isinstance(plan.get("resource_changes"), list):
        raise RolePreflightError("JSON do Plan sem resource_changes válido.")
    matches = [
        item for item in plan["resource_changes"]
        if isinstance(item, dict) and item.get("address") == "aws_eks_cluster.autoflow"
    ]
    if len(matches) != 1:
        raise RolePreflightError("O Plan não contém exatamente um recurso aws_eks_cluster.autoflow.")
    change = matches[0].get("change")
    if not isinstance(change, dict) or change.get("actions") != ["no-op"]:
        raise RolePreflightError("Cluster Role ausente: o Plan precisa preservar o cluster sem alterações.")


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
    allow_missing_existing_cluster_role: bool = False,
) -> bool:
    if not cluster_name.strip():
        raise RolePreflightError("EKS_CLUSTER_NAME ausente.")
    if not region.strip():
        raise RolePreflightError("AWS_REGION ausente.")
    cluster_role, node_role = validate_role_configuration(cluster_role_arn, node_role_arn, expected_account)

    try:
        cluster_response = _run_aws(
            ["eks", "describe-cluster", "--name", cluster_name, "--region", region, "--output", "json"], run
        )
    except RolePreflightError as error:
        if "não existe" in str(error).lower():
            _validate_role(cluster_role, CLUSTER_SERVICE, "cluster", run)
            _validate_role(node_role, NODE_SERVICE, "node", run)
            return False
        raise

    cluster = cluster_response.get("cluster")
    if not isinstance(cluster, dict) or not isinstance(cluster.get("roleArn"), str):
        raise RolePreflightError("Não foi possível confirmar a role efetiva do cluster EKS.")
    cluster_role_matches(cluster_role.arn, cluster["roleArn"])

    cluster_role_missing = False
    try:
        _validate_role(cluster_role, CLUSTER_SERVICE, "cluster", run)
    except RolePreflightError as error:
        if (
            allow_missing_existing_cluster_role
            and "cluster: a iam role configurada não existe" in str(error).lower()
        ):
            cluster_role_missing = True
        else:
            raise
    _validate_role(node_role, NODE_SERVICE, "node", run)
    return cluster_role_missing


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cluster", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--expected-account", required=True)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--discover", action="store_true", help="Descobre roles únicas por trust e policies IAM.")
    modes.add_argument("--plan-json", type=Path, help="Valida as roles embutidas no Plan aprovado.")
    parser.add_argument("--cluster-role-arn")
    parser.add_argument("--node-role-arn")
    args = parser.parse_args(arguments)
    try:
        plan = None
        if args.discover:
            if args.cluster_role_arn or args.node_role_arn:
                raise RolePreflightError("Não combine --discover com ARNs fornecidos manualmente.")
            cluster_role_arn, node_role_arn = discover_eks_iam_roles(
                args.expected_account, args.cluster, args.region
            )
        elif args.plan_json:
            if args.cluster_role_arn or args.node_role_arn:
                raise RolePreflightError("Não combine --plan-json com ARNs fornecidos manualmente.")
            plan = json.loads(args.plan_json.read_text(encoding="utf-8"))
            cluster_role_arn, node_role_arn = role_arns_from_plan(plan)
        else:
            if not args.cluster_role_arn or not args.node_role_arn:
                raise RolePreflightError("Informe --discover, --plan-json ou ambos os ARNs IAM.")
            cluster_role_arn, node_role_arn = args.cluster_role_arn, args.node_role_arn

        cluster_role_missing = verify_eks_iam_roles(
            args.cluster,
            args.region,
            args.expected_account,
            cluster_role_arn,
            node_role_arn,
            allow_missing_existing_cluster_role=args.discover or args.plan_json is not None,
        )
        if args.plan_json and cluster_role_missing:
            require_cluster_noop(plan)
    except (OSError, json.JSONDecodeError, RolePreflightError) as error:
        print(f"Preflight IAM do EKS bloqueado: {error}", file=sys.stderr)
        return 1
    if args.discover or args.plan_json:
        print(json.dumps({"cluster_role_arn": cluster_role_arn, "node_role_arn": node_role_arn}))
    else:
        print("IAM Roles, trust policies, policies requeridas e role do cluster EKS validadas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
