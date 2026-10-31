import json
import tempfile
import unittest
from pathlib import Path

from newrelic_reconcile import ReconciliationError, reconcile


ACCOUNT_ID = "123456"
ENVIRONMENT = "homolog"
BASE_ENV = {
    "TF_VAR_enable_newrelic_account_resources": "true",
    "TF_VAR_enable_newrelic_kubernetes": "false",
    "TF_VAR_newrelic_synthetic_url": "",
    "TF_VAR_newrelic_synthetic_locations": "[]",
}
WORKFLOW = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "newrelic.yml").read_text(encoding="utf-8")


def write_state(path: Path, objects: list[tuple[str, str, str]]) -> None:
    path.write_text(json.dumps({
        "version": 4,
        "resources": [
            {
                "mode": "managed",
                "type": resource_type,
                "name": resource_name,
                "instances": [{"index_key": 0, "attributes": {"id": identity}}],
            }
            for resource_type, resource_name, identity in objects
        ],
    }), encoding="utf-8")


def write_helm_state(path: Path, instances: list[dict], *, show_json: bool = False) -> None:
    if show_json:
        resources = [
            {
                "address": f"helm_release.newrelic_kubernetes[{index}]",
                "mode": "managed",
                "type": "helm_release",
                "name": "newrelic_kubernetes",
                "values": attributes,
            }
            for index, attributes in enumerate(instances)
        ]
        payload = {"format_version": "1.0", "values": {"root_module": {"resources": resources}}}
    else:
        payload = {
            "version": 4,
            "resources": [{
                "mode": "managed",
                "type": "helm_release",
                "name": "newrelic_kubernetes",
                "instances": [
                    {"index_key": index, "attributes": attributes}
                    for index, attributes in enumerate(instances)
                ],
            }],
        }
    path.write_text(json.dumps(payload), encoding="utf-8")


def resource(category: str, resource_type: str, resource_name: str, import_id: str) -> dict[str, str]:
    names = {
        "dashboard": "AutoFlow Observability",
        "policy": "AutoFlow homolog",
        "condition:order_processing_failure": "AutoFlow: falha no processamento de OS",
        "condition:integration_failure": "AutoFlow: falha de integração",
        "condition:api_error_rate": "AutoFlow: taxa de erro API",
        "condition:api_latency_p95": "AutoFlow: latência p95 API",
        "condition:backend_unavailable": "AutoFlow: backend indisponível",
        "condition:backend_cpu_utilization": "AutoFlow: utilização de CPU",
        "condition:backend_memory_utilization": "AutoFlow: utilização de memória",
        "condition:synthetic_failure": "AutoFlow: indisponibilidade Synthetic",
        "synthetics": "AutoFlow homolog public uptime",
    }
    result = {
        "category": category,
        "resource_type": resource_type,
        "resource_name": resource_name,
        "remote_name": names[category],
        "import_id": import_id,
    }
    if category.startswith("condition:"):
        result["policy_id"] = import_id.split(":", 1)[0]
    if category == "synthetics":
        result.update({"monitor_type": "SIMPLE", "uri": "https://example.test"})
    return result


def inventory(resources: list[dict[str, str]]) -> dict:
    return {"version": 1, "account_id": ACCOUNT_ID, "environment": ENVIRONMENT, "resources": resources}


