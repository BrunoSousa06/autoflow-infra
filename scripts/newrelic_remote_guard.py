"""Confirma, sem exibir payloads, a existência dos recursos New Relic remotos."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class RemoteInventoryError(ValueError):
    pass


MAX_REST_PAGES = 10000
LINK_RELATION_PATTERN = re.compile(r'<([^>]+)>\s*;\s*rel\s*=\s*"?([a-z]+)"?', re.IGNORECASE)


def _get(url: str, api_key: str, endpoint: str, *, include_headers: bool = False) -> object:
    request = Request(url, headers={"Api-Key": api_key, "Accept": "application/json"})
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read())
            if include_headers:
                return payload, response.headers.get("Link")
            return payload
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


def _post_graphql(
    url: str,
    api_key: str,
    query: str,
    variables: dict[str, object],
    endpoint: str = "dashboards.search",
) -> object:
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

    if not isinstance(payload, dict) or payload.get("errors"):
        raise RemoteInventoryError(
            f"Endpoint lógico {endpoint}: erro GraphQL; inventário inconclusivo, operação bloqueada."
        )
    return payload


def _entity_search(
    region: str,
    api_key: str,
    account_id: str,
    domain: str,
    entity_type: str,
    name: str,
    endpoint: str,
) -> list[dict[str, str]]:
    host = "api.newrelic.com" if region == "US" else "api.eu.newrelic.com"
    query = """
    query DashboardInventory($query: String!, $options: EntitySearchOptions) {
      actor {
        entitySearch(query: $query, options: $options) {
          results { entities { name guid accountId } nextCursor }
        }
      }
    }
    """
    search = f"accountId = {account_id} AND domain = '{domain}' AND type = '{entity_type}' AND name = '{name}'"
    cursor = None
    seen_cursors: set[str] = set()
    matches: list[dict[str, str]] = []
    while True:
        payload = _post_graphql(
            f"https://{host}/graphql",
            api_key,
            query,
            {"query": search, "options": {"cursor": cursor} if cursor else {}},
            endpoint,
        )
        try:
            result = payload["data"]["actor"]["entitySearch"]["results"]
            entities = result["entities"]
            if "nextCursor" not in result:
                raise KeyError("nextCursor")
            next_cursor = result.get("nextCursor")
        except (KeyError, TypeError) as error:
            raise RemoteInventoryError(
            f"Endpoint lógico {endpoint}: resposta incompleta; inventário inconclusivo, operação bloqueada."
            ) from error
        if not isinstance(entities, list):
            raise RemoteInventoryError(
                f"Endpoint lógico {endpoint}: resposta incompleta; inventário inconclusivo, operação bloqueada."
            )
        named_entities = [
            entity for entity in entities
            if isinstance(entity, dict) and entity.get("name") == name
        ]
        if any(str(entity.get("accountId", "")) != str(account_id) for entity in named_entities):
            raise RemoteInventoryError(
                f"Endpoint lógico {endpoint}: conta divergente; inventário inconclusivo, operação bloqueada."
            )
        if named_entities:
            if any(not isinstance(entity.get("guid"), str) or not entity["guid"] for entity in named_entities):
                raise RemoteInventoryError(
                    f"Endpoint lógico {endpoint}: identidade incompleta; inventário inconclusivo, operação bloqueada."
                )
            matches.extend(
                {"name": str(entity["name"]), "guid": str(entity["guid"])}
                for entity in named_entities
            )
        if not next_cursor:
            return matches
        if not isinstance(next_cursor, str) or next_cursor in seen_cursors:
            raise RemoteInventoryError(
                f"Endpoint lógico {endpoint}: cursor inválido ou repetido; inventário inconclusivo, operação bloqueada."
            )
        seen_cursors.add(next_cursor)
        cursor = next_cursor


def _dashboard_entities(region: str, api_key: str, account_id: str, name: str) -> list[dict[str, str]]:
    return _entity_search(region, api_key, account_id, "VIZ", "DASHBOARD", name, "dashboards.search")


def _synthetic_monitor_entities(region: str, api_key: str, account_id: str, name: str) -> list[dict[str, str]]:
    return _entity_search(region, api_key, account_id, "SYNTH", "MONITOR", name, "synthetics.search")


def _dashboard_exists(region: str, api_key: str, account_id: str, name: str) -> bool:
    return bool(_dashboard_entities(region, api_key, account_id, name))


def _rest_collection_pages(
    base_url: str,
    api_key: str,
    endpoint: str,
    collection: str,
    *,
    page_parameter: str,
    page_size: int,
    initial_page: int = 1,
    fixed_parameters: dict[str, str] | None = None,
) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    page = initial_page
    pages = 0
    current_url = ""
    seen_urls: set[str] = set()
    while True:
        pages += 1
        if pages > MAX_REST_PAGES:
            raise RemoteInventoryError(
                f"Endpoint lógico {endpoint}: limite de páginas excedido; inventário inconclusivo, operação bloqueada."
            )
        parameters = dict(fixed_parameters or {})
        parameters[page_parameter] = str(page)
        if page_parameter == "offset":
            parameters["limit"] = str(page_size)
        request_url = current_url or f"{base_url}?{urlencode(parameters)}"
        if request_url in seen_urls:
            raise RemoteInventoryError(
                f"Endpoint lógico {endpoint}: paginação repetida; inventário inconclusivo, operação bloqueada."
            )
        seen_urls.add(request_url)
        request_parts = urlsplit(request_url)
        response = _get(request_url, api_key, endpoint, include_headers=True)
        if isinstance(response, tuple) and len(response) == 2:
            payload, link_header = response
        else:
            payload, link_header = response, None
        values = payload.get(collection) if isinstance(payload, dict) else payload if isinstance(payload, list) else None
        if not isinstance(values, list) or any(not isinstance(item, dict) for item in values):
            raise RemoteInventoryError(
                f"Endpoint lógico {endpoint}: resposta incompleta; inventário inconclusivo, operação bloqueada."
            )
        items.extend(values)
        relations = {
            relation.lower(): target
            for target, relation in LINK_RELATION_PATTERN.findall(link_header or "")
        }
        next_target = relations.get("next")
        if next_target is None and link_header and re.search(r"rel\s*=\s*\"?next\"?", link_header, re.IGNORECASE):
            raise RemoteInventoryError(
                f"Endpoint lógico {endpoint}: Link de paginação inválido; inventário inconclusivo, operação bloqueada."
            )

        if next_target is None and "last" in relations:
            last_url = urljoin(request_url, relations["last"])
            last_parts = urlsplit(last_url)
            if (
                last_parts.scheme != urlsplit(base_url).scheme
                or last_parts.netloc != urlsplit(base_url).netloc
                or last_parts.path.rstrip("/") != urlsplit(base_url).path.rstrip("/")
            ):
                raise RemoteInventoryError(
                    f"Endpoint lógico {endpoint}: Link aponta para outro endpoint; inventário inconclusivo, operação bloqueada."
                )
            last_parameters = parse_qs(last_parts.query)
            current_parameters = parse_qs(request_parts.query)
            if any(last_parameters.get(key) != [value] for key, value in (fixed_parameters or {}).items()):
                raise RemoteInventoryError(
                    f"Endpoint lógico {endpoint}: Link perdeu o filtro fixo; inventário inconclusivo, operação bloqueada."
                )
            current_values = current_parameters.get(page_parameter, [str(initial_page)])
            last_values = last_parameters.get(page_parameter)
            if not last_values:
                raise RemoteInventoryError(
                    f"Endpoint lógico {endpoint}: Link final sem parâmetro de página; inventário inconclusivo, operação bloqueada."
                )
            try:
                current_index = int(current_values[0])
                last_index = int(last_values[0])
            except ValueError as error:
                raise RemoteInventoryError(
                    f"Endpoint lógico {endpoint}: índice de página inválido; inventário inconclusivo, operação bloqueada."
                ) from error
            if current_index == last_index:
                return items
            if current_index > last_index or not values:
                raise RemoteInventoryError(
                    f"Endpoint lógico {endpoint}: paginação inconsistente; inventário inconclusivo, operação bloqueada."
                )
            if page_parameter == "offset":
                limit_values = last_parameters.get("limit") or current_parameters.get("limit") or [str(page_size)]
                next_index = current_index + len(values)
                if next_index > last_index:
                    raise RemoteInventoryError(
                        f"Endpoint lógico {endpoint}: paginação inconsistente; inventário inconclusivo, operação bloqueada."
                    )
                current_parameters[page_parameter] = [str(next_index)]
                current_parameters["limit"] = limit_values
                next_target = f"{request_parts.scheme}://{request_parts.netloc}{request_parts.path}?{urlencode(current_parameters, doseq=True)}"
            else:
                current_parameters[page_parameter] = [str(current_index + 1)]
                next_target = f"{request_parts.scheme}://{request_parts.netloc}{request_parts.path}?{urlencode(current_parameters, doseq=True)}"

        if next_target is None:
            if link_header and (relations or 'rel="next"' in link_header.lower()):
                raise RemoteInventoryError(
                    f"Endpoint lógico {endpoint}: Link sem continuação/fim verificável; inventário inconclusivo, operação bloqueada."
                )
            if len(values) >= page_size:
                raise RemoteInventoryError(
                    f"Endpoint lógico {endpoint}: página cheia sem Link de continuação; inventário inconclusivo, operação bloqueada."
                )
            return items
        next_url = urljoin(request_url, next_target)
        base_parts = urlsplit(base_url)
        next_parts = urlsplit(next_url)
        if (
            next_parts.scheme != base_parts.scheme
            or next_parts.netloc != base_parts.netloc
            or next_parts.path.rstrip("/") != base_parts.path.rstrip("/")
        ):
            raise RemoteInventoryError(
                f"Endpoint lógico {endpoint}: Link aponta para outro endpoint; inventário inconclusivo, operação bloqueada."
            )
        next_parameters = parse_qs(next_parts.query)
        if next_parameters.get(page_parameter) is None:
            raise RemoteInventoryError(
                f"Endpoint lógico {endpoint}: Link sem parâmetro de página; inventário inconclusivo, operação bloqueada."
            )
        if any(next_parameters.get(key) != [value] for key, value in (fixed_parameters or {}).items()):
            raise RemoteInventoryError(
                f"Endpoint lógico {endpoint}: Link perdeu o filtro fixo; inventário inconclusivo, operação bloqueada."
            )
        current_parameters = parse_qs(request_parts.query)
        try:
            current_index = int(current_parameters.get(page_parameter, [str(initial_page)])[0])
            next_index = int(next_parameters[page_parameter][0])
        except ValueError as error:
            raise RemoteInventoryError(
                f"Endpoint lógico {endpoint}: índice de página inválido; inventário inconclusivo, operação bloqueada."
            ) from error
        expected_index = current_index + (len(values) if page_parameter == "offset" else 1)
        if next_index != expected_index:
            raise RemoteInventoryError(
                f"Endpoint lógico {endpoint}: Link pula ou repete páginas; inventário inconclusivo, operação bloqueada."
            )
        current_url = next_url


def account_resources_exist(region: str, api_key: str, environment: str, account_id: str) -> bool:
    return bool(account_resource_categories(region, api_key, environment, account_id))


def account_resource_categories(region: str, api_key: str, environment: str, account_id: str) -> set[str]:
    return {str(resource["category"]) for resource in account_resource_inventory(region, api_key, environment, account_id)["resources"]}


def account_resource_inventory(
    region: str,
    api_key: str,
    environment: str,
    account_id: str,
    synthetic_url: str = "",
) -> dict[str, object]:
    host = "api.newrelic.com" if region == "US" else "api.eu.newrelic.com"
    policies = _rest_collection_pages(
        f"https://{host}/v2/alerts_policies.json",
        api_key,
        "alert_policies.list",
        "policies",
        page_parameter="page",
        page_size=1000,
    )
    synthetics_host = "synthetics.newrelic.com" if region == "US" else "synthetics.eu.newrelic.com"
    monitors = _rest_collection_pages(
        f"https://{synthetics_host}/synthetics/api/v3/monitors",
        api_key,
        "synthetics_monitors.list",
        "monitors",
        page_parameter="offset",
        page_size=100,
        initial_page=0,
    )

    resources: list[dict[str, str]] = []
    dashboards = _dashboard_entities(region, api_key, account_id, "AutoFlow Observability")
    for dashboard in dashboards:
        resources.append({
            "category": "dashboard",
            "resource_type": "newrelic_one_dashboard",
            "resource_name": "autoflow",
            "remote_name": dashboard["name"],
            "import_id": dashboard["guid"],
        })

    matching_policies = [item for item in policies if item.get("name") == f"AutoFlow {environment}"]
    expected_conditions = {
        "AutoFlow: falha no processamento de OS": ("condition:order_processing_failure", "order_processing_failure"),
        "AutoFlow: falha de integração": ("condition:integration_failure", "integration_failure"),
        "AutoFlow: taxa de erro API": ("condition:api_error_rate", "api_error_rate"),
        "AutoFlow: latência p95 API": ("condition:api_latency_p95", "api_latency_p95"),
        "AutoFlow: backend indisponível": ("condition:backend_unavailable", "backend_unavailable"),
        "AutoFlow: utilização de CPU": ("condition:backend_cpu_utilization", "backend_cpu_utilization"),
        "AutoFlow: utilização de memória": ("condition:backend_memory_utilization", "backend_memory_utilization"),
        "AutoFlow: indisponibilidade Synthetic": ("condition:synthetic_failure", "synthetic_failure"),
    }
    for policy in matching_policies:
        policy_id = policy.get("id")
        if not policy_id:
            raise RemoteInventoryError("Inventário da policy New Relic incompleto; operação bloqueada.")
        if policy.get("account_id") is not None and str(policy["account_id"]) != str(account_id):
            raise RemoteInventoryError("Policy AutoFlow encontrada fora da conta New Relic configurada; inventário bloqueado.")
        resources.append({
            "category": "policy",
            "resource_type": "newrelic_alert_policy",
            "resource_name": "autoflow",
            "remote_name": str(policy["name"]),
            "import_id": f"{policy_id}:{account_id}",
        })
        conditions = _rest_collection_pages(
            f"https://{host}/v2/alerts_nrql_conditions.json",
            api_key,
            "alert_conditions.list",
            "nrql_conditions",
            page_parameter="page",
            page_size=1000,
            fixed_parameters={"policy_id": str(policy_id)},
        )
        for item in conditions:
            mapped = expected_conditions.get(str(item.get("name", "")))
            if mapped is None:
                continue
            category, resource_name = mapped
            condition_id = item.get("id")
            condition_type = item.get("type")
            if not condition_id or condition_type != "static":
                raise RemoteInventoryError("Inventário de condição NRQL incompleto; operação bloqueada.")
            resources.append({
                "category": category,
                "resource_type": "newrelic_nrql_alert_condition",
                "resource_name": resource_name,
                "remote_name": str(item["name"]),
                "import_id": f"{policy_id}:{condition_id}:{condition_type}",
                "policy_id": str(policy_id),
                "condition_type": str(condition_type),
            })

    expected_monitor_name = f"AutoFlow {environment} public uptime"
    matching_monitors = [monitor for monitor in monitors if monitor.get("name") == expected_monitor_name]
    if matching_monitors:
        if len(matching_monitors) != 1:
            raise RemoteInventoryError("Synthetic monitors AutoFlow duplicados/ambíguos; inventário bloqueado.")
        monitor = matching_monitors[0]
        monitor_rest_id = monitor.get("id")
        if not monitor_rest_id or monitor.get("type") != "SIMPLE":
            raise RemoteInventoryError("Inventário do Synthetic monitor incompatível; operação bloqueada.")
        if synthetic_url and monitor.get("uri") != synthetic_url:
            raise RemoteInventoryError("Synthetic monitor AutoFlow tem URL divergente; importação automática bloqueada.")
        entities = _synthetic_monitor_entities(region, api_key, account_id, expected_monitor_name)
        if len(entities) != 1:
            raise RemoteInventoryError("GUID do Synthetic monitor ausente ou ambíguo; inventário inconclusivo, operação bloqueada.")
        resources.append({
            "category": "synthetics",
            "resource_type": "newrelic_synthetics_monitor",
            "resource_name": "autoflow_uptime",
            "remote_name": str(monitor["name"]),
            # Terraform provider import accepts the monitor entity GUID, not the
            # legacy REST monitor ID used to read its URI/type.
            "import_id": entities[0]["guid"],
            "rest_monitor_id": str(monitor_rest_id),
            "monitor_type": "SIMPLE",
            "uri": str(monitor.get("uri", "")),
        })

    return {
        "version": 1,
        "account_id": str(account_id),
        "environment": environment,
        "resources": resources,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Arquivo temporário com inventário de identidade para reconciliação.")
    args = parser.parse_args()
    try:
        region = os.environ.get("TF_VAR_newrelic_region", "")
        api_key = os.environ.get("TF_VAR_newrelic_api_key", "")
        environment = os.environ.get("TF_VAR_newrelic_environment", "")
        account_id = os.environ.get("TF_VAR_newrelic_account_id", "")
        if region not in {"US", "EU"} or not api_key or not environment or not account_id.isdigit():
            raise RemoteInventoryError("Configuração do inventário New Relic incompleta.")
        inventory = account_resource_inventory(
            region,
            api_key,
            environment,
            account_id,
            os.environ.get("TF_VAR_newrelic_synthetic_url", ""),
        )
        categories = {str(resource["category"]) for resource in inventory["resources"]}
        if args.output:
            args.output.write_text(json.dumps(inventory, sort_keys=True), encoding="utf-8")
            os.chmod(args.output, 0o600)
        print(",".join(sorted(categories)) if categories else "absent")
        return 0
    except (RemoteInventoryError, OSError) as error:
        print(f"Guard remoto New Relic bloqueou a execução: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
