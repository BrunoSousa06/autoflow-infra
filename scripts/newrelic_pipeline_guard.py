"""Valida configuração New Relic e bloqueia desativações Terraform acidentais."""

from __future__ import annotations

import json
import hashlib
import base64
import binascii
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ACCOUNT_ID_PATTERN = re.compile(r"[1-9][0-9]*\Z")
AWS_ACCOUNT_ID_PATTERN = re.compile(r"[0-9]{12}\Z")
FINGERPRINT_INPUTS = (
    "AWS_EXPECTED_ACCOUNT_ID",
    "TF_VAR_enable_newrelic_kubernetes",
    "TF_VAR_enable_newrelic_account_resources",
    "TF_VAR_newrelic_account_id",
    "TF_VAR_newrelic_region",
    "TF_VAR_newrelic_environment",
    "TF_VAR_newrelic_synthetic_url",
    "TF_VAR_newrelic_synthetic_locations",
    "TF_VAR_newrelic_api_gateway_dashboard_queries",
)


class ConfigurationError(ValueError):
    """Configuração externa ausente ou inconsistente."""


def _required(environment: dict[str, str], name: str) -> str:
    value = environment.get(name, "").strip()
    if not value:
        github_name = {
            "TF_VAR_enable_newrelic_kubernetes": "ENABLE_NEWRELIC_KUBERNETES",
            "TF_VAR_enable_newrelic_account_resources": "ENABLE_NEWRELIC_ACCOUNT_RESOURCES",
            "TF_VAR_newrelic_account_id": "NEW_RELIC_ACCOUNT_ID",
            "TF_VAR_newrelic_region": "NEW_RELIC_REGION",
            "TF_VAR_newrelic_api_key": "NEW_RELIC_API_KEY",
            "TF_VAR_newrelic_environment": "NEW_RELIC_ENVIRONMENT",
        }.get(name, name)
        raise ConfigurationError(f"{github_name} ausente ou vazio.")
    return value


def validate_inputs(environment: dict[str, str]) -> tuple[bool, bool]:
    expected_aws_account = _required(environment, "AWS_EXPECTED_ACCOUNT_ID")
    if AWS_ACCOUNT_ID_PATTERN.fullmatch(expected_aws_account) is None:
        raise ConfigurationError("AWS_EXPECTED_ACCOUNT_ID deve conter 12 dígitos.")

    kubernetes_value = _required(environment, "TF_VAR_enable_newrelic_kubernetes")
    account_value = _required(environment, "TF_VAR_enable_newrelic_account_resources")
    if kubernetes_value not in {"true", "false"}:
        raise ConfigurationError("ENABLE_NEWRELIC_KUBERNETES deve ser true ou false.")
    if account_value not in {"true", "false"}:
        raise ConfigurationError("ENABLE_NEWRELIC_ACCOUNT_RESOURCES deve ser true ou false.")

    enable_kubernetes = kubernetes_value == "true"
    enable_account = account_value == "true"
    environment_name = _required(environment, "TF_VAR_newrelic_environment")
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", environment_name) is None:
        raise ConfigurationError("NEW_RELIC_ENVIRONMENT possui formato inválido.")
    if enable_account:
        account_id = _required(environment, "TF_VAR_newrelic_account_id")
        if ACCOUNT_ID_PATTERN.fullmatch(account_id) is None:
            raise ConfigurationError("NEW_RELIC_ACCOUNT_ID ausente ou inválido.")
        region = _required(environment, "TF_VAR_newrelic_region")
        if region not in {"US", "EU"}:
            raise ConfigurationError("NEW_RELIC_REGION deve ser US ou EU.")
        _required(environment, "TF_VAR_newrelic_api_key")
    synthetic_url = environment.get("TF_VAR_newrelic_synthetic_url", "").strip()
    synthetic_locations = environment.get("TF_VAR_newrelic_synthetic_locations", "[]").strip() or "[]"
    try:
        locations = json.loads(synthetic_locations)
    except json.JSONDecodeError as error:
        raise ConfigurationError("NEW_RELIC_SYNTHETIC_LOCATIONS_JSON deve ser uma lista JSON.") from error
    if not isinstance(locations, list) or not all(isinstance(item, str) and item.strip() for item in locations):
        raise ConfigurationError("NEW_RELIC_SYNTHETIC_LOCATIONS_JSON deve conter somente nomes não vazios.")
    if bool(synthetic_url) != bool(locations):
        raise ConfigurationError("URL Synthetic e locations devem ser fornecidas juntas ou ambas vazias.")
    gateway_queries_value = environment.get("TF_VAR_newrelic_api_gateway_dashboard_queries", "[]").strip() or "[]"
    try:
        gateway_queries = json.loads(gateway_queries_value)
    except json.JSONDecodeError as error:
        raise ConfigurationError("NEW_RELIC_API_GATEWAY_DASHBOARD_QUERIES_JSON deve ser uma lista JSON.") from error
    if not isinstance(gateway_queries, list) or not all(
        isinstance(item, dict)
        and isinstance(item.get("title"), str)
        and item["title"].strip()
        and isinstance(item.get("query"), str)
        and item["query"].strip()
        for item in gateway_queries
    ):
        raise ConfigurationError("Cada widget de API Gateway exige título e NRQL não vazios.")

    return enable_kubernetes, enable_account


