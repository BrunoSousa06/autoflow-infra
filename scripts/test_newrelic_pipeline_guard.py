import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from newrelic_pipeline_guard import (
    ConfigurationError,
    check_plan,
    check_legacy_root_plan,
    config_fingerprint,
    validate_inputs,
    verify_kubernetes_secret,
    verify_application_workloads,
)


class NewRelicPipelineGuardTests(unittest.TestCase):
    def setUp(self):
        self.environment = {
            "AWS_EXPECTED_ACCOUNT_ID": "1" * 12,
            "TF_VAR_enable_newrelic_kubernetes": "false",
            "TF_VAR_enable_newrelic_account_resources": "false",
            "TF_VAR_newrelic_environment": "test",
        }

    def enabled_configuration(self):
        self.environment.update(
            {
                "TF_VAR_enable_newrelic_kubernetes": "true",
            }
        )

    def test_missing_enable_variable_fails_closed(self):
        del self.environment["TF_VAR_enable_newrelic_kubernetes"]
        with self.assertRaisesRegex(ConfigurationError, "ENABLE_NEWRELIC_KUBERNETES"):
            validate_inputs(self.environment)

    def test_invalid_enable_variable_fails_closed(self):
        self.environment["TF_VAR_enable_newrelic_kubernetes"] = "yes"
        with self.assertRaisesRegex(ConfigurationError, "true ou false"):
            validate_inputs(self.environment)

    def test_enabled_kubernetes_uses_stable_defaults_without_account_credentials(self):
        self.environment["TF_VAR_enable_newrelic_kubernetes"] = "true"
        self.assertEqual(validate_inputs(self.environment), (True, False))

    def test_enabled_kubernetes_accepts_valid_external_config(self):
        self.enabled_configuration()
        self.assertEqual(validate_inputs(self.environment), (True, False))

    def test_false_flags_allow_no_new_relic_account_values(self):
        self.assertEqual(validate_inputs(self.environment), (False, False))

    def test_account_resources_require_account_region_and_provider_key(self):
        self.environment["TF_VAR_enable_newrelic_account_resources"] = "true"
        with self.assertRaisesRegex(ConfigurationError, "NEW_RELIC_ACCOUNT_ID"):
            validate_inputs(self.environment)

    def test_automatic_false_cannot_destroy_existing_release(self):
        self.enabled_configuration()
        self.environment["TF_VAR_enable_newrelic_kubernetes"] = "false"
        plan = {
            "resource_changes": [
                {"address": "helm_release.newrelic_kubernetes[0]", "type": "helm_release", "change": {"actions": ["delete"]}}
            ]
        }
        with self.assertRaisesRegex(ConfigurationError, "sem workflow_dispatch"):
            check_plan(plan, self.environment)

    def test_reset_allows_only_stale_helm_state_to_be_removed_while_eks_is_absent(self):
        self.enabled_configuration()
        self.environment["EKS_CLUSTER_EXISTS"] = "false"
        plan = {
            "resource_changes": [
                {"address": "helm_release.newrelic_kubernetes[0]", "type": "helm_release", "change": {"actions": ["delete"]}}
            ]
        }
        check_plan(plan, self.environment)

    def test_enabled_release_deletion_still_fails_when_eks_exists(self):
        self.enabled_configuration()
        self.environment["EKS_CLUSTER_EXISTS"] = "true"
        plan = {
            "resource_changes": [
                {"address": "helm_release.newrelic_kubernetes[0]", "type": "helm_release", "change": {"actions": ["delete"]}}
            ]
        }
        with self.assertRaisesRegex(ConfigurationError, "ainda habilitados"):
            check_plan(plan, self.environment)

    def test_explicit_deactivation_approval_allows_release_removal(self):
        self.enabled_configuration()
        self.environment["TF_VAR_enable_newrelic_kubernetes"] = "false"
        self.environment["NEWRELIC_DEACTIVATION_APPROVED"] = "true"
        plan = {
            "resource_changes": [
                {"address": "helm_release.newrelic_kubernetes[0]", "type": "helm_release", "change": {"actions": ["delete"]}}
            ]
        }
        check_plan(plan, self.environment)

    def test_enabled_resource_cannot_be_deleted_even_with_deactivation_approval(self):
        self.enabled_configuration()
        self.environment["NEWRELIC_DEACTIVATION_APPROVED"] = "true"
        plan = {
            "resource_changes": [
                {"address": "helm_release.newrelic_kubernetes[0]", "type": "helm_release", "change": {"actions": ["delete"]}}
            ]
        }
        with self.assertRaisesRegex(ConfigurationError, "ainda habilitados"):
            check_plan(plan, self.environment)

    def test_non_newrelic_deletes_are_ignored_by_new_relic_guard(self):
        plan = {
            "resource_changes": [
                {"address": "aws_eks_cluster.autoflow", "type": "aws_eks_cluster", "change": {"actions": ["delete"]}}
            ]
        }
        check_plan(plan, self.environment)

    def test_secret_verification_checks_only_presence_without_echoing_value(self):
        secret_data = {"data": {"licenseKey": "c2Vuc2l0aXZlLXZhbHVl"}}
        result = SimpleNamespace(returncode=0, stdout=json.dumps(secret_data), stderr="")
        with patch("newrelic_pipeline_guard.subprocess.run", return_value=result) as run:
            verify_kubernetes_secret(self.environment)
        self.assertEqual(run.call_args.args[0][0:3], ["kubectl", "get", "secret"])

    def test_missing_secret_key_fails_without_showing_secret(self):
        result = SimpleNamespace(returncode=0, stdout='{"data":{}}', stderr="")
        with patch("newrelic_pipeline_guard.subprocess.run", return_value=result):
            with self.assertRaisesRegex(ConfigurationError, "chave configurada está ausente"):
                verify_kubernetes_secret(self.environment)

    def test_empty_or_invalid_secret_value_is_rejected(self):
        for encoded in ("", "not-base64", "===="):
            result = SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"data": {"licenseKey": encoded}}),
                stderr="",
            )
            with self.subTest(encoded=encoded), patch(
                "newrelic_pipeline_guard.subprocess.run", return_value=result
            ):
                with self.assertRaises(ConfigurationError):
                    verify_kubernetes_secret(self.environment)

    def test_failed_license_bootstrap_leaves_no_usable_secret_and_blocks_installation(self):
        failed_bootstrap = SimpleNamespace(returncode=1, stdout="", stderr="bootstrap failed")
        with patch("newrelic_pipeline_guard.subprocess.run", return_value=failed_bootstrap):
            with self.assertRaisesRegex(ConfigurationError, "Secret New Relic ausente"):
                verify_kubernetes_secret(self.environment)

    def test_workload_preflight_requires_ready_backend_frontend_and_services(self):
        from pathlib import Path

        healthy_deployments = {
            "items": [
                {"metadata": {"name": name}, "spec": {"replicas": 2}, "status": {"readyReplicas": 2}}
                for name in ("autoflow-backend", "autoflow-frontend")
            ]
        }
        services = {"items": [
            {"metadata": {"name": name}}
            for name in ("autoflow-backend-internal", "autoflow-frontend-internal")
        ]}
        results = [
            SimpleNamespace(returncode=0, stdout=json.dumps(healthy_deployments)),
            SimpleNamespace(returncode=0, stdout=json.dumps(services)),
        ]
        with patch("newrelic_pipeline_guard.subprocess.run", side_effect=results) as run:
            verify_application_workloads()
        self.assertEqual(run.call_count, 2)

        unhealthy = json.loads(json.dumps(healthy_deployments))
        unhealthy["items"][0]["status"]["readyReplicas"] = 1
        with patch(
            "newrelic_pipeline_guard.subprocess.run",
            side_effect=(
                SimpleNamespace(returncode=0, stdout=json.dumps(unhealthy)),
                SimpleNamespace(returncode=0, stdout=json.dumps(services)),
            ),
        ):
            with self.assertRaisesRegex(ConfigurationError, "não estão prontos"):
                verify_application_workloads()

        workflow = Path(__file__).parents[1] / ".github/workflows/newrelic.yml"
        content = workflow.read_text(encoding="utf-8")
        self.assertEqual(content.count("python scripts/newrelic_pipeline_guard.py verify-workloads"), 2)

    def test_fingerprint_changes_when_flags_or_environment_config_changes(self):
        original = config_fingerprint(self.environment)
        changed = dict(
            self.environment,
            TF_VAR_enable_newrelic_account_resources="true",
            TF_VAR_newrelic_account_id="1234567890123",
            TF_VAR_newrelic_region="US",
            TF_VAR_newrelic_api_key="synthetic-api-key-not-real",
        )
        self.assertNotEqual(original, config_fingerprint(changed))

    def test_fingerprint_changes_on_aws_region_cluster_or_state_key_divergence(self):
        original = config_fingerprint(self.environment)
        for name, value in (
            ("AWS_REGION", "us-west-2"),
            ("TF_VAR_eks_cluster_name", "different-cluster"),
            ("AWS_TF_STATE_KEY_NEWRELIC", "production/newrelic.tfstate"),
        ):
            with self.subTest(name=name):
                self.assertNotEqual(original, config_fingerprint({**self.environment, name: value}))

    def test_synthetic_url_and_locations_must_be_configured_together(self):
        self.environment["TF_VAR_enable_newrelic_account_resources"] = "true"
        self.environment.update(
            {
                "TF_VAR_newrelic_account_id": "1234567890123",
                "TF_VAR_newrelic_region": "US",
                "TF_VAR_newrelic_api_key": "synthetic-api-key-not-real",
            }
        )
        self.environment["TF_VAR_newrelic_synthetic_url"] = "https://synthetic.invalid/"
        with self.assertRaisesRegex(ConfigurationError, "URL Synthetic e locations"):
            validate_inputs(self.environment)

    def test_gateway_dashboard_queries_must_be_valid_json(self):
        self.environment["TF_VAR_newrelic_api_gateway_dashboard_queries"] = "not-json"
        with self.assertRaisesRegex(ConfigurationError, "QUERIES_JSON deve ser uma lista JSON"):
            validate_inputs(self.environment)

    def test_legacy_plan_cannot_destroy_newrelic_resources_even_after_split(self):
        with self.assertRaisesRegex(ConfigurationError, "root legado"):
            check_legacy_root_plan({"resource_changes": [{
                "address": "newrelic_alert_policy.autoflow[0]",
                "type": "newrelic_alert_policy",
                "change": {"actions": ["delete"]},
            }]})
        check_legacy_root_plan({"resource_changes": [{
            "address": "aws_eks_cluster.autoflow",
            "type": "aws_eks_cluster",
            "change": {"actions": ["delete"]},
        }]})

    def test_endpoint_cleanup_runs_only_after_authorization_was_attempted(self):
        from pathlib import Path

        workflow = Path(__file__).parents[1] / ".github/workflows/newrelic.yml"
        content = workflow.read_text(encoding="utf-8")
        plan = content.split("\n  plan:", 1)[1].split("\n  apply:", 1)[0]
        apply = content.split("\n  apply:", 1)[1]

        expected_bucket = "EKS_LEASE_BUCKET: ${{ vars.AWS_TERRAFORM_STATE_BUCKET }}"
        for job, section in (("plan", plan), ("apply", apply)):
            with self.subTest(job=job):
                job_env = section.split("    steps:", 1)[0]
                self.assertIn(expected_bucket, section)
                self.assertIn("AWS_TF_STATE_KEY_INFRA: ${{ vars.AWS_TF_STATE_KEY_INFRA }}", job_env)
                self.assertIn(
                    f"EKS_LEASE_KEY: ci/eks-endpoint-lease-newrelic-${{{{ github.run_id }}}}-${{{{ github.run_attempt }}}}-{job}.json",
                    section,
                )
                credentials_position = section.index("aws-actions/configure-aws-credentials@v4")
                authorization_position = section.index("python scripts/eks_endpoint_access.py authorize")
                self.assertLess(credentials_position, authorization_position)
                authorization = section.split("- name: Autorizar temporariamente o runner no endpoint EKS", 1)[1]
                self.assertIn("id: authorize_eks", authorization.split("- name:", 1)[0])
                cleanup = section.split("- name: Remover autorização temporária do endpoint EKS", 1)[1]
                self.assertIn("if: always() && steps.authorize_eks.outcome != 'skipped'", cleanup)
                self.assertIn("python scripts/eks_endpoint_access.py cleanup", cleanup)

    def test_plan_infra_state_key_is_available_to_pre_credential_validation(self):
        from pathlib import Path

        workflow = Path(__file__).parents[1] / ".github/workflows/newrelic.yml"
        content = workflow.read_text(encoding="utf-8")
        plan = content.split("\n  plan:", 1)[1].split("\n  apply:", 1)[0]
        job_env = plan.split("    steps:", 1)[0]
        validation = plan.split("- name: Validar configuração antes de acessar AWS", 1)[1].split("- uses:", 1)[0]
        credentials_position = plan.index("aws-actions/configure-aws-credentials@v4")

        self.assertIn("AWS_TF_STATE_KEY_INFRA: ${{ vars.AWS_TF_STATE_KEY_INFRA }}", job_env)
        self.assertIn('test -n "$AWS_TF_STATE_KEY_INFRA"', validation)
        self.assertLess(plan.index("Validar configuração antes de acessar AWS"), credentials_position)


if __name__ == "__main__":
    unittest.main()
