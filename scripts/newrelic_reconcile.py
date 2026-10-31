"""Prepara imports declarativos e classificações de recuperação sem alterar State."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from newrelic_state_guard import (
    CATEGORY_RESOURCES,
    StateGuardError,
    _address_matches,
    state_addresses,
    state_category_ids,
    state_helm_attributes,
)


class ReconciliationError(ValueError):
    """A reconciliação é ambígua, incompleta ou requer aprovação explícita."""


HELM_CATEGORY = "helm"
HELM_RESOURCE = ("helm_release", "newrelic_kubernetes")
GENERATED_IMPORTS_HEADER = "# Gerado pelo guard New Relic; não editar nem versionar.\n"
RESOURCE_ADDRESSES = {
    "dashboard": "newrelic_one_dashboard.autoflow[0]",
    "policy": "newrelic_alert_policy.autoflow[0]",
    "synthetics": "newrelic_synthetics_monitor.autoflow_uptime[0]",
    **{
        category: f"newrelic_nrql_alert_condition.{resource_name}[0]"
        for category, (resource_type, resource_name) in CATEGORY_RESOURCES.items()
        if resource_type == "newrelic_nrql_alert_condition"
    },
    HELM_CATEGORY: "helm_release.newrelic_kubernetes[0]",
}


def configured_categories(environment: dict[str, str]) -> set[str]:
    """Categorias com destino gerenciado habilitado na configuração deste run."""
    enabled: set[str] = set()
    if environment.get("TF_VAR_enable_newrelic_account_resources", "false").lower() == "true":
        enabled.update({
            "dashboard",
            "policy",
            "condition:order_processing_failure",
            "condition:integration_failure",
            "condition:api_error_rate",
            "condition:api_latency_p95",
        })
        optional_queries = {
            "condition:backend_unavailable": "TF_VAR_newrelic_backend_availability_alert_query",
            "condition:backend_cpu_utilization": "TF_VAR_newrelic_backend_cpu_utilization_alert_query",
            "condition:backend_memory_utilization": "TF_VAR_newrelic_backend_memory_utilization_alert_query",
        }
        enabled.update(
            category for category, variable in optional_queries.items()
            if environment.get(variable, "").strip()
        )
        try:
            locations = json.loads(environment.get("TF_VAR_newrelic_synthetic_locations", "[]") or "[]")
        except json.JSONDecodeError as error:
            raise ReconciliationError("Locations Synthetic inválidas; reconciliação bloqueada.") from error
        if not isinstance(locations, list):
            raise ReconciliationError("Locations Synthetic inválidas; reconciliação bloqueada.")
        if environment.get("TF_VAR_newrelic_synthetic_url", "").strip() and locations:
            enabled.update({"synthetics", "condition:synthetic_failure"})
    if environment.get("TF_VAR_enable_newrelic_kubernetes", "false").lower() == "true":
        enabled.add(HELM_CATEGORY)
    return enabled


def _read_helm_inventory(path: str | None, expected_namespace: str, remote_helm: str) -> dict[str, str] | None:
    if remote_helm == "unknown":
        raise ReconciliationError("Inventário Helm inconclusivo; reconciliação bloqueada.")
    if remote_helm == "absent":
        return None
    if path is None:
        raise ReconciliationError("Inventário Helm detalhado ausente; reconciliação bloqueada.")
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReconciliationError("Inventário Helm inválido; reconciliação bloqueada.") from error
    if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
        raise ReconciliationError("Inventário Helm incompleto; reconciliação bloqueada.")
    matching = [item for item in payload if item.get("name") == "newrelic-kubernetes"]
    if len(matching) != 1:
        raise ReconciliationError("Release Helm New Relic ausente ou ambíguo; reconciliação bloqueada.")
    release = matching[0]
    remote_namespace = release.get("namespace")
    if (
        not isinstance(expected_namespace, str)
        or not expected_namespace.strip()
        or not isinstance(remote_namespace, str)
        or not remote_namespace.strip()
        or remote_namespace != expected_namespace
        or not str(release.get("chart", "")).startswith("nri-bundle-")
    ):
        raise ReconciliationError("Release Helm encontrado não corresponde ao namespace/chart AutoFlow; importação bloqueada.")
    if release.get("status") != "deployed":
        raise ReconciliationError("Release Helm não está em estado deployed; reconciliação bloqueada.")
    return {
        "category": HELM_CATEGORY,
        "resource_type": HELM_RESOURCE[0],
        "resource_name": HELM_RESOURCE[1],
        "remote_name": "newrelic-kubernetes",
        "remote_namespace": remote_namespace,
        "import_id": f"{expected_namespace}/newrelic-kubernetes",
    }


def _state_categories(addresses: set[str]) -> set[str]:
    categories = {
        category
        for category, (resource_type, resource_name) in CATEGORY_RESOURCES.items()
        if any(_address_matches(address, resource_type, resource_name) for address in addresses)
    }
    if any(_address_matches(address, *HELM_RESOURCE) for address in addresses):
        categories.add(HELM_CATEGORY)
    return categories


def _validate_state_cardinality(addresses: set[str]) -> None:
    for category, (resource_type, resource_name) in CATEGORY_RESOURCES.items():
        matches = [address for address in addresses if _address_matches(address, resource_type, resource_name)]
        if len(matches) > 1:
            raise ReconciliationError(
                f"State contém múltiplas instâncias para a categoria {category}; ownership ambíguo, reconciliação bloqueada."
            )
    helm_matches = [address for address in addresses if _address_matches(address, *HELM_RESOURCE)]
    if len(helm_matches) > 1:
        raise ReconciliationError("State contém múltiplas instâncias do release Helm New Relic; reconciliação bloqueada.")


def _canonical_identity(category: str, identifier: str) -> str:
    """Normaliza import IDs compostos à identidade que distingue o objeto remoto."""
    parts = identifier.split(":")
    if category == "policy":
        return parts[0]
    if category.startswith("condition:"):
        return ":".join(parts[:2]) if len(parts) >= 2 else identifier
    return identifier


def _validate_inventory(
    inventory: object,
    account_id: str,
    environment_name: str,
    synthetic_url: str,
) -> list[dict[str, str]]:
    if not isinstance(inventory, dict) or inventory.get("version") != 1:
        raise ReconciliationError("Inventário New Relic sem versão/schemas suportados; reconciliação bloqueada.")
    if str(inventory.get("account_id")) != str(account_id) or inventory.get("environment") != environment_name:
        raise ReconciliationError("Inventário New Relic diverge da conta/ambiente selecionados; reconciliação bloqueada.")
    resources = inventory.get("resources")
    if not isinstance(resources, list) or any(not isinstance(resource, dict) for resource in resources):
        raise ReconciliationError("Inventário New Relic incompleto; reconciliação bloqueada.")
    normalized: list[dict[str, str]] = []
    expected_remote_names = {
        "dashboard": "AutoFlow Observability",
        "policy": f"AutoFlow {environment_name}",
        "synthetics": f"AutoFlow {environment_name} public uptime",
        "condition:order_processing_failure": "AutoFlow: falha no processamento de OS",
        "condition:integration_failure": "AutoFlow: falha de integração",
        "condition:api_error_rate": "AutoFlow: taxa de erro API",
        "condition:api_latency_p95": "AutoFlow: latência p95 API",
        "condition:backend_unavailable": "AutoFlow: backend indisponível",
        "condition:backend_cpu_utilization": "AutoFlow: utilização de CPU",
        "condition:backend_memory_utilization": "AutoFlow: utilização de memória",
        "condition:synthetic_failure": "AutoFlow: indisponibilidade Synthetic",
    }
    for item in resources:
        category = str(item.get("category", ""))
        if category not in CATEGORY_RESOURCES:
            raise ReconciliationError("Inventário New Relic contém categoria desconhecida; reconciliação bloqueada.")
        expected_type, expected_name = CATEGORY_RESOURCES[category]
        if item.get("resource_type") != expected_type or item.get("resource_name") != expected_name:
            raise ReconciliationError(f"Identidade lógica incompatível para categoria {category}; reconciliação bloqueada.")
        if item.get("remote_name") != expected_remote_names[category]:
            raise ReconciliationError(f"Nome remoto não corresponde à categoria {category}; importação bloqueada.")
        import_id = item.get("import_id")
        if not isinstance(import_id, str) or not import_id.strip():
            raise ReconciliationError(f"Identidade remota ausente para categoria {category}; reconciliação bloqueada.")
        normalized_item = {key: str(value) for key, value in item.items()}
        if category == "policy":
            parts = import_id.split(":")
            if len(parts) != 2 or parts[1] != str(account_id):
                raise ReconciliationError("Policy remota não está vinculada à conta selecionada; importação bloqueada.")
        if category.startswith("condition:"):
            parts = import_id.split(":")
            if len(parts) != 3 or parts[2] != "static" or not item.get("policy_id"):
                raise ReconciliationError(f"Condição remota não corresponde ao tipo esperado em {category}; importação bloqueada.")
            normalized_item["policy_id"] = str(item["policy_id"])
        if category == "synthetics":
            if item.get("monitor_type") != "SIMPLE" or not synthetic_url or item.get("uri") != synthetic_url:
                raise ReconciliationError("Synthetic monitor remoto não corresponde à URL/tipo configurados; importação bloqueada.")
        normalized.append(normalized_item)

    remote_policy_ids = {
        item["import_id"].split(":", 1)[0]
        for item in normalized
        if item["category"] == "policy"
    }
    for item in normalized:
        if item["category"].startswith("condition:") and item["policy_id"] not in remote_policy_ids:
            raise ReconciliationError(
                f"Condição da categoria {item['category']} não está associada à policy AutoFlow do ambiente; importação bloqueada."
            )
    return normalized


def reconcile(
    state_path: str,
    inventory: object,
    account_id: str,
    environment_name: str,
    remote_helm: str,
    helm_inventory_path: str | None,
    environment: dict[str, str],
    approve: bool,
) -> tuple[str, dict[str, Any], str]:
    addresses = state_addresses(state_path)
    _validate_state_cardinality(addresses)
    state_ids = state_category_ids(state_path)
    state_categories = _state_categories(addresses)
    remote_resources = _validate_inventory(
        inventory,
        account_id,
        environment_name,
        environment.get("TF_VAR_newrelic_synthetic_url", "").strip(),
    )
    helm_resource = _read_helm_inventory(
        helm_inventory_path,
        environment.get("TF_VAR_newrelic_namespace", "default"),
        remote_helm,
    )
    if helm_resource:
        remote_resources.append(helm_resource)

    grouped: dict[str, list[dict[str, str]]] = {}
    for resource in remote_resources:
        grouped.setdefault(resource["category"], []).append(resource)
    duplicates = sorted(category for category, resources in grouped.items() if len(resources) > 1)
    if duplicates:
        raise ReconciliationError(
            "Recursos remotos AutoFlow ambíguos (possível duplicação): "
            + ", ".join(duplicates)
            + "; nenhuma importação foi preparada."
        )

    remote_categories = set(grouped)
    remote_only = remote_categories - state_categories
    state_only = state_categories - remote_categories
    desired = configured_categories(environment)
    disabled_remote = remote_only - desired
    if disabled_remote:
        raise ReconciliationError(
            "Categorias remotas não habilitadas na configuração atual: "
            + ", ".join(sorted(disabled_remote))
            + "; revisar configuração/ownership manualmente."
        )

    common = state_categories & remote_categories
    for category in sorted(common):
        if category == HELM_CATEGORY:
            attributes = state_helm_attributes(state_path)
            if len(attributes) != 1:
                raise ReconciliationError(
                    "State não permite provar a identidade única da categoria helm; reconciliação bloqueada."
                )
            state_name = attributes[0].get("name")
            state_namespace = attributes[0].get("namespace")
            remote = grouped[category][0]
            if (
                not isinstance(state_name, str)
                or not state_name.strip()
                or not isinstance(state_namespace, str)
                or not state_namespace.strip()
            ):
                raise ReconciliationError(
                    "Atributos de name/namespace ausentes no State da categoria helm; reconciliação bloqueada."
                )
            if state_name != remote["remote_name"] or state_namespace != remote["remote_namespace"]:
                raise ReconciliationError(
                    f"Identidade no State diverge do objeto remoto da categoria {category}; "
                    "possível substituição externa, revisão manual obrigatória."
                )
            continue
        identifiers = state_ids.get(category, set())
        if len(identifiers) != 1:
            raise ReconciliationError(
                f"State não permite provar a identidade única da categoria {category}; reconciliação bloqueada."
            )
        state_identity = _canonical_identity(category, next(iter(identifiers)))
        remote_identity = _canonical_identity(category, grouped[category][0]["import_id"])
        if state_identity != remote_identity:
            raise ReconciliationError(
                f"Identidade no State diverge do objeto remoto da categoria {category}; "
                "possível substituição externa, revisão manual obrigatória."
            )

    if (remote_only or state_only) and not approve:
        pieces = []
        if remote_only:
            pieces.append("remotos sem State: " + ", ".join(sorted(remote_only)))
        if state_only:
            pieces.append("no State sem correspondência no inventário: " + ", ".join(sorted(state_only)))
        raise ReconciliationError(
            "Reconciliação exige workflow_dispatch com aprovação explícita (approve_reconciliation=true): "
            + "; ".join(pieces)
            + "."
        )

    imports: list[tuple[str, str, str]] = []
    for category in sorted(remote_only):
        item = grouped[category][0]
        imports.append((category, RESOURCE_ADDRESSES[category], item["import_id"]))

    hcl = "\n".join(
        "import {\n"
        f"  to = {address}\n"
        f"  id = {json.dumps(import_id)}\n"
        "}"
        for _, address, import_id in imports
    )
    if hcl:
        hcl += "\n"
    summary = {
        "account_id": str(account_id),
        "environment": environment_name,
        "import_categories": [category for category, _, _ in imports],
        "recovery_categories": sorted(state_only),
    }
    identity_snapshot = {
        "account_id": str(account_id),
        "environment": environment_name,
        "state": {category: sorted(values) for category, values in sorted(state_ids.items())},
        "remote": [
            {"category": resource["category"], "import_id": resource["import_id"]}
            for resource in sorted(remote_resources, key=lambda item: (item["category"], item["import_id"]))
        ],
    }
    fingerprint = hashlib.sha256(
        json.dumps(identity_snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return hcl, summary, fingerprint


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True)
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--remote-helm", choices=("present", "absent", "unknown"), required=True)
    parser.add_argument("--helm-inventory")
    parser.add_argument("--approve", choices=("true", "false"), default="false")
    parser.add_argument("--imports-output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path, required=True)
    parser.add_argument("--fingerprint-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.imports_output.exists():
            current = args.imports_output.read_text(encoding="utf-8")
            if not current.startswith(GENERATED_IMPORTS_HEADER):
                raise ReconciliationError("Arquivo de import existente não foi gerado pelo guard; reconciliação bloqueada.")
            args.imports_output.unlink()
        inventory = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
        imports, summary, fingerprint = reconcile(
            args.state,
            inventory,
            args.account_id,
            args.environment,
            args.remote_helm,
            args.helm_inventory,
            dict(os.environ),
            args.approve == "true",
        )
        args.imports_output.write_text(GENERATED_IMPORTS_HEADER + imports, encoding="utf-8")
        args.summary_output.write_text(json.dumps(summary, sort_keys=True), encoding="utf-8")
        args.fingerprint_output.write_text(fingerprint + "\n", encoding="ascii")
        for output in (args.imports_output, args.summary_output, args.fingerprint_output):
            os.chmod(output, 0o600)
        categories = summary["import_categories"] + summary["recovery_categories"]
        print("Reconciliação New Relic preparada: " + (", ".join(sorted(categories)) if categories else "nenhuma divergência"))
        return 0
    except (OSError, json.JSONDecodeError, StateGuardError, ReconciliationError) as error:
        print(f"Reconciliação New Relic bloqueada: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
