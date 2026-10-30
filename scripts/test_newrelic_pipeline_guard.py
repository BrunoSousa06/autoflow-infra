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

    def test_import_update_and_create_actions_are_allowed_for_approved_reconciliation_plan(self):
        self.environment.update({
            "TF_VAR_enable_newrelic_account_resources": "true",
            "TF_VAR_newrelic_account_id": "123456",
            "TF_VAR_newrelic_region": "US",
            "TF_VAR_newrelic_api_key": "redacted-test-key",
        })
        plan = {
            "resource_changes": [
                {
                    "address": "newrelic_one_dashboard.autoflow[0]",
                    "type": "newrelic_one_dashboard",
                    "change": {"actions": ["no-op"], "importing": {"id": "dashboard-guid"}},
                },
                {
                    "address": "newrelic_nrql_alert_condition.api_error_rate[0]",
                    "type": "newrelic_nrql_alert_condition",
                    "change": {"actions": ["update"]},
                },
                {
                    "address": "newrelic_nrql_alert_condition.api_latency_p95[0]",
                    "type": "newrelic_nrql_alert_condition",
                    "change": {"actions": ["create"]},
                },
            ]
        }

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

    def test_workload_preflight_accepts_healthy_deployments_and_services(self):
        from pathlib import Path

        def response(kind, name, *, ready=1, available=1, desired=1, returncode=0):
            if kind == "services":
                item = {"metadata": {"name": name, "namespace": "default"}}
            else:
                item = {
                    "metadata": {"name": name, "namespace": "default"},
                    "spec": {"replicas": desired},
                    "status": {"readyReplicas": ready, "availableReplicas": available},
                }
            return SimpleNamespace(returncode=returncode, stdout=json.dumps(item), stderr="")

        resources = {
            ("services", "autoflow-backend-internal"): response("services", "autoflow-backend-internal"),
            ("services", "autoflow-frontend-internal"): response("services", "autoflow-frontend-internal"),
            ("deployments", "autoflow-backend"): response("deployments", "autoflow-backend", desired=2, ready=2, available=2),
            ("deployments", "autoflow-frontend"): response("deployments", "autoflow-frontend", desired=1, ready=1, available=1),
        }

        def run(command, **_kwargs):
            return resources[(command[2], command[3])]

        with patch("newrelic_pipeline_guard.subprocess.run", side_effect=run) as mocked:
            verify_application_workloads()
        self.assertEqual(mocked.call_count, 4)

        workflow = Path(__file__).parents[1] / ".github/workflows/newrelic.yml"
        content = workflow.read_text(encoding="utf-8")
        self.assertEqual(content.count("python scripts/newrelic_pipeline_guard.py verify-workloads"), 2)

    @patch("newrelic_pipeline_guard.time.sleep")
    def test_workload_preflight_waits_for_transient_deployment_rollout(self, sleep):
        results = {}
        backend_reads = 0
        for service_name in ("autoflow-backend-internal", "autoflow-frontend-internal"):
            results[("services", service_name)] = SimpleNamespace(
                returncode=0, stdout=json.dumps({"metadata": {"name": service_name, "namespace": "default"}}), stderr=""
            )
        results[("deployments", "autoflow-frontend")] = SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"metadata": {"name": "autoflow-frontend", "namespace": "default"},
                               "spec": {"replicas": 1}, "status": {"readyReplicas": 1, "availableReplicas": 1}}),
            stderr="",
        )

        def run(command, **_kwargs):
            nonlocal backend_reads
            kind, name = command[2], command[3]
            if (kind, name) == ("deployments", "autoflow-backend"):
                backend_reads += 1
                ready = 0 if backend_reads == 1 else 1
                return SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps({"metadata": {"name": name, "namespace": "default"},
                                       "spec": {"replicas": 1},
                                       "status": {"readyReplicas": ready, "availableReplicas": ready}}),
                    stderr="",
                )
            return results[(kind, name)]

        with patch("newrelic_pipeline_guard.subprocess.run", side_effect=run), patch(
            "newrelic_pipeline_guard.time.monotonic", side_effect=(0, 0)
        ):
            verify_application_workloads()
        sleep.assert_called_once()

    def test_workload_preflight_times_out_with_safe_deployment_counts(self):
        clock = [0]

        def run(command, **_kwargs):
            kind, name = command[2], command[3]
            if kind == "services":
                item = {"metadata": {"name": name, "namespace": "default"}}
            else:
                ready = 0
                available = 0
                desired = 2 if name == "autoflow-backend" else 1
                item = {"metadata": {"name": name, "namespace": "default"},
                        "spec": {"replicas": desired},
                        "status": {"readyReplicas": ready, "availableReplicas": available}}
            return SimpleNamespace(returncode=0, stdout=json.dumps(item), stderr="")

        def sleep(seconds):
            clock[0] += seconds

        with patch("newrelic_pipeline_guard.subprocess.run", side_effect=run), patch(
            "newrelic_pipeline_guard.WORKLOAD_READY_TIMEOUT_SECONDS", 10
        ), patch("newrelic_pipeline_guard.WORKLOAD_POLL_INTERVAL_SECONDS", 5), patch(
            "newrelic_pipeline_guard.time.monotonic", side_effect=lambda: clock[0]
        ), patch("newrelic_pipeline_guard.time.sleep", side_effect=sleep):
            with self.assertRaisesRegex(
                ConfigurationError,
                r"Deployment autoflow-backend: desired=2, available=0, ready=0.*Deployment autoflow-frontend: desired=1, available=0, ready=0",
            ):
                verify_application_workloads()

    def test_workload_preflight_names_missing_service(self):
        def run(command, **_kwargs):
            kind, name = command[2], command[3]
            if kind == "services" and name == "autoflow-frontend-internal":
                return SimpleNamespace(returncode=1, stdout="", stderr="NotFound")
            item = {"metadata": {"name": name, "namespace": "default"}}
            if kind == "deployments":
                item.update({"spec": {"replicas": 1}, "status": {"readyReplicas": 1, "availableReplicas": 1}})
            return SimpleNamespace(returncode=0, stdout=json.dumps(item), stderr="")

        with patch("newrelic_pipeline_guard.subprocess.run", side_effect=run):
            with self.assertRaisesRegex(ConfigurationError, "Service autoflow-frontend-internal ausente ou inacessível"):
                verify_application_workloads()

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
                    f"EKS_LEASE_KEY: ci/${{{{ github.ref == 'refs/heads/main' && 'production' || 'homolog' }}}}/eks-endpoint-lease-newrelic-${{{{ github.run_id }}}}-${{{{ github.run_attempt }}}}-{job}.json",
                    section,
                )
                credentials_position = section.index("aws-actions/configure-aws-credentials@v4")
                authorization_position = section.index("python scripts/eks_endpoint_access.py authorize")
                self.assertLess(credentials_position, authorization_position)
                authorization = section.split("- name: Autorizar temporariamente o runner no endpoint EKS", 1)[1]
                self.assertIn("id: authorize_eks", authorization.split("- name:", 1)[0])
                cleanup = section.split("- name: Limpar artefatos temporários e autorização do endpoint EKS", 1)[1]
                self.assertIn("if: always()", cleanup)
                self.assertIn('"${{ steps.authorize_eks.outcome }}" != skipped', cleanup)
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
        self.assertIn('[[ "$AWS_EXPECTED_ACCOUNT_ID" =~ ^[0-9]{12}$ ]]', validation)
        self.assertIn('[[ "$TF_STATE_KEY" == "$GITHUB_DEPLOYMENT_ENVIRONMENT/"* ]]', validation)
        self.assertIn('test "$APPROVAL_CONFIGURED" = true', validation)
        self.assertIn('test "$REVIEWERS" -gt 0', validation)
        self.assertLess(plan.index("Validar configuração antes de acessar AWS"), credentials_position)

    def test_production_push_waits_for_explicit_state_bootstrap_then_runs_continuous_apply(self):
        from pathlib import Path

        workflow = Path(__file__).parents[1] / ".github/workflows/newrelic.yml"
        content = workflow.read_text(encoding="utf-8")
        plan = content.split("\n  plan:", 1)[1].split("\n  apply:", 1)[0]
        apply = content.split("\n  apply:", 1)[1]

        self.assertIn("outputs:", plan)
        self.assertIn("initialized: ${{ steps.newrelic_state.outputs.initialized }}", plan)
        self.assertIn('echo "initialized=true" >> "$GITHUB_OUTPUT"', plan)
        self.assertIn('echo "initialized=false" >> "$GITHUB_OUTPUT"', plan)
        self.assertIn("github.event_name == 'push' && needs.plan.outputs.initialized == 'true'", apply)
        self.assertIn("github.event_name == 'workflow_dispatch' && inputs.apply", apply)
        self.assertLess(apply.index("Validar conta e aprovação efetiva"), apply.index("aws-actions/configure-aws-credentials@v4"))
        self.assertIn('aws s3api head-bucket --bucket "$TF_STATE_BUCKET" --expected-bucket-owner "$AWS_EXPECTED_ACCOUNT_ID"', plan)
        self.assertIn('aws eks describe-cluster --name "$EKS_CLUSTER_NAME"', plan)
        self.assertNotIn("aws eks list-clusters", content)


if __name__ == "__main__":
    unittest.main()
