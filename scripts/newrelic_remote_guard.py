"""Confirma, sem exibir payloads, a existência dos recursos New Relic remotos."""

from __future__ import annotations

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class RemoteInventoryError(ValueError):
    pass


def _get(url: str, api_key: str) -> object:
    request = Request(url, headers={"Api-Key": api_key, "Accept": "application/json"})
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read())
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
        raise RemoteInventoryError("Inventário New Relic indisponível ou sem autorização; operação bloqueada.") from error


def account_resources_exist(region: str, api_key: str, environment: str) -> bool:
    return bool(account_resource_categories(region, api_key, environment))


def account_resource_categories(region: str, api_key: str, environment: str) -> set[str]:
    host = "api.newrelic.com" if region == "US" else "api.eu.newrelic.com"
    dashboards = _get(f"https://{host}/v2/dashboards.json", api_key)
    policies = _get(f"https://{host}/v2/alerts_policies.json", api_key)
    synthetics_host = "synthetics.newrelic.com" if region == "US" else "synthetics.eu.newrelic.com"
    monitors = _get(f"https://{synthetics_host}/synthetics/api/v3/monitors", api_key)

    def named(payload: object, collection: str, name: str) -> bool:
        values = payload.get(collection, []) if isinstance(payload, dict) else payload
        return isinstance(values, list) and any(isinstance(item, dict) and item.get("name") == name for item in values)

    categories: set[str] = set()
    if named(dashboards, "dashboards", "AutoFlow Observability"):
        categories.add("dashboard")
    policy_values = policies.get("policies", []) if isinstance(policies, dict) else policies
    matching_policies = [
        item for item in policy_values if isinstance(item, dict) and item.get("name") == f"AutoFlow {environment}"
    ] if isinstance(policy_values, list) else []
    if matching_policies:
        categories.add("policy")
        expected_conditions = {
            "AutoFlow: falha no processamento de OS": "order_processing_failure",
            "AutoFlow: falha de integração": "integration_failure",
            "AutoFlow: taxa de erro API": "api_error_rate",
            "AutoFlow: latência p95 API": "api_latency_p95",
            "AutoFlow: backend indisponível": "backend_unavailable",
            "AutoFlow: utilização de CPU": "backend_cpu_utilization",
            "AutoFlow: utilização de memória": "backend_memory_utilization",
            "AutoFlow: indisponibilidade Synthetic": "synthetic_failure",
        }
        for policy in matching_policies:
            policy_id = policy.get("id")
            if not policy_id:
                raise RemoteInventoryError("Inventário da policy New Relic incompleto; operação bloqueada.")
            conditions = _get(
                f"https://{host}/v2/alerts_nrql_conditions.json?policy_id={policy_id}", api_key
            )
            values = conditions.get("nrql_conditions", []) if isinstance(conditions, dict) else conditions
            if isinstance(values, list):
                for item in values:
                    if isinstance(item, dict) and item.get("name") in expected_conditions:
                        categories.add(f"condition:{expected_conditions[item['name']]}")
    if named(monitors, "monitors", f"AutoFlow {environment} public uptime"):
        categories.add("synthetics")
    return categories


def main() -> int:
    try:
        region = os.environ.get("TF_VAR_newrelic_region", "")
        api_key = os.environ.get("TF_VAR_newrelic_api_key", "")
        environment = os.environ.get("TF_VAR_newrelic_environment", "")
        if region not in {"US", "EU"} or not api_key or not environment:
            raise RemoteInventoryError("Configuração do inventário New Relic incompleta.")
        categories = account_resource_categories(region, api_key, environment)
        print(",".join(sorted(categories)) if categories else "absent")
        return 0
    except RemoteInventoryError as error:
        print(f"Guard remoto New Relic bloqueou a execução: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
