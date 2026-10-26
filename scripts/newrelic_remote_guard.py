"""Confirma, sem exibir payloads, a existência dos recursos New Relic remotos."""

from __future__ import annotations

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class RemoteInventoryError(ValueError):
    pass


def _get(url: str, api_key: str, endpoint: str) -> object:
    request = Request(url, headers={"Api-Key": api_key, "Accept": "application/json"})
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read())
    except HTTPError as error:
        status = error.code
        category = {
            401: "autenticação",
            403: "autorização",
            429: "limite de requisições",
        }.get(status, "erro HTTP")
        raise RemoteInventoryError(
            f"Endpoint lógico {endpoint}: {category} (HTTP {status}); operação bloqueada."
        ) from error
    except (URLError, TimeoutError) as error:
        category = "timeout" if isinstance(error, TimeoutError) else "erro de transporte"
        raise RemoteInventoryError(
            f"Endpoint lógico {endpoint}: {category}; inventário inconclusivo, operação bloqueada."
        ) from error
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise RemoteInventoryError(
            f"Endpoint lógico {endpoint}: resposta JSON inválida; inventário inconclusivo, operação bloqueada."
        ) from error


def _post_graphql(url: str, api_key: str, query: str, variables: dict[str, object]) -> object:
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={"Api-Key": api_key, "Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read())
    except HTTPError as error:
        status = error.code
        category = {
            401: "autenticação",
            403: "autorização",
            429: "limite de requisições",
        }.get(status, "erro HTTP")
        raise RemoteInventoryError(
            f"Endpoint lógico dashboards.search: {category} (HTTP {status}); operação bloqueada."
        ) from error
    except (URLError, TimeoutError) as error:
        category = "timeout" if isinstance(error, TimeoutError) else "erro de transporte"
        raise RemoteInventoryError(
            f"Endpoint lógico dashboards.search: {category}; inventário inconclusivo, operação bloqueada."
        ) from error
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise RemoteInventoryError(
            "Endpoint lógico dashboards.search: resposta JSON inválida; inventário inconclusivo, operação bloqueada."
        ) from error

    if not isinstance(payload, dict) or payload.get("errors"):
        raise RemoteInventoryError(
            "Endpoint lógico dashboards.search: erro GraphQL; inventário inconclusivo, operação bloqueada."
        )
    return payload


def _dashboard_exists(region: str, api_key: str, account_id: str, name: str) -> bool:
    host = "api.newrelic.com" if region == "US" else "api.eu.newrelic.com"
    query = """
    query DashboardInventory($query: String!, $cursor: String) {
      actor {
        entitySearch(query: $query, cursor: $cursor) {
          results { entities { name } nextCursor }
        }
      }
    }
    """
    search = f"accountId = {account_id} AND domain = 'VIZ' AND type = 'DASHBOARD' AND name = '{name}'"
    cursor = None
    while True:
        payload = _post_graphql(
            f"https://{host}/graphql", api_key, query, {"query": search, "cursor": cursor}
        )
        try:
            result = payload["data"]["actor"]["entitySearch"]["results"]
            entities = result["entities"]
            next_cursor = result.get("nextCursor")
        except (KeyError, TypeError) as error:
            raise RemoteInventoryError(
                "Endpoint lógico dashboards.search: resposta incompleta; inventário inconclusivo, operação bloqueada."
            ) from error
        if not isinstance(entities, list):
            raise RemoteInventoryError(
                "Endpoint lógico dashboards.search: resposta incompleta; inventário inconclusivo, operação bloqueada."
            )
        if any(isinstance(entity, dict) and entity.get("name") == name for entity in entities):
            return True
        if not next_cursor:
            return False
        if not isinstance(next_cursor, str):
            raise RemoteInventoryError(
                "Endpoint lógico dashboards.search: cursor inválido; inventário inconclusivo, operação bloqueada."
            )
        cursor = next_cursor
def account_resources_exist(region: str, api_key: str, environment: str, account_id: str) -> bool:
    return bool(account_resource_categories(region, api_key, environment, account_id))


def account_resource_categories(region: str, api_key: str, environment: str, account_id: str) -> set[str]:
    host = "api.newrelic.com" if region == "US" else "api.eu.newrelic.com"
    policies = _get(f"https://{host}/v2/alerts_policies.json", api_key, "alert_policies.list")
    synthetics_host = "synthetics.newrelic.com" if region == "US" else "synthetics.eu.newrelic.com"
    monitors = _get(
        f"https://{synthetics_host}/synthetics/api/v3/monitors", api_key, "synthetics_monitors.list"
    )

    def named(payload: object, collection: str, name: str) -> bool:
        values = payload.get(collection, []) if isinstance(payload, dict) else payload
        return isinstance(values, list) and any(isinstance(item, dict) and item.get("name") == name for item in values)

    categories: set[str] = set()
    if _dashboard_exists(region, api_key, account_id, "AutoFlow Observability"):
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
                f"https://{host}/v2/alerts_nrql_conditions.json?policy_id={policy_id}",
                api_key,
                "alert_conditions.list",
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
        account_id = os.environ.get("TF_VAR_newrelic_account_id", "")
        if region not in {"US", "EU"} or not api_key or not environment or not account_id.isdigit():
            raise RemoteInventoryError("Configuração do inventário New Relic incompleta.")
        categories = account_resource_categories(region, api_key, environment, account_id)
        print(",".join(sorted(categories)) if categories else "absent")
        return 0
    except RemoteInventoryError as error:
        print(f"Guard remoto New Relic bloqueou a execução: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
