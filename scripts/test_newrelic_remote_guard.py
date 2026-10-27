import unittest
from io import BytesIO
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from newrelic_remote_guard import (
    RemoteInventoryError,
    _get,
    _post_graphql,
    _dashboard_exists,
    account_resource_categories,
    account_resources_exist,
)


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

    @patch("newrelic_remote_guard._dashboard_exists", return_value=False)
    @patch("newrelic_remote_guard._get")
    def test_no_matching_resources_are_absent(self, get, dashboard_exists):
        get.side_effect = [{"policies": []}, []]
        self.assertFalse(account_resources_exist("US", "redacted-test-key", "homolog", "123456"))
        dashboard_exists.assert_called_once_with("US", "redacted-test-key", "123456", "AutoFlow Observability")

    @patch("newrelic_remote_guard._dashboard_exists", return_value=True)
    @patch("newrelic_remote_guard._get", side_effect=[{"policies": []}, []])
    def test_any_target_object_blocks_fresh_creation(self, _get, _dashboard_exists):
        self.assertTrue(account_resources_exist("US", "redacted-test-key", "homolog", "123456"))

    @patch("newrelic_remote_guard._get", side_effect=RemoteInventoryError("offline"))
    def test_inaccessible_api_fails_closed(self, _get):
        with self.assertRaises(RemoteInventoryError):
            account_resources_exist("US", "redacted-test-key", "homolog", "123456")

    @patch("newrelic_remote_guard._dashboard_exists", return_value=True)
    @patch("newrelic_remote_guard._get")
    def test_inventory_reports_each_managed_account_resource_category(self, get, _dashboard_exists):
        get.side_effect = [
            {"policies": [{"id": 42, "name": "AutoFlow homolog"}]},
            {"monitors": [{"name": "AutoFlow homolog public uptime"}]},
            {"nrql_conditions": [{"name": "AutoFlow: falha no processamento de OS"}]},
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
            {"data": {"actor": {"entitySearch": {"results": {"entities": [{"name": "AutoFlow Observability"}], "nextCursor": None}}}}},
        ]
        self.assertTrue(_dashboard_exists("EU", "key", "123456", "AutoFlow Observability"))
        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args_list[0].args[0], "https://api.eu.newrelic.com/graphql")
        self.assertIn("accountId = 123456", post.call_args_list[0].args[3]["query"])
        self.assertIn("options: $options", post.call_args_list[0].args[2])
        self.assertNotIn("cursor: $cursor", post.call_args_list[0].args[2])
        self.assertEqual(post.call_args_list[1].args[3]["options"], {"cursor": "page-2"})

    @patch("newrelic_remote_guard._dashboard_exists", return_value=False)
    @patch("newrelic_remote_guard._get")
    def test_remote_inventory_paginates_policies_and_synthetics(self, get, _dashboard_exists):
        get.side_effect = [
            {"policies": [{"id": 1, "name": "Unrelated"}] * 1000},
            {"policies": [{"id": 42, "name": "AutoFlow homolog"}]},
            {"monitors": [{"name": "Unrelated"}] * 100},
            {"monitors": [{"name": "AutoFlow homolog public uptime"}]},
            {"nrql_conditions": []},
        ]

        categories = account_resource_categories("US", "key", "homolog", "123456")

        self.assertIn("policy", categories)
        self.assertIn("synthetics", categories)
        self.assertIn("page=2", get.call_args_list[1].args[0])
        self.assertIn("offset=100&limit=100", get.call_args_list[3].args[0])

    @patch("newrelic_remote_guard._dashboard_exists", return_value=False)
    @patch("newrelic_remote_guard._get", return_value={"unexpected": []})
    def test_malformed_rest_inventory_fails_closed(self, _get, _dashboard_exists):
        with self.assertRaisesRegex(RemoteInventoryError, "resposta incompleta"):
            account_resource_categories("US", "key", "homolog", "123456")

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
