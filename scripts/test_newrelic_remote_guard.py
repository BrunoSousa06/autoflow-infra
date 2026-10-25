import unittest
from unittest.mock import patch

from newrelic_remote_guard import RemoteInventoryError, account_resource_categories, account_resources_exist


class NewRelicRemoteGuardTests(unittest.TestCase):
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