class NewRelicReconciliationTests(unittest.TestCase):
    def _reconcile(self, state, remote, *, approve=False, environment=None, helm_inventory=None, remote_helm="absent"):
        return reconcile(
            str(state), remote, ACCOUNT_ID, ENVIRONMENT, remote_helm,
            str(helm_inventory) if helm_inventory else None,
            environment or BASE_ENV, approve,
        )

    def test_initial_provisioning_creates_only_when_both_state_and_remote_are_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "empty.json"
            write_state(state, [])

            imports, summary, _ = self._reconcile(state, inventory([]))

            self.assertEqual(imports, "")
            self.assertEqual(summary["import_categories"], [])
            self.assertEqual(summary["recovery_categories"], [])

    def test_partial_apply_reuses_owned_resources_and_leaves_failed_alerts_for_terraform_create(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "partial.json"
            write_state(state, [
                ("newrelic_one_dashboard", "autoflow", "dashboard-guid"),
                ("newrelic_alert_policy", "autoflow", "42:123456"),
                ("newrelic_nrql_alert_condition", "order_processing_failure", "42:100:static"),
                ("newrelic_nrql_alert_condition", "integration_failure", "42:101:static"),
            ])
            remote = inventory([
                resource("dashboard", "newrelic_one_dashboard", "autoflow", "dashboard-guid"),
                resource("policy", "newrelic_alert_policy", "autoflow", "42:123456"),
                resource("condition:order_processing_failure", "newrelic_nrql_alert_condition", "order_processing_failure", "42:100:static"),
                resource("condition:integration_failure", "newrelic_nrql_alert_condition", "integration_failure", "42:101:static"),
            ])

            imports, summary, _ = self._reconcile(state, remote)

            self.assertEqual(imports, "")
            self.assertEqual(summary["import_categories"], [])
            self.assertEqual(summary["recovery_categories"], [])

    def test_reconciliation_is_idempotent_for_same_state_and_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            write_state(state, [])
            remote = inventory([resource("dashboard", "newrelic_one_dashboard", "autoflow", "dashboard-guid")])

            first = self._reconcile(state, remote, approve=True)
            second = self._reconcile(state, remote, approve=True)

            self.assertEqual(first, second)
            self.assertIn("newrelic_one_dashboard.autoflow[0]", first[0])

    def test_remote_only_matching_object_requires_approval_and_prepares_provider_import(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            write_state(state, [])
            remote = inventory([resource("policy", "newrelic_alert_policy", "autoflow", "42:123456")])

            with self.assertRaisesRegex(ReconciliationError, "aprovação explícita.*policy"):
                self._reconcile(state, remote)

            imports, summary, _ = self._reconcile(state, remote, approve=True)

            self.assertIn("to = newrelic_alert_policy.autoflow[0]", imports)
            self.assertIn('id = "42:123456"', imports)
            self.assertEqual(summary["import_categories"], ["policy"])

    def test_remote_only_nrql_condition_uses_provider_composite_import_identifier(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            write_state(state, [])
            remote = inventory([
                resource("policy", "newrelic_alert_policy", "autoflow", "42:123456"),
                resource(
                    "condition:api_error_rate",
                    "newrelic_nrql_alert_condition",
                    "api_error_rate",
                    "42:101:static",
                ),
            ])

            imports, summary, _ = self._reconcile(state, remote, approve=True)

            self.assertIn('id = "42:101:static"', imports)
            self.assertEqual(summary["import_categories"], ["condition:api_error_rate", "policy"])

    def test_remote_only_synthetic_monitor_import_requires_matching_configured_url(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            write_state(state, [])
            environment = {
                **BASE_ENV,
                "TF_VAR_newrelic_synthetic_url": "https://example.test/health",
                "TF_VAR_newrelic_synthetic_locations": '["AWS_US_EAST_1"]',
            }
            remote = inventory([{
                **resource("synthetics", "newrelic_synthetics_monitor", "autoflow_uptime", "synthetics-guid"),
                "uri": "https://example.test/health",
                "monitor_type": "SIMPLE",
            }])

            imports, summary, _ = self._reconcile(
                state, remote, approve=True, environment=environment
            )

            self.assertIn('id = "synthetics-guid"', imports)
            self.assertEqual(summary["import_categories"], ["synthetics"])

    def test_state_only_resource_requires_approval_and_prepares_refresh_plan_not_state_removal(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            write_state(state, [("newrelic_one_dashboard", "autoflow", "dashboard-guid")])
            original = state.read_bytes()

            with self.assertRaisesRegex(ReconciliationError, "aprovação explícita.*dashboard"):
                self._reconcile(state, inventory([]))

            imports, summary, _ = self._reconcile(state, inventory([]), approve=True)

            self.assertEqual(imports, "")
            self.assertEqual(summary["recovery_categories"], ["dashboard"])
            self.assertEqual(state.read_bytes(), original)

    def test_same_category_with_different_remote_identity_blocks_duplicate_or_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            write_state(state, [("newrelic_one_dashboard", "autoflow", "old-guid")])
            remote = inventory([resource("dashboard", "newrelic_one_dashboard", "autoflow", "new-guid")])

            with self.assertRaisesRegex(ReconciliationError, "Identidade no State diverge.*dashboard"):
                self._reconcile(state, remote, approve=True)

    def test_multiple_remote_candidates_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            write_state(state, [])
            remote = inventory([
                resource("dashboard", "newrelic_one_dashboard", "autoflow", "guid-a"),
                resource("dashboard", "newrelic_one_dashboard", "autoflow", "guid-b"),
            ])

            with self.assertRaisesRegex(ReconciliationError, "ambíguos.*dashboard"):
                self._reconcile(state, remote, approve=True)

    def test_duplicate_state_instances_block_even_if_the_remote_id_is_the_same(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            state.write_text(json.dumps({
                "version": 4,
                "resources": [{
                    "mode": "managed",
                    "type": "newrelic_one_dashboard",
                    "name": "autoflow",
                    "instances": [
                        {"index_key": 0, "attributes": {"id": "dashboard-guid"}},
                        {"index_key": 1, "attributes": {"id": "dashboard-guid"}},
                    ],
                }],
            }), encoding="utf-8")

            with self.assertRaisesRegex(ReconciliationError, "múltiplas instâncias.*dashboard"):
                self._reconcile(
                    state,
                    inventory([resource("dashboard", "newrelic_one_dashboard", "autoflow", "dashboard-guid")]),
                    approve=True,
                )

    def test_remote_object_disabled_in_current_configuration_is_not_imported(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            write_state(state, [])
            remote = inventory([
                resource("policy", "newrelic_alert_policy", "autoflow", "42:123456"),
                resource(
                    "condition:backend_cpu_utilization",
                    "newrelic_nrql_alert_condition",
                    "backend_cpu_utilization",
                    "42:100:static",
                ),
            ])

            with self.assertRaisesRegex(ReconciliationError, "não habilitadas.*condition:backend_cpu_utilization"):
                self._reconcile(state, remote, approve=True)

    def test_incomplete_or_wrong_account_inventory_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            write_state(state, [])

            with self.assertRaisesRegex(ReconciliationError, "conta/ambiente"):
                self._reconcile(state, {**inventory([]), "account_id": "999999"})
            with self.assertRaisesRegex(ReconciliationError, "incompleto"):
                self._reconcile(state, {**inventory([]), "resources": None})

    def test_helm_release_import_uses_namespace_and_release_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            write_state(state, [])
            helm_file = Path(directory) / "helm.json"
            helm_file.write_text(json.dumps([{
                "name": "newrelic-kubernetes",
                "namespace": "default",
                "chart": "nri-bundle-8.0.32",
                "status": "deployed",
            }]), encoding="utf-8")
            environment = {**BASE_ENV, "TF_VAR_enable_newrelic_kubernetes": "true"}

            imports, summary, _ = self._reconcile(
                state,
                inventory([]),
                approve=True,
                environment=environment,
                helm_inventory=helm_file,
                remote_helm="present",
            )

            self.assertIn("to = helm_release.newrelic_kubernetes[0]", imports)
            self.assertIn('id = "default/newrelic-kubernetes"', imports)
            self.assertEqual(summary["import_categories"], ["helm"])

    def test_helm_state_name_and_namespace_match_remote_in_state_pull_format(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            write_helm_state(state, [{"id": "newrelic-kubernetes", "name": "newrelic-kubernetes", "namespace": "default"}])
            helm_file = Path(directory) / "helm.json"
            helm_file.write_text(json.dumps([{
                "name": "newrelic-kubernetes",
                "namespace": "default",
                "chart": "nri-bundle-8.0.32",
                "status": "deployed",
            }]), encoding="utf-8")
            environment = {**BASE_ENV, "TF_VAR_enable_newrelic_kubernetes": "true"}

            imports, summary, _ = self._reconcile(
                state, inventory([]), environment=environment,
                helm_inventory=helm_file, remote_helm="present",
            )

            self.assertEqual(imports, "")
            self.assertEqual(summary["import_categories"], [])

    def test_helm_state_show_json_format_matches_by_name_and_namespace(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            write_helm_state(state, [{
                "id": "newrelic-kubernetes",
                "name": "newrelic-kubernetes",
                "namespace": "default",
            }], show_json=True)
            helm_file = Path(directory) / "helm.json"
            helm_file.write_text(json.dumps([{
                "name": "newrelic-kubernetes",
                "namespace": "default",
                "chart": "nri-bundle-8.0.32",
                "status": "deployed",
            }]), encoding="utf-8")

            imports, _, _ = self._reconcile(
                state, inventory([]),
                environment={**BASE_ENV, "TF_VAR_enable_newrelic_kubernetes": "true"},
                helm_inventory=helm_file, remote_helm="present",
            )

            self.assertEqual(imports, "")

    def test_helm_namespace_divergence_blocks_reconciliation(self):
        self._assert_helm_identity_divergence(
            {"id": "newrelic-kubernetes", "name": "newrelic-kubernetes", "namespace": "other"}
        )

    def test_helm_name_divergence_blocks_reconciliation(self):
        self._assert_helm_identity_divergence(
            {"id": "newrelic-kubernetes", "name": "replacement", "namespace": "default"}
        )

    def _assert_helm_identity_divergence(self, attributes):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            write_helm_state(state, [attributes])
            helm_file = Path(directory) / "helm.json"
            helm_file.write_text(json.dumps([{
                "name": "newrelic-kubernetes",
                "namespace": "default",
                "chart": "nri-bundle-8.0.32",
                "status": "deployed",
            }]), encoding="utf-8")

            with self.assertRaisesRegex(ReconciliationError, "Identidade no State diverge.*helm"):
                self._reconcile(
                    state, inventory([]),
                    environment={**BASE_ENV, "TF_VAR_enable_newrelic_kubernetes": "true"},
                    helm_inventory=helm_file, remote_helm="present",
                )

    def test_helm_release_missing_remotely_remains_controlled_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            write_helm_state(state, [{
                "id": "newrelic-kubernetes",
                "name": "newrelic-kubernetes",
                "namespace": "default",
            }])

            with self.assertRaisesRegex(ReconciliationError, "aprovação explícita.*helm"):
                self._reconcile(
                    state, inventory([]),
                    environment={**BASE_ENV, "TF_VAR_enable_newrelic_kubernetes": "true"},
                    remote_helm="absent",
                )

            _, summary, _ = self._reconcile(
                state, inventory([]), approve=True,
                environment={**BASE_ENV, "TF_VAR_enable_newrelic_kubernetes": "true"},
                remote_helm="absent",
            )
            self.assertEqual(summary["recovery_categories"], ["helm"])

    def test_two_helm_state_instances_block_reconciliation(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            attributes = {"id": "newrelic-kubernetes", "name": "newrelic-kubernetes", "namespace": "default"}
            write_helm_state(state, [attributes, attributes])

            with self.assertRaisesRegex(ReconciliationError, "múltiplas instâncias.*Helm"):
                self._reconcile(
                    state, inventory([]),
                    environment={**BASE_ENV, "TF_VAR_enable_newrelic_kubernetes": "true"},
                    remote_helm="absent",
                )

    def test_incomplete_helm_state_attributes_block_even_when_id_matches(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            write_helm_state(state, [{"id": "newrelic-kubernetes", "name": "newrelic-kubernetes"}])
            helm_file = Path(directory) / "helm.json"
            helm_file.write_text(json.dumps([{
                "name": "newrelic-kubernetes",
                "namespace": "default",
                "chart": "nri-bundle-8.0.32",
                "status": "deployed",
            }]), encoding="utf-8")

            with self.assertRaisesRegex(ReconciliationError, "Atributos de name/namespace ausentes.*helm"):
                self._reconcile(
                    state, inventory([]),
                    environment={**BASE_ENV, "TF_VAR_enable_newrelic_kubernetes": "true"},
                    helm_inventory=helm_file, remote_helm="present",
                )

    def test_helm_reconciliation_is_idempotent_without_state_or_inventory_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            write_helm_state(state, [{
                "id": "newrelic-kubernetes",
                "name": "newrelic-kubernetes",
                "namespace": "default",
            }])
            helm_file = Path(directory) / "helm.json"
            helm_file.write_text(json.dumps([{
                "name": "newrelic-kubernetes",
                "namespace": "default",
                "chart": "nri-bundle-8.0.32",
                "status": "deployed",
            }]), encoding="utf-8")
            environment = {**BASE_ENV, "TF_VAR_enable_newrelic_kubernetes": "true"}
            arguments = dict(environment=environment, helm_inventory=helm_file, remote_helm="present")

            first = self._reconcile(state, inventory([]), **arguments)
            second = self._reconcile(state, inventory([]), **arguments)

            self.assertEqual(first, second)

    def test_workflow_requires_manual_reconciliation_approval_and_revalidates_plan_identity(self):
        self.assertIn("approve_reconciliation:", WORKFLOW)
        self.assertIn("default: false", WORKFLOW.split("approve_reconciliation:", 1)[1].split("allow_destructive:", 1)[0])
        self.assertEqual(WORKFLOW.count("NEWRELIC_RECONCILIATION_APPROVED:"), 2)
        self.assertEqual(WORKFLOW.count("scripts/newrelic_reconcile.py"), 2)
        self.assertIn("cmp \"$RUNNER_TEMP/newrelic-reconciliation.current.sha256\" newrelic-reconciliation.sha256", WORKFLOW)
        self.assertIn("terraform apply -input=false newrelic.tfplan", WORKFLOW)
        self.assertNotIn("terraform state rm", WORKFLOW)
        self.assertNotIn("terraform import ", WORKFLOW)


if __name__ == "__main__":
    unittest.main()
