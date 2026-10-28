import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import BytesIO
from io import StringIO
from pathlib import Path
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from newrelic_remote_guard import (
    RemoteInventoryError,
    _get,
    _post_graphql,
    _dashboard_entities,
    _dashboard_exists,
    account_resource_categories,
    account_resource_inventory,
    account_resources_exist,
    main,
)


def page(payload, next_url=None):
    link = f'<{next_url}>; rel="next"' if next_url else None
    return payload, link


class NewRelicRemoteGuardTests(unittest.TestCase):
    @patch("newrelic_remote_guard.urlopen")
    def test_http_error_identifies_logical_endpoint_and_status_without_response_body(self, urlopen):
        urlopen.side_effect = HTTPError(
            "https://api.newrelic.com/v2/dashboards.json",
            403,
            "forbidden",
            {},
            BytesIO(b"sensitive response body"),
        )

        with self.assertRaises(RemoteInventoryError) as caught:
            _get("https://api.newrelic.com/v2/dashboards.json", "secret-api-key", "dashboards.list")

        request = urlopen.call_args.args[0]
        message = str(caught.exception)
        self.assertEqual(request.get_header("Api-key"), "secret-api-key")
        self.assertIn("dashboards.list", message)
        self.assertIn("autorização", message)
        self.assertIn("HTTP 403", message)
        self.assertNotIn("secret-api-key", message)
        self.assertNotIn("sensitive response body", message)
        self.assertNotIn("api.newrelic.com", message)

    @patch("newrelic_remote_guard.urlopen")
    def test_transport_error_identifies_logical_endpoint(self, urlopen):
        urlopen.side_effect = URLError("sensitive network details")
        with self.assertRaisesRegex(RemoteInventoryError, "synthetics_monitors.list.*erro de transporte"):
            _get(
                "https://synthetics.newrelic.com/synthetics/api/v3/monitors",
                "secret-api-key",
                "synthetics_monitors.list",
            )

    @patch("newrelic_remote_guard._dashboard_entities", return_value=[])
    @patch("newrelic_remote_guard._get")
    def test_no_matching_resources_are_absent(self, get, dashboard_entities):
        get.side_effect = [{"policies": []}, []]
        self.assertFalse(account_resources_exist("US", "redacted-test-key", "homolog", "123456"))
        dashboard_entities.assert_called_once_with("US", "redacted-test-key", "123456", "AutoFlow Observability")

    @patch("newrelic_remote_guard._dashboard_entities", return_value=[{"name": "AutoFlow Observability", "guid": "dashboard-guid"}])
    @patch("newrelic_remote_guard._get", side_effect=[{"policies": []}, []])
    def test_any_target_object_blocks_fresh_creation(self, _get, _dashboard_entities):
        self.assertTrue(account_resources_exist("US", "redacted-test-key", "homolog", "123456"))

    @patch("newrelic_remote_guard._get", side_effect=RemoteInventoryError("offline"))
    def test_inaccessible_api_fails_closed(self, _get):
        with self.assertRaises(RemoteInventoryError):
            account_resources_exist("US", "redacted-test-key", "homolog", "123456")

    @patch("newrelic_remote_guard._dashboard_entities", return_value=[{"name": "AutoFlow Observability", "guid": "dashboard-guid"}])
    @patch("newrelic_remote_guard._synthetic_monitor_entities", return_value=[{"name": "AutoFlow homolog public uptime", "guid": "synthetics-guid"}])
    @patch("newrelic_remote_guard._get")
    def test_inventory_reports_each_managed_account_resource_category(self, get, _synthetic_entities, _dashboard_entities):
        get.side_effect = [
            {"policies": [{"id": 42, "name": "AutoFlow homolog"}]},
            {"monitors": [{"id": "synthetics-rest-id", "name": "AutoFlow homolog public uptime", "type": "SIMPLE", "uri": "https://example.test"}]},
            {"nrql_conditions": [{"id": 100, "type": "static", "name": "AutoFlow: falha no processamento de OS"}]},
        ]
        self.assertEqual(
            account_resource_categories("US", "redacted-test-key", "homolog", "123456"),
            {"dashboard", "policy", "condition:order_processing_failure", "synthetics"},
        )
        self.assertEqual(get.call_args_list[0].args[0], "https://api.newrelic.com/v2/alerts_policies.json?page=1")
        self.assertEqual(get.call_args_list[1].args[0], "https://synthetics.newrelic.com/synthetics/api/v3/monitors?offset=0&limit=100")
        self.assertEqual(get.call_args_list[2].args[0], "https://api.newrelic.com/v2/alerts_nrql_conditions.json?policy_id=42&page=1")

    @patch("newrelic_remote_guard._post_graphql")
    def test_dashboard_search_paginates_and_scopes_to_configured_account_and_region(self, post):
        post.side_effect = [
            {"data": {"actor": {"entitySearch": {"results": {"entities": [], "nextCursor": "page-2"}}}}},
            {"data": {"actor": {"entitySearch": {"results": {"entities": [{"name": "AutoFlow Observability", "guid": "dashboard-guid", "accountId": 123456}], "nextCursor": None}}}}},
        ]
        self.assertTrue(_dashboard_exists("EU", "key", "123456", "AutoFlow Observability"))
        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args_list[0].args[0], "https://api.eu.newrelic.com/graphql")
        self.assertIn("accountId = 123456", post.call_args_list[0].args[3]["query"])
        self.assertIn("options: $options", post.call_args_list[0].args[2])
        self.assertNotIn("cursor: $cursor", post.call_args_list[0].args[2])
        self.assertEqual(post.call_args_list[1].args[3]["options"], {"cursor": "page-2"})

    @patch("newrelic_remote_guard._post_graphql", return_value={"data": {"actor": {"entitySearch": {"results": {"entities": [], "nextCursor": None}}}}})
    def test_dashboard_search_returns_an_empty_collection_only_after_a_complete_page(self, _post):
        self.assertEqual(_dashboard_entities("US", "key", "123456", "AutoFlow Observability"), [])

    @patch("newrelic_remote_guard._post_graphql")
    def test_dashboard_search_collects_all_pages_to_detect_duplicate_identity(self, post):
        post.side_effect = [
            {"data": {"actor": {"entitySearch": {"results": {
                "entities": [{"name": "AutoFlow Observability", "guid": "guid-a", "accountId": 123456}],
                "nextCursor": "page-2",
            }}}}},
            {"data": {"actor": {"entitySearch": {"results": {
                "entities": [{"name": "AutoFlow Observability", "guid": "guid-b", "accountId": 123456}],
                "nextCursor": None,
            }}}}},
        ]

        results = _dashboard_entities("US", "key", "123456", "AutoFlow Observability")

        self.assertEqual([item["guid"] for item in results], ["guid-a", "guid-b"])
        self.assertEqual(post.call_count, 2)

    @patch("newrelic_remote_guard._dashboard_entities", return_value=[])
    @patch("newrelic_remote_guard._synthetic_monitor_entities", return_value=[{"name": "AutoFlow homolog public uptime", "guid": "synthetics-guid"}])
    @patch("newrelic_remote_guard._get")
    def test_remote_inventory_paginates_policies_and_synthetics(self, get, _synthetic_entities, _dashboard_entities):
        get.side_effect = [
            page(
                {"policies": [{"id": 1, "name": "Unrelated"}] * 1000},
                "https://api.newrelic.com/v2/alerts_policies.json?page=2",
            ),
            {"policies": [{"id": 42, "name": "AutoFlow homolog"}]},
            page(
                {"monitors": [{"name": "Unrelated"}] * 100},
                "https://synthetics.newrelic.com/synthetics/api/v3/monitors?offset=100&limit=100",
            ),
            {"monitors": [{"id": "synthetics-rest-id", "name": "AutoFlow homolog public uptime", "type": "SIMPLE", "uri": "https://example.test"}]},
            {"nrql_conditions": []},
        ]

        categories = account_resource_categories("US", "key", "homolog", "123456")

        self.assertIn("policy", categories)
        self.assertIn("synthetics", categories)
        self.assertIn("page=2", get.call_args_list[1].args[0])
        self.assertIn("offset=100&limit=100", get.call_args_list[3].args[0])

    @patch("newrelic_remote_guard._dashboard_entities", return_value=[])
    @patch("newrelic_remote_guard._synthetic_monitor_entities", return_value=[{"name": "AutoFlow homolog public uptime", "guid": "synthetics-guid"}])
    @patch("newrelic_remote_guard._get")
    def test_synthetics_first_and_last_links_allow_offset_pagination_without_next_rel(self, get, _synthetic_entities, _dashboard_entities):
        base = "https://synthetics.newrelic.com/synthetics/api/v3/monitors"
        get.side_effect = [
            {"policies": []},
            (
                {"monitors": [{"name": "Unrelated"}] * 20},
                f'<{base}?offset=0&limit=20>; rel="first", <{base}?offset=40&limit=20>; rel="last"',
            ),
            (
                {"monitors": [{"name": "Unrelated"}] * 20},
                f'<{base}?offset=0&limit=20>; rel="first", <{base}?offset=40&limit=20>; rel="last"',
            ),
            (
                {"monitors": [{"id": "rest-monitor-id", "name": "AutoFlow homolog public uptime", "type": "SIMPLE", "uri": "https://example.test"}]},
                f'<{base}?offset=0&limit=20>; rel="first", <{base}?offset=40&limit=20>; rel="last"',
            ),
        ]

        categories = account_resource_categories("US", "key", "homolog", "123456")

        self.assertEqual(categories, {"synthetics"})
        self.assertIn("offset=20&limit=20", get.call_args_list[2].args[0])
        self.assertIn("offset=40&limit=20", get.call_args_list[3].args[0])

    @patch("newrelic_remote_guard._dashboard_entities", return_value=[])
    @patch("newrelic_remote_guard._get")
    def test_nrql_condition_inventory_paginates_within_matching_policy(self, get, _dashboard_entities):
        get.side_effect = [
            {"policies": [{"id": 42, "name": "AutoFlow homolog"}]},
            {"monitors": []},
            page(
                {"nrql_conditions": [{"name": "Unrelated"}] * 1000},
                "https://api.newrelic.com/v2/alerts_nrql_conditions.json?policy_id=42&page=2",
            ),
            {"nrql_conditions": [{"id": 101, "type": "static", "name": "AutoFlow: taxa de erro API"}]},
        ]

        categories = account_resource_categories("US", "key", "homolog", "123456")

        self.assertEqual(categories, {"policy", "condition:api_error_rate"})
        self.assertIn("policy_id=42&page=2", get.call_args_list[3].args[0])

    @patch("newrelic_remote_guard._dashboard_entities", return_value=[])
    @patch("newrelic_remote_guard._get")
    def test_policy_and_synthetic_inventory_are_scoped_to_environment(self, get, _dashboard_entities):
        get.side_effect = [
            {"policies": [{"id": 42, "name": "AutoFlow production"}]},
            {"monitors": [{"name": "AutoFlow production public uptime"}]},
        ]

        self.assertEqual(account_resource_categories("US", "key", "homolog", "123456"), set())

    @patch("newrelic_remote_guard._dashboard_entities", return_value=[])
    @patch("newrelic_remote_guard._get")
    def test_failure_while_paging_conditions_remains_inconclusive(self, get, _dashboard_entities):
        get.side_effect = [
            {"policies": [{"id": 42, "name": "AutoFlow homolog"}]},
            {"monitors": []},
            page(
                {"nrql_conditions": [{"name": "Unrelated"}] * 1000},
                "https://api.newrelic.com/v2/alerts_nrql_conditions.json?policy_id=42&page=2",
            ),
            RemoteInventoryError("offline"),
        ]

        with self.assertRaisesRegex(RemoteInventoryError, "offline"):
            account_resource_categories("US", "key", "homolog", "123456")

    @patch("newrelic_remote_guard._dashboard_entities", return_value=[])
    @patch("newrelic_remote_guard._get", return_value={"policies": [{"id": 1, "name": "Unrelated"}] * 1000})
    def test_full_rest_page_without_pagination_link_is_not_treated_as_complete(self, _get, _dashboard_entities):
        with self.assertRaisesRegex(RemoteInventoryError, "página cheia sem Link"):
            account_resource_categories("US", "key", "homolog", "123456")

    @patch("newrelic_remote_guard._dashboard_entities", return_value=[])
    @patch("newrelic_remote_guard._get")
    def test_conditions_pagination_link_must_preserve_policy_filter(self, get, _dashboard_entities):
        get.side_effect = [
            {"policies": [{"id": 42, "name": "AutoFlow homolog"}]},
            {"monitors": []},
            page(
                {"nrql_conditions": [{"name": "Unrelated"}] * 1000},
                "https://api.newrelic.com/v2/alerts_nrql_conditions.json?page=2",
            ),
        ]
        with self.assertRaisesRegex(RemoteInventoryError, "perdeu o filtro fixo"):
            account_resource_categories("US", "key", "homolog", "123456")

    @patch("newrelic_remote_guard._dashboard_entities", return_value=[])
    @patch("newrelic_remote_guard._get", return_value={"unexpected": []})
    def test_malformed_rest_inventory_fails_closed(self, _get, _dashboard_entities):
        with self.assertRaisesRegex(RemoteInventoryError, "resposta incompleta"):
            account_resource_categories("US", "key", "homolog", "123456")

    @patch("newrelic_remote_guard._dashboard_entities", return_value=[{"name": "AutoFlow Observability", "guid": "dashboard-guid"}])
    @patch("newrelic_remote_guard._synthetic_monitor_entities", return_value=[{"name": "AutoFlow homolog public uptime", "guid": "synthetics-guid"}])
    @patch("newrelic_remote_guard._get")
    def test_inventory_retains_scoped_import_identities_for_provider_formats(self, get, _synthetic_entities, _dashboard_entities):
        get.side_effect = [
            {"policies": [{"id": 42, "account_id": 123456, "name": "AutoFlow homolog"}]},
            {"monitors": [{"id": "synthetics-rest-id", "name": "AutoFlow homolog public uptime", "type": "SIMPLE", "uri": "https://example.test"}]},
            {"nrql_conditions": [{"id": 100, "type": "static", "name": "AutoFlow: falha no processamento de OS"}]},
        ]

        result = account_resource_inventory("US", "key", "homolog", "123456", "https://example.test")

        self.assertEqual(result["account_id"], "123456")
        self.assertEqual(result["environment"], "homolog")
        import_ids = {item["category"]: item["import_id"] for item in result["resources"]}
        self.assertEqual(import_ids["dashboard"], "dashboard-guid")
        self.assertEqual(import_ids["policy"], "42:123456")
        self.assertEqual(import_ids["condition:order_processing_failure"], "42:100:static")
        self.assertEqual(import_ids["synthetics"], "synthetics-guid")
        _synthetic_entities.assert_called_once_with("US", "key", "123456", "AutoFlow homolog public uptime")

    @patch("newrelic_remote_guard._dashboard_entities", return_value=[{"name": "AutoFlow Observability", "guid": "dashboard-guid"}])
    @patch("newrelic_remote_guard._get", side_effect=[{"policies": [{"id": 42, "account_id": 999999, "name": "AutoFlow homolog"}]}, {"monitors": []}])
    def test_policy_from_different_account_fails_closed(self, _get, _dashboard_entities):
        with self.assertRaisesRegex(RemoteInventoryError, "fora da conta"):
            account_resource_inventory("US", "key", "homolog", "123456")

    @patch("newrelic_remote_guard._dashboard_entities", return_value=[{"name": "AutoFlow Observability", "guid": "dashboard-guid"}])
    @patch("newrelic_remote_guard._get", side_effect=[{"policies": []}, {"monitors": [{"id": "guid", "name": "AutoFlow homolog public uptime", "type": "SIMPLE", "uri": "https://other.test"}]}])
    def test_synthetic_uri_mismatch_is_not_imported_as_autoflow(self, _get, _dashboard_entities):
        with self.assertRaisesRegex(RemoteInventoryError, "URL divergente"):
            account_resource_inventory("US", "key", "homolog", "123456", "https://expected.test")

    @patch.dict(os.environ, {
        "TF_VAR_newrelic_region": "US",
        "TF_VAR_newrelic_api_key": "redacted-test-key",
        "TF_VAR_newrelic_environment": "homolog",
        "TF_VAR_newrelic_account_id": "123456",
        "TF_VAR_newrelic_synthetic_url": "",
    })
    @patch("newrelic_remote_guard.account_resource_inventory")
    def test_cli_writes_remote_ids_only_to_restricted_inventory_file(self, inventory):
        inventory.return_value = {
            "version": 1,
            "account_id": "123456",
            "environment": "homolog",
            "resources": [{"category": "dashboard", "import_id": "private-guid"}],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = f"{directory}/inventory.json"
            output = StringIO()
            with patch("sys.argv", ["newrelic_remote_guard.py", "--output", path]), redirect_stdout(output):
                self.assertEqual(main(), 0)
            self.assertEqual(output.getvalue().strip(), "dashboard")
            self.assertIn("private-guid", Path(path).read_text(encoding="utf-8"))

    @patch("newrelic_remote_guard.urlopen")
    def test_graphql_http_200_errors_fail_closed_without_leaking_error_payload(self, urlopen):
        from io import BytesIO

        urlopen.return_value.__enter__.return_value.read.return_value = b'{"errors":[{"message":"private details"}]}'
        with self.assertRaisesRegex(RemoteInventoryError, "erro GraphQL") as caught:
            _post_graphql("https://api.newrelic.com/graphql", "secret", "query { actor { id } }", {})
        self.assertNotIn("private details", str(caught.exception))
        self.assertNotIn("secret", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
