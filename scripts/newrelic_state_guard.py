"""Inspeciona endereços Terraform sem imprimir conteúdo de state."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


class StateGuardError(ValueError):
    pass


CATEGORY_RESOURCES = {
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


def _category(resource_type: str, resource_name: str) -> str | None:
    return next(
        (name for name, address in CATEGORY_RESOURCES.items() if address == (resource_type, resource_name)),
        None,
    )


def _address_matches(address: str, resource_type: str, resource_name: str) -> bool:
    pattern = rf"(?:^|\.){re.escape(resource_type)}\.{re.escape(resource_name)}(?:\[[^\]]+\])?$"
    return re.search(pattern, address) is not None


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
    if not isinstance(state, dict):
        raise StateGuardError("State inválido ou formato não reconhecido; operação bloqueada.")
    root = state.get("values", {}).get("root_module")
    if root is not None:
        if not isinstance(root, dict):
            raise StateGuardError("State sem root_module legível; operação bloqueada.")
        return _resources(root)
    # `terraform state pull` retorna o formato serializado do state (resources
    # e instances), diferente do JSON de `terraform show -json`.
    resources = state.get("resources")
    if isinstance(state.get("version"), int) and isinstance(resources, list):
        addresses: set[str] = set()
        for resource in resources:
            if resource.get("mode", "managed") != "managed":
                continue
            module = resource.get("module", "")
            base = f"{module + '.' if module else ''}{resource['type']}.{resource['name']}"
            instances = resource.get("instances", [])
            for instance in instances:
                address = base
                index = instance.get("index_key")
                if index is not None:
                    address += f"[{json.dumps(index) if isinstance(index, str) else index}]"
                if _newrelic_address(address):
                    addresses.add(address)
        return addresses
    raise StateGuardError("State sem root_module legível; operação bloqueada.")


def state_category_ids(path: str | None) -> dict[str, set[str]]:
    """Lê IDs de recursos reais para validar ownership sem expô-los em mensagens."""
    if path is None:
        return {}
    try:
        state = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as error:
        raise StateGuardError("Não foi possível ler o state com segurança.") from error

    identities: dict[str, set[str]] = {}

    def record(resource_type: str, resource_name: str, attributes: object) -> None:
        category = "helm" if (resource_type, resource_name) == ("helm_release", "newrelic_kubernetes") else _category(resource_type, resource_name)
        if category is None or not isinstance(attributes, dict):
            return
        identity = attributes.get("id")
        if isinstance(identity, (str, int)) and str(identity):
            identities.setdefault(category, set()).add(str(identity))

    def visit(module: dict[str, Any]) -> None:
        for resource in module.get("resources", []):
            if resource.get("mode", "managed") == "managed":
                record(str(resource.get("type", "")), str(resource.get("name", "")), resource.get("values", {}))
        for child in module.get("child_modules", []):
            visit(child)

    root = state.get("values", {}).get("root_module")
    if isinstance(root, dict):
        visit(root)
        return identities

    resources = state.get("resources")
    if not isinstance(resources, list):
        raise StateGuardError("State sem formato de recursos legível; operação bloqueada.")
    for resource in resources:
        if resource.get("mode", "managed") != "managed":
            continue
        for instance in resource.get("instances", []):
            record(
                str(resource.get("type", "")),
                str(resource.get("name", "")),
                instance.get("attributes", {}),
            )
    return identities


def state_helm_attributes(path: str | None) -> list[dict[str, Any]]:
    """Retorna os atributos efetivos das instâncias Helm nos formatos de State suportados."""
    if path is None:
        return []
    try:
        state = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError) as error:
        raise StateGuardError("Não foi possível ler o state com segurança.") from error

    attributes: list[dict[str, Any]] = []

    def visit(module: dict[str, Any]) -> None:
        for resource in module.get("resources", []):
            if (
                resource.get("mode", "managed") == "managed"
                and resource.get("type") == "helm_release"
                and resource.get("name") == "newrelic_kubernetes"
            ):
                values = resource.get("values")
                attributes.append(values if isinstance(values, dict) else {})
        for child in module.get("child_modules", []):
            visit(child)

    root = state.get("values", {}).get("root_module")
    if isinstance(root, dict):
        visit(root)
        return attributes

    resources = state.get("resources")
    if not isinstance(resources, list):
        raise StateGuardError("State sem formato de recursos legível; operação bloqueada.")
    for resource in resources:
        if (
            resource.get("mode", "managed") != "managed"
            or resource.get("type") != "helm_release"
            or resource.get("name") != "newrelic_kubernetes"
        ):
            continue
        for instance in resource.get("instances", []):
            values = instance.get("attributes")
            attributes.append(values if isinstance(values, dict) else {})
    return attributes


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


def check_states(
    old_state: str | None,
    new_state: str | None,
    remote_helm: str,
    remote_account: str,
    allow_reconciliation: bool = False,
) -> None:
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
        if not allow_reconciliation:
            raise StateGuardError("Categoria helm remota sem ownership no state novo: helm; reconciliação exige aprovação explícita.")
    if new_has_helm and remote_helm == "absent":
        if not allow_reconciliation:
            raise StateGuardError("State registra a categoria helm ausente no inventário remoto: helm; reconciliação exige aprovação explícita.")
    remote_categories = set() if remote_account == "absent" else set(remote_account.split(","))
    if remote_account == "present":
        remote_categories = set(CATEGORY_RESOURCES)
    if remote_categories - set(CATEGORY_RESOURCES):
        raise StateGuardError("Inventário de recursos de conta inválido; operação bloqueada.")
    state_categories = {
        category
        for category, (resource_type, resource_name) in CATEGORY_RESOURCES.items()
        if any(_address_matches(address, resource_type, resource_name) for address in new)
    }
    if remote_categories - state_categories:
        missing = remote_categories - state_categories
        if missing and not allow_reconciliation:
            categories = ", ".join(sorted(missing))
            raise StateGuardError(
                "Categorias New Relic remotas sem ownership no state: "
                f"{categories}; importação declarativa exige aprovação explícita."
            )
    missing_remotely = state_categories - remote_categories
    if missing_remotely and not allow_reconciliation:
        categories = ", ".join(sorted(missing_remotely))
        raise StateGuardError(
            "State registra categorias ausentes no inventário remoto: "
            f"{categories}; plano de recuperação exige aprovação explícita."
        )


def check_legacy_state(old_state: str | None) -> None:
    if state_addresses(old_state):
        raise StateGuardError("State legado ainda contém recursos New Relic; Plan do root antigo bloqueado até migração autorizada.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-state")
    parser.add_argument("--new-state")
    parser.add_argument("--remote-helm", choices=("present", "absent", "unknown"))
    parser.add_argument("--remote-account")
    parser.add_argument("--allow-reconciliation", choices=("true", "false"), default="false")
    parser.add_argument("--legacy-only", action="store_true")
    args = parser.parse_args()
    try:
        if args.legacy_only:
            check_legacy_state(args.old_state)
        else:
            if not args.remote_helm or not args.remote_account:
                raise StateGuardError("Informe os resultados do inventário remoto; operação bloqueada.")
            check_states(
                args.old_state,
                args.new_state,
                args.remote_helm,
                args.remote_account,
                args.allow_reconciliation == "true",
            )
    except StateGuardError as error:
        print(f"Guard de state New Relic bloqueou a execução: {error}", file=sys.stderr)
        return 1
    print("States sem ownership New Relic conflitante; inventário remoto informou ausência.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
