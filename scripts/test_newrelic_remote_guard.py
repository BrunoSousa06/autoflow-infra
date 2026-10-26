import unittest
from io import BytesIO
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from newrelic_remote_guard import RemoteInventoryError, _get, account_resource_categories, account_resources_exist


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

    @patch("newrelic_remote_guard._get")
    def test_no_matching_resources_are_absent(self, get):
        get.side_effect = [{"dashboards": []}, {"policies": []}, []]
        self.assertFalse(account_resources_exist("US", "redacted-test-key", "homolog"))

    @patch("newrelic_remote_guard._get")
    def test_any_target_object_blocks_fresh_creation(self, get):
        get.side_effect = [{"dashboards": [{"name": "AutoFlow Observability"}]}, {"policies": []}, []]
        self.assertTrue(account_resources_exist("US", "redacted-test-key", "homolog"))

    @patch("newrelic_remote_guard._get", side_effect=RemoteInventoryError("offline"))
    def test_inaccessible_api_fails_closed(self, _get):
        with self.assertRaises(RemoteInventoryError):
            account_resources_exist("US", "redacted-test-key", "homolog")

    @patch("newrelic_remote_guard._get")
    def test_inventory_reports_each_managed_account_resource_category(self, get):
        get.side_effect = [
            {"dashboards": [{"name": "AutoFlow Observability"}]},
            {"policies": [{"id": 42, "name": "AutoFlow homolog"}]},
            {"monitors": [{"name": "AutoFlow homolog public uptime"}]},
            {"nrql_conditions": [{"name": "AutoFlow: falha no processamento de OS"}]},
        ]
        self.assertEqual(
            account_resource_categories("US", "redacted-test-key", "homolog"),
            {"dashboard", "policy", "condition:order_processing_failure", "synthetics"},
        )


if __name__ == "__main__":
    unittest.main()