def _is_new_relic_change(resource: dict[str, Any]) -> bool:
    resource_type = str(resource.get("type", ""))
    address = str(resource.get("address", "")).lower()
    return resource_type.startswith("newrelic_") or "helm_release.newrelic_kubernetes" in address


def check_plan(plan: dict[str, Any], environment: dict[str, str]) -> None:
    enabled_kubernetes, enabled_account = validate_inputs(environment)
    eks_exists = environment.get("EKS_CLUSTER_EXISTS", "true") == "true"
    approved = environment.get("NEWRELIC_DEACTIVATION_APPROVED") == "true"
    deactivations: list[str] = []

    for resource in plan.get("resource_changes", []):
        if not _is_new_relic_change(resource):
            continue
        actions = set(resource.get("change", {}).get("actions", []))
        if "delete" not in actions:
            continue

        resource_type = str(resource.get("type", ""))
        is_kubernetes_release = resource_type == "helm_release"
        if is_kubernetes_release and not eks_exists:
            # Em um reset, o release remoto desapareceu junto com o cluster;
            # remover sua referência órfã do state não desativa um agente ativo.
            continue
        if (
            (is_kubernetes_release and enabled_kubernetes and eks_exists)
            or (not is_kubernetes_release and enabled_account)
        ):
            raise ConfigurationError("O plan tenta remover recursos New Relic ainda habilitados; execução bloqueada.")
        deactivations.append(str(resource.get("address", "")))

    if deactivations and not approved:
        raise ConfigurationError(
            "O plan removeria recursos New Relic; desativação bloqueada sem workflow_dispatch, apply e aprovação explícita."
        )


def verify_kubernetes_secret(environment: dict[str, str]) -> None:
    namespace = "default"
    secret_name = "newrelic-license"
    secret_key = "licenseKey"
    try:
        result = subprocess.run(
            ["kubectl", "get", "secret", secret_name, "--namespace", namespace, "--output", "json"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        raise ConfigurationError("Não foi possível verificar a referência de Secret no Kubernetes.") from error
    if result.returncode:
        raise ConfigurationError("Secret New Relic ausente ou inacessível no namespace configurado.")
    try:
        data = json.loads(result.stdout).get("data", {})
        encoded_value = data.get(secret_key)
        if not isinstance(encoded_value, str) or not encoded_value:
            raise ConfigurationError("A chave configurada está ausente no Secret Kubernetes.")
        try:
            decoded_value = base64.b64decode(encoded_value, validate=True)
        except (ValueError, binascii.Error) as error:
            raise ConfigurationError("A chave configurada no Secret Kubernetes é inválida.") from error
        if not decoded_value:
            raise ConfigurationError("A chave configurada está vazia no Secret Kubernetes.")
    except (AttributeError, json.JSONDecodeError) as error:
        raise ConfigurationError("Resposta Kubernetes inválida ao verificar Secret New Relic.") from error


def config_fingerprint(environment: dict[str, str]) -> str:
    validate_inputs(environment)
    normalized = {name: environment.get(name, "") for name in FINGERPRINT_INPUTS}
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def main(arguments: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if arguments is None else arguments
    try:
        if arguments == ["validate"]:
            validate_inputs(dict(os.environ))
            print("Configuração New Relic e conta AWS validadas.")
            return 0
        if arguments == ["verify-secret"]:
            verify_kubernetes_secret(dict(os.environ))
            print("Referência de Secret New Relic verificada sem ler ou exibir seu conteúdo.")
            return 0
        if len(arguments) == 2 and arguments[0] == "fingerprint":
            fingerprint = config_fingerprint(dict(os.environ))
            Path(arguments[1]).write_text(f"{fingerprint}\n", encoding="ascii")
            print("Fingerprint não secreto da configuração New Relic registrado.")
            return 0
        if len(arguments) == 2 and arguments[0] == "verify-fingerprint":
            expected = Path(arguments[1]).read_text(encoding="ascii").strip()
            if not re.fullmatch(r"[a-f0-9]{64}", expected) or config_fingerprint(dict(os.environ)) != expected:
                raise ConfigurationError("A configuração New Relic mudou entre plan e apply; execução bloqueada.")
            print("Configuração New Relic idêntica à vinculada ao plan.")
            return 0
        if len(arguments) == 2 and arguments[0] == "check-plan":
            plan = json.loads(Path(arguments[1]).read_text(encoding="utf-8"))
            check_plan(plan, dict(os.environ))
            print("Plano sem remoção New Relic acidental.")
            return 0
        print(
            "Uso: newrelic_pipeline_guard.py validate | verify-secret | fingerprint <arquivo> | "
            "verify-fingerprint <arquivo> | check-plan <terraform-plan.json>",
            file=sys.stderr,
        )
        return 2
    except (ConfigurationError, OSError, json.JSONDecodeError) as error:
        print(f"Validação New Relic bloqueada: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
