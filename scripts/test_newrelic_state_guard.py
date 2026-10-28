import json
import tempfile
import unittest
from pathlib import Path

from newrelic_state_guard import StateGuardError, check_legacy_state, check_states, state_addresses


def write_state(path: Path, resources: list[dict]) -> None:
    path.write_text(json.dumps({"version": 4, "values": {"root_module": {"resources": resources}}}), encoding="utf-8")


def write_pulled_state(path: Path, resources: list[dict]) -> None:
    path.write_text(json.dumps({"version": 4, "resources": resources}), encoding="utf-8")


class NewRelicStateGuardTests(unittest.TestCase):
    def test_scenario_a_empty_states_and_remote_inventory_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            empty = Path(directory) / "empty.json"
            write_state(empty, [])
            check_states(str(empty), str(empty), "absent", "absent")

    def test_scenario_b_legacy_newrelic_address_blocks_normal_deploy(self):
        with tempfile.TemporaryDirectory() as directory:
            old = Path(directory) / "old.json"
            old.write_text(json.dumps({
                "version": 4,
                "resources": [{
                    "module": "module.x",
                    "mode": "managed",
                    "type": "helm_release",
                    "name": "newrelic_kubernetes",
                    "instances": [{"index_key": 7}],
                }],
            }), encoding="utf-8")
            with self.assertRaisesRegex(StateGuardError, "legado"):
                check_states(str(old), None, "present", "absent")

    def test_existing_newroot_ownership_matches_existing_remote_objects(self):
        with tempfile.TemporaryDirectory() as directory:
            new = Path(directory) / "new.json"
            write_state(new, [
                {"address": "helm_release.newrelic_kubernetes[4]", "mode": "managed"},
                {"address": "newrelic_alert_policy.autoflow[2]", "mode": "managed"},
            ])
            check_states(None, str(new), "present", "policy")

    def test_partial_account_migration_missing_one_remote_condition_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            new = Path(directory) / "new.json"
            write_state(new, [{"address": "newrelic_alert_policy.autoflow[0]", "mode": "managed"}])
            with self.assertRaisesRegex(StateGuardError, "sem ownership"):
                check_states(None, str(new), "absent", "condition:api_error_rate")

    def test_zero_instance_containers_in_pulled_state_are_not_owned_objects(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "new.json"
            resource_names = [
                ("newrelic_nrql_alert_condition", "backend_unavailable"),
                ("newrelic_nrql_alert_condition", "backend_cpu_utilization"),
                ("newrelic_nrql_alert_condition", "backend_memory_utilization"),
                ("newrelic_nrql_alert_condition", "synthetic_failure"),
                ("newrelic_synthetics_monitor", "autoflow_uptime"),
            ]
            write_pulled_state(state, [
                {"mode": "managed", "type": resource_type, "name": name, "instances": []}
                for resource_type, name in resource_names
            ])

            self.assertEqual(state_addresses(str(state)), set())
            check_states(None, str(state), "absent", "absent")

    def test_partially_applied_objects_match_inventory_while_failed_alerts_remain_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "new.json"
            populated = [
                ("newrelic_one_dashboard", "autoflow"),
                ("newrelic_alert_policy", "autoflow"),
                ("newrelic_nrql_alert_condition", "order_processing_failure"),
                ("newrelic_nrql_alert_condition", "integration_failure"),
            ]
            empty = [
                ("newrelic_nrql_alert_condition", "api_error_rate"),
                ("newrelic_nrql_alert_condition", "api_latency_p95"),
                ("newrelic_synthetics_monitor", "autoflow_uptime"),
                ("newrelic_nrql_alert_condition", "synthetic_failure"),
            ]
            write_pulled_state(state, [
                {
                    "mode": "managed",
                    "type": resource_type,
                    "name": name,
                    "instances": [{"attributes": {"id": "redacted-test-id"}}],
                }
                for resource_type, name in populated
            ] + [
                {"mode": "managed", "type": resource_type, "name": name, "instances": []}
                for resource_type, name in empty
            ])

            check_states(
                None,
                str(state),
                "absent",
                "dashboard,policy,condition:order_processing_failure,condition:integration_failure",
            )

    def test_real_state_remote_divergence_names_category_without_exposing_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "new.json"
            write_pulled_state(state, [{
                "mode": "managed",
                "type": "newrelic_one_dashboard",
                "name": "autoflow",
                "instances": [{"attributes": {"id": "sensitive-remote-id"}}],
            }])

            with self.assertRaises(StateGuardError) as caught:
                check_states(None, str(state), "absent", "absent")

            self.assertIn("dashboard", str(caught.exception))
            self.assertNotIn("sensitive-remote-id", str(caught.exception))

    def test_reconciliation_approval_allows_differences_but_not_unknown_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "new.json"
            write_state(state, [{"address": "newrelic_one_dashboard.autoflow[0]", "mode": "managed"}])
            check_states(None, str(state), "absent", "absent", allow_reconciliation=True)
            with self.assertRaisesRegex(StateGuardError, "inconclusivo"):
                check_states(None, str(state), "unknown", "absent", allow_reconciliation=True)

    def test_same_resource_in_both_states_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            old, new = Path(directory) / "old.json", Path(directory) / "new.json"
            resource = [{"address": "newrelic_alert_policy.autoflow[3]", "mode": "managed"}]
            write_state(old, resource)
            write_state(new, resource)
            with self.assertRaisesRegex(StateGuardError, "duplicado"):
                check_states(str(old), str(new), "absent", "present")

    def test_same_remote_identity_with_different_state_indexes_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            old, new = Path(directory) / "old.json", Path(directory) / "new.json"
            old.write_text(json.dumps({"version": 4, "resources": [{
                "mode": "managed", "type": "newrelic_alert_policy", "name": "autoflow",
                "instances": [{"index_key": 7, "attributes": {"id": "remote-policy-id"}}],
            }]}), encoding="utf-8")
            new.write_text(json.dumps({"version": 4, "resources": [{
                "mode": "managed", "type": "newrelic_alert_policy", "name": "autoflow",
                "instances": [{"index_key": 2, "attributes": {"id": "remote-policy-id"}}],
            }]}), encoding="utf-8")
            with self.assertRaisesRegex(StateGuardError, "duplicado"):
                check_states(str(old), str(new), "absent", "present")

    def test_partial_migration_and_ambiguous_remote_inventory_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            new = Path(directory) / "new.json"
            write_state(new, [])
            with self.assertRaisesRegex(StateGuardError, "Categorias New Relic remotas"):
                check_states(None, str(new), "absent", "present")
            with self.assertRaisesRegex(StateGuardError, "inconclusivo"):
                check_states(None, str(new), "unknown", "absent")

    def test_unrelated_state_objects_do_not_count_as_newrelic(self):
        with tempfile.TemporaryDirectory() as directory:
            old = Path(directory) / "old.json"
            write_state(old, [{"address": "aws_eks_cluster.autoflow", "mode": "managed"}])
            check_states(str(old), None, "absent", "absent")

    def test_legacy_root_plan_guard_allows_empty_state_only(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            write_state(state, [{"address": "newrelic_alert_policy.autoflow[3]", "mode": "managed"}])
            with self.assertRaisesRegex(StateGuardError, "Plan do root antigo bloqueado"):
                check_legacy_state(str(state))
            write_state(state, [{"address": "aws_eks_cluster.autoflow", "mode": "managed"}])
            check_legacy_state(str(state))


if __name__ == "__main__":
    unittest.main()
