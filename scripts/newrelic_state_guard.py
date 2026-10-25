"""Inspeciona endereços Terraform sem imprimir conteúdo de state."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


class StateGuardError(ValueError):
    pass


def _resources(module: dict[str, Any], prefix: str = "") -> set[str]:
    addresses: set[str] = set()
    for resource in module.get("resources", []):
        address = resource.get("address")
        if not address:
            module_address = module.get("address", prefix)
            address = f"{module_address + '.' if module_address else ''}{resource['type']}.{resource['name']}"
            index = resource.get("index_key")
            if index is not None:
                address += f"[{json.dumps(index) if isinstance(index, str) else index}]"
        if resource.get("mode", "managed") == "managed" and _newrelic_address(address):
            addresses.add(address)
    for child in module.get("child_modules", []):
        addresses.update(_resources(child))
    return addresses


def _newrelic_address(address: str) -> bool:
    return "helm_release.newrelic_kubernetes" in address or any(
        f".{resource_type}." in f".{address}."
        for resource_type in (
            "newrelic_one_dashboard",
            "newrelic_alert_policy",
            "newrelic_nrql_alert_condition",
            "newrelic_synthetics_monitor",
        )
    )


def state_addresses(path: str | None) -> set[str]:
    if path is None:
        return set()
    try:
        state = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return set()
    except (OSError, json.JSONDecodeError) as error:
        raise StateGuardError("Não foi possível ler o state com segurança.") from error
    if not isinstance(state, dict) or not isinstance(state.get("version"), int):
        raise StateGuardError("State inválido ou formato não reconhecido; operação bloqueada.")
    root = state.get("values", {}).get("root_module")
    if root is not None:
        return _resources(root)
    # `terraform state pull` retorna o formato serializado do state (resources
    # e instances), diferente do JSON de `terraform show -json`.
    resources = state.get("resources")
    if isinstance(resources, list):
        addresses: set[str] = set()
        for resource in resources:
            if resource.get("mode", "managed") != "managed":
                continue
            module = resource.get("module", "")
            base = f"{module + '.' if module else ''}{resource['type']}.{resource['name']}"
            instances = resource.get("instances", [])
            if not instances and _newrelic_address(base):
                addresses.add(base)
            for instance in instances:
                address = base
                index = instance.get("index_key")
                if index is not None:
                    address += f"[{json.dumps(index) if isinstance(index, str) else index}]"
                if _newrelic_address(address):
                    addresses.add(address)
        return addresses
    raise StateGuardError("State sem root_module legível; operação bloqueada.")


def state_identities(path: str | None) -> set[str]:
    """Retorna fingerprints internos de type/id sem exibir IDs do state."""
    if path is None:
        return set()
    try:
        state = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return set()
    except (OSError, json.JSONDecodeError) as error:
        raise StateGuardError("Não foi possível ler o state com segurança.") from error
    identities: set[str] = set()

    def add(resource_type: str, attributes: object) -> None:
        if not isinstance(attributes, dict) or not isinstance(attributes.get("id"), (str, int)):
            return
        value = f"{resource_type}\0{attributes['id']}".encode("utf-8")
        identities.add(hashlib.sha256(value).hexdigest())

    def visit(module: dict[str, Any]) -> None:
        for resource in module.get("resources", []):
            if resource.get("mode", "managed") == "managed" and _newrelic_address(str(resource.get("address", ""))):
                add(str(resource.get("type", "")), resource.get("values", {}))
            for child in resource.get("child_modules", []):
                visit(child)
        for child in module.get("child_modules", []):
            visit(child)

    root = state.get("values", {}).get("root_module")
    if isinstance(root, dict):
        visit(root)
    else:
        for resource in state.get("resources", []):
            if resource.get("mode", "managed") != "managed":
                continue
            module = resource.get("module", "")
            address = f"{module + '.' if module else ''}{resource.get('type', '')}.{resource.get('name', '')}"
            if _newrelic_address(address):
                for instance in resource.get("instances", []):
                    add(str(resource.get("type", "")), instance.get("attributes", {}))
    return identities


def check_states(old_state: str | None, new_state: str | None, remote_helm: str, remote_account: str) -> None:
    old = state_addresses(old_state)
    new = state_addresses(new_state)
    if old & new or (state_identities(old_state) & state_identities(new_state)):
        raise StateGuardError("Ownership New Relic duplicado entre states; migração manual necessária.")
    if old:
        raise StateGuardError("State legado ainda contém recursos New Relic; bloqueado até migração autorizada.")
    if remote_helm == "unknown" or remote_account == "unknown":
        raise StateGuardError("Inventário remoto inconclusivo; operação bloqueada por segurança.")
    new_has_helm = any("helm_release.newrelic_kubernetes" in address for address in new)
    if remote_helm == "present" and not new_has_helm:
        raise StateGuardError("Release Helm remoto existe sem ownership no state novo; adotar/importar manualmente.")
    if new_has_helm and remote_helm == "absent":
        raise StateGuardError("State registra Helm, mas o release remoto está ausente.")
    category_resources = {
        "dashboard": ("newrelic_one_dashboard", "autoflow"),
        "policy": ("newrelic_alert_policy", "autoflow"),
        "synthetics": ("newrelic_synthetics_monitor", "autoflow_uptime"),
        "condition:order_processing_failure": ("newrelic_nrql_alert_condition", "order_processing_failure"),
        "condition:integration_failure": ("newrelic_nrql_alert_condition", "integration_failure"),
        "condition:api_error_rate": ("newrelic_nrql_alert_condition", "api_error_rate"),
        "condition:api_latency_p95": ("newrelic_nrql_alert_condition", "api_latency_p95"),
        "condition:backend_unavailable": ("newrelic_nrql_alert_condition", "backend_unavailable"),
        "condition:backend_cpu_utilization": ("newrelic_nrql_alert_condition", "backend_cpu_utilization"),
        "condition:backend_memory_utilization": ("newrelic_nrql_alert_condition", "backend_memory_utilization"),
        "condition:synthetic_failure": ("newrelic_nrql_alert_condition", "synthetic_failure"),
    }
    remote_categories = set() if remote_account == "absent" else set(remote_account.split(","))
    if remote_account == "present":
        remote_categories = set(category_resources)
    if remote_categories - set(category_resources):
        raise StateGuardError("Inventário de recursos de conta inválido; operação bloqueada.")
    state_categories = {
        category
        for category, (resource_type, resource_name) in category_resources.items()
        if any(f".{resource_type}.{resource_name}" in f".{address}" for address in new)
    }
    if remote_categories - state_categories:
        missing = remote_categories - state_categories
        if missing:
            raise StateGuardError("Objeto New Relic remoto sem ownership correspondente no state novo; adotar/importar manualmente.")
    if state_categories - remote_categories:
        raise StateGuardError("State registra objeto de conta ausente no inventário remoto.")


def check_legacy_state(old_state: str | None) -> None:
    if state_addresses(old_state):
        raise StateGuardError("State legado ainda contém recursos New Relic; Plan do root antigo bloqueado até migração autorizada.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-state")
    parser.add_argument("--new-state")
    parser.add_argument("--remote-helm", choices=("present", "absent", "unknown"))
    parser.add_argument("--remote-account")
    parser.add_argument("--legacy-only", action="store_true")
    args = parser.parse_args()
    try:
        if args.legacy_only:
            check_legacy_state(args.old_state)
        else:
            if not args.remote_helm or not args.remote_account:
                raise StateGuardError("Informe os resultados do inventário remoto; operação bloqueada.")
            check_states(args.old_state, args.new_state, args.remote_helm, args.remote_account)
    except StateGuardError as error:
        print(f"Guard de state New Relic bloqueou a execução: {error}", file=sys.stderr)
        return 1
    print("States sem ownership New Relic conflitante; inventário remoto informou ausência.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
