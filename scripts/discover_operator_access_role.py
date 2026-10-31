"""Resolve com segurança a IAM Role do caller atual para o acesso operador EKS."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import Any, Callable

from verify_eks_iam_roles import RolePreflightError, validate_role_configuration


ACCOUNT_ID_PATTERN = re.compile(r"[0-9]{12}\Z")
ASSUMED_ROLE_ARN_PATTERN = re.compile(
    r"arn:(?P<partition>[^:]+):sts::(?P<account>[0-9]{12}):assumed-role/(?P<name>[^/]+)/(?P<session>.+)\Z"
)


class OperatorRoleDiscoveryError(ValueError):
    """O caller atual não pode ser associado inequivocamente a uma IAM Role."""


def _aws_json(arguments: list[str], run: Callable[..., Any]) -> dict[str, Any]:
    try:
        result = run(["aws", *arguments, "--output", "json", "--no-cli-pager"],
                     capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or "").lower()
        if "accessdenied" in detail or "unauthorizedoperation" in detail or "not authorized" in detail:
            raise OperatorRoleDiscoveryError(
                "Sem permissão de leitura para descobrir a IAM Role do caller; exige sts:GetCallerIdentity e iam:ListRoles."
            ) from error
        raise OperatorRoleDiscoveryError(
            "Consulta AWS da identidade/roles falhou; descoberta bloqueada sem fallback."
        ) from error
    except OSError as error:
        raise OperatorRoleDiscoveryError("AWS CLI indisponível; descoberta da role bloqueada.") from error
    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError) as error:
        raise OperatorRoleDiscoveryError("Resposta AWS inválida durante descoberta da role.") from error
    if not isinstance(payload, dict):
        raise OperatorRoleDiscoveryError("Resposta AWS inesperada durante descoberta da role.")
    return payload


def discover_operator_access_role(
    expected_account: str,
    cluster_role_arn: str,
    node_role_arn: str,
    run: Callable[..., Any] = subprocess.run,
) -> str:
    if ACCOUNT_ID_PATTERN.fullmatch(expected_account or "") is None:
        raise OperatorRoleDiscoveryError("AWS_EXPECTED_ACCOUNT_ID ausente ou inválido.")
    try:
        cluster_role, node_role = validate_role_configuration(
            cluster_role_arn, node_role_arn, expected_account
        )
    except RolePreflightError as error:
        raise OperatorRoleDiscoveryError(str(error)) from error

    caller = _aws_json(["sts", "get-caller-identity"], run)
    if caller.get("Account") != expected_account:
        raise OperatorRoleDiscoveryError("Caller STS pertence a uma conta diferente da esperada.")
    assumed_arn = caller.get("Arn")
    match = ASSUMED_ROLE_ARN_PATTERN.fullmatch(assumed_arn or "")
    if match is None or match.group("account") != expected_account:
        raise OperatorRoleDiscoveryError("Caller STS não é uma sessão IAM Role compatível com EKS.")

    role_id = str(caller.get("UserId", "")).split(":", 1)[0]
    if not role_id:
        raise OperatorRoleDiscoveryError("STS não retornou o identificador da sessão Role.")

    roles = _aws_json(["iam", "list-roles"], run).get("Roles")
    if not isinstance(roles, list):
        raise OperatorRoleDiscoveryError("iam:ListRoles retornou uma resposta incompleta.")
    partition = match.group("partition")
    role_name = match.group("name")
    candidates = [
        role for role in roles
        if isinstance(role, dict)
        and role.get("RoleName") == role_name
        and isinstance(role.get("Arn"), str)
        and role["Arn"].startswith(f"arn:{partition}:iam::{expected_account}:role/")
    ]
    if len(candidates) != 1:
        raise OperatorRoleDiscoveryError(
            f"iam:ListRoles retornou {len(candidates)} IAM Roles compatíveis com a sessão STS; seleção bloqueada."
        )

    role = candidates[0]
    if role.get("RoleId") != role_id:
        raise OperatorRoleDiscoveryError(
            "RoleId da sessão STS diverge da IAM Role listada; identidade recriada ou ambígua."
        )
    arn = role.get("Arn", "")
    if arn in {cluster_role.arn, node_role.arn}:
        raise OperatorRoleDiscoveryError(
            "A IAM Role do caller coincide com role de cluster ou node; acesso operador bloqueado."
        )
    if (not arn or arn.rsplit("/", 1)[-1] != role_name
            or not isinstance(role.get("Path"), str)
            or role["Path"].startswith("/aws-service-role/")):
        raise OperatorRoleDiscoveryError("A IAM Role do caller não é válida como principal de acesso EKS.")
    return arn


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-account", required=True)
    parser.add_argument("--cluster-role-arn", required=True)
    parser.add_argument("--node-role-arn", required=True)
    args = parser.parse_args(arguments)
    try:
        print(discover_operator_access_role(
            args.expected_account, args.cluster_role_arn, args.node_role_arn
        ))
    except OperatorRoleDiscoveryError as error:
        print(f"Descoberta da role operador EKS bloqueada: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
