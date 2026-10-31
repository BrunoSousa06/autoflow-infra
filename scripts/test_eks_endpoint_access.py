import json
import os
import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

from eks_endpoint_access import (
    AwsOperationError,
    LeaseReadError,
    authorize,
    cleanup,
    cleanup_if_lease_exists,
    load_lease,
    reconcile_orphan_leases,
)


class FakeAws:
    def __init__(self, cidrs):
        self.cidrs = set(cidrs)
        self.calls = []
        self.fail_update = False
        self.fail_after_update = False
        self.pending_updates = []

    def __call__(self, *args):
        self.calls.append(args)
        if args[1] == "describe-cluster":
            return {"cluster": {"resourcesVpcConfig": {"publicAccessCidrs": sorted(self.cidrs)}}}
        if args[1] == "update-cluster-config":
            if self.fail_update:
                raise RuntimeError("falha simulada")
            values = next(x for x in args if x.startswith("publicAccessCidrs="))
            self.cidrs = set(values.split("=", 1)[1].split(","))
            if self.fail_after_update:
                raise RuntimeError("falha após atualização simulada")
            return {"update": {"id": "update-1"}}
        if args[1] == "describe-update":
            return {"update": {"status": "Successful"}}
        if args[1] == "list-updates":
            return {"updateIds": list(self.pending_updates)}
        raise AssertionError(args)


class EndpointAccessTests(unittest.TestCase):
    def setUp(self):
        self.lease = None
        self.patches = [
            patch("eks_endpoint_access.save_lease", side_effect=lambda value: setattr(self, "lease", value)),
            patch("eks_endpoint_access.load_lease", side_effect=lambda: self.lease),
            patch("eks_endpoint_access.remove_lease", side_effect=lambda: setattr(self, "lease", None)),
        ]
        for mocked in self.patches:
            mocked.start()
            self.addCleanup(mocked.stop)

    @patch("eks_endpoint_access.time.sleep")
    def test_authorize_preserves_existing_and_waits_for_update(self, _sleep):
        aws = FakeAws({"189.6.8.245/32", "203.0.113.4/32"})
        lease = authorize(aws, "eks-autoflow", "us-east-1", "198.51.100.7", ["189.6.8.245/32"])
        self.assertEqual(aws.cidrs, {"189.6.8.245/32", "203.0.113.4/32", "198.51.100.7/32"})
        self.assertEqual(lease["original_cidrs"], ["189.6.8.245/32", "203.0.113.4/32"])
        self.assertEqual([c[1] for c in aws.calls].count("describe-update"), 1)

    def test_fails_closed_if_permanent_cidr_missing(self):
        aws = FakeAws({"203.0.113.4/32"})
        with self.assertRaises(RuntimeError):
            authorize(aws, "eks-autoflow", "us-east-1", "198.51.100.7", ["189.6.8.245/32"])
        self.assertFalse(any(c[1] == "update-cluster-config" for c in aws.calls))

    def test_missing_cluster_skips_authorization_but_aws_errors_fail(self):
        from eks_endpoint_access import cluster_config
        missing = __import__("subprocess").CalledProcessError(1, "aws", stderr="ResourceNotFoundException: cluster not found")
        self.assertIsNone(cluster_config(lambda *_: (_ for _ in ()).throw(missing), "eks-autoflow", "us-east-1"))
        missing_aws_cli = AwsOperationError("eks describe-cluster", __import__("subprocess").CalledProcessError(
            254, "aws", stderr="An error occurred (ResourceNotFoundException) when calling DescribeCluster: absent"
        ))
        self.assertIsNone(cluster_config(lambda *_: (_ for _ in ()).throw(missing_aws_cli), "eks-autoflow", "us-east-1"))
        error = __import__("subprocess").CalledProcessError(1, "aws", stderr="AccessDeniedException")
        with self.assertRaises(__import__("subprocess").CalledProcessError):
            cluster_config(lambda *_: (_ for _ in ()).throw(error), "eks-autoflow", "us-east-1")

    def test_failure_does_not_change_cidrs(self):
        aws = FakeAws({"189.6.8.245/32"})
        aws.fail_update = True
        with self.assertRaisesRegex(RuntimeError, "simulada"):
            authorize(aws, "eks-autoflow", "us-east-1", "198.51.100.7", ["189.6.8.245/32"])
        self.assertEqual(aws.cidrs, {"189.6.8.245/32"})

    @patch("eks_endpoint_access.time.sleep")
    def test_cleanup_recovers_original_cidrs_after_authorize_update_failure(self, _sleep):
        aws = FakeAws({"189.6.8.245/32", "203.0.113.4/32"})
        aws.fail_after_update = True
        with self.assertRaisesRegex(RuntimeError, "após atualização simulada"):
            authorize(aws, "eks-autoflow", "us-east-1", "198.51.100.7", ["189.6.8.245/32"])

        self.assertIsNotNone(self.lease)
        aws.fail_after_update = False
        self.assertTrue(cleanup_if_lease_exists(aws, "eks-autoflow", "us-east-1"))
        self.assertEqual(aws.cidrs, {"189.6.8.245/32", "203.0.113.4/32"})
        self.assertIsNone(self.lease)

    @patch("eks_endpoint_access.time.sleep")
    def test_cleanup_removes_only_runner_ip_and_restores_original_cidrs(self, _sleep):
        aws = FakeAws({"189.6.8.245/32", "198.51.100.7/32"})
        cleanup(aws, "eks-autoflow", "us-east-1", {
            "temporary_cidr": "198.51.100.7/32", "original_cidrs": ["189.6.8.245/32", "203.0.113.4/32"]
        })
        self.assertEqual(aws.cidrs, {"189.6.8.245/32", "203.0.113.4/32"})
        self.assertEqual([c[1] for c in aws.calls].count("describe-update"), 1)

    @patch("eks_endpoint_access.time.sleep")
    def test_cleanup_skips_update_and_removes_lease_when_cidrs_are_already_restored(self, _sleep):
        aws = FakeAws({"189.6.8.245/32", "203.0.113.4/32"})
        cleanup(aws, "eks-autoflow", "us-east-1", {
            "temporary_cidr": "198.51.100.7/32", "original_cidrs": ["189.6.8.245/32", "203.0.113.4/32"]
        })
        self.assertFalse(any(call[1] == "update-cluster-config" for call in aws.calls))
        self.assertIsNone(self.lease)

    @patch("eks_endpoint_access.time.sleep")
    def test_cleanup_waits_for_in_progress_update_before_requesting_restoration(self, _sleep):
        aws = FakeAws({"189.6.8.245/32", "198.51.100.7/32"})
        aws.pending_updates = ["existing-update"]
        cleanup(aws, "eks-autoflow", "us-east-1", {
            "temporary_cidr": "198.51.100.7/32", "original_cidrs": ["189.6.8.245/32"]
        })
        operations = [call[1] for call in aws.calls]
        self.assertLess(operations.index("list-updates"), operations.index("update-cluster-config"))

    @patch("eks_endpoint_access.time.sleep")
    def test_cleanup_retries_only_transient_resource_in_use_conflicts(self, _sleep):
        aws = FakeAws({"189.6.8.245/32", "198.51.100.7/32"})
        update = aws.__call__
        conflicts = [AwsOperationError("eks update-cluster-config", __import__("subprocess").CalledProcessError(
            254, "aws", stderr="An error occurred (ResourceInUseException) when calling UpdateClusterConfig: busy"
        ))]

        def with_one_conflict(*args):
            if args[1] == "update-cluster-config" and conflicts:
                raise conflicts.pop()
            return update(*args)

        cleanup(with_one_conflict, "eks-autoflow", "us-east-1", {
            "temporary_cidr": "198.51.100.7/32", "original_cidrs": ["189.6.8.245/32"]
        })
        self.assertEqual([call[1] for call in aws.calls].count("update-cluster-config"), 1)

    def test_permission_errors_are_not_retried_and_diagnostic_reports_aws_code(self):
        import subprocess

        error = AwsOperationError("eks update-cluster-config", subprocess.CalledProcessError(
            254, "aws", stderr="An error occurred (AccessDeniedException) when calling UpdateClusterConfig: private"
        ))
        self.assertIn("AccessDeniedException", str(error))
        self.assertNotIn("private", str(error))
        self.lease = {
            "temporary_cidr": "198.51.100.7/32", "original_cidrs": ["189.6.8.245/32"]
        }
        aws = FakeAws({"189.6.8.245/32", "198.51.100.7/32"})
        calls = []

        def denied(*args):
            calls.append(args[1])
            if args[1] == "update-cluster-config":
                raise error
            return aws(*args)

        with self.assertRaises(AwsOperationError):
            cleanup(denied, "eks-autoflow", "us-east-1", {
                "temporary_cidr": "198.51.100.7/32", "original_cidrs": ["189.6.8.245/32"]
            })
        self.assertEqual(calls.count("update-cluster-config"), 1)
        self.assertIsNotNone(self.lease)

    def test_orphan_reconciliation_skips_active_runs_and_current_run(self):
        runs = [
            {"id": 101, "run_attempt": 2, "status": "in_progress"},
            {"id": 102, "run_attempt": 1, "status": "completed"},
            {"id": 103, "run_attempt": 1, "status": "completed"},
        ]
        with patch.dict(os.environ, {"GITHUB_DEPLOYMENT_ENVIRONMENT": "homolog"}), patch("eks_endpoint_access.newrelic_workflow_runs", return_value=runs), patch(
            "eks_endpoint_access.load_lease", return_value=None
        ) as load, patch("eks_endpoint_access._cleanup") as cleanup_orphan:
            self.assertEqual(
                reconcile_orphan_leases(
                    FakeAws(set()), "eks-autoflow", "us-east-1", "token", "org/repo", "103", 1
                ),
                0,
            )
        self.assertEqual(load.call_count, 8)
        self.assertEqual(
            [call.args[0] for call in load.call_args_list],
            [
                "ci/homolog/eks-endpoint-lease-newrelic-101-1-plan.json",
                "ci/eks-endpoint-lease-newrelic-101-1-plan.json",
                "ci/homolog/eks-endpoint-lease-newrelic-101-1-apply.json",
                "ci/eks-endpoint-lease-newrelic-101-1-apply.json",
                "ci/homolog/eks-endpoint-lease-newrelic-102-1-plan.json",
                "ci/eks-endpoint-lease-newrelic-102-1-plan.json",
                "ci/homolog/eks-endpoint-lease-newrelic-102-1-apply.json",
                "ci/eks-endpoint-lease-newrelic-102-1-apply.json",
            ],
        )
        cleanup_orphan.assert_not_called()

    def test_orphan_reconciliation_restores_only_a_valid_completed_run_lease(self):
        run = {"id": 205, "run_attempt": 2, "status": "completed"}
        key = "ci/homolog/eks-endpoint-lease-newrelic-205-1-plan.json"
        lease = {"temporary_cidr": "20.106.182.211/32", "original_cidrs": ["189.6.8.245/32"]}
        with patch.dict(os.environ, {"GITHUB_DEPLOYMENT_ENVIRONMENT": "homolog"}), patch("eks_endpoint_access.newrelic_workflow_runs", return_value=[run]), patch(
            "eks_endpoint_access.load_lease", side_effect=lambda candidate: lease if candidate == key else None
        ) as load, patch("eks_endpoint_access._cleanup") as cleanup_orphan:
            count = reconcile_orphan_leases(
                FakeAws(set()), "eks-autoflow", "us-east-1", "token", "org/repo", "999", 1
            )
        self.assertEqual(count, 1)
        cleanup_orphan.assert_called_once()
        self.assertEqual(cleanup_orphan.call_args.args[1:], ("eks-autoflow", "us-east-1", lease))
        self.assertEqual(cleanup_orphan.call_args.kwargs, {"lease_key": key})

    def test_invalid_orphan_lease_fails_closed_without_cleanup(self):
        run = {"id": 206, "run_attempt": 1, "status": "completed"}
        with patch.dict(os.environ, {"GITHUB_DEPLOYMENT_ENVIRONMENT": "homolog"}), patch("eks_endpoint_access.newrelic_workflow_runs", return_value=[run]), patch(
            "eks_endpoint_access.load_lease", side_effect=LeaseReadError("invalid_lease")
        ), patch("eks_endpoint_access._cleanup") as cleanup_orphan:
            with self.assertRaises(LeaseReadError):
                reconcile_orphan_leases(
                    FakeAws(set()), "eks-autoflow", "us-east-1", "token", "org/repo", "999", 1
                )
        cleanup_orphan.assert_not_called()

    def test_production_orphan_reconciliation_does_not_read_homolog_leases(self):
        run = {"id": 207, "run_attempt": 1, "status": "completed"}
        with patch.dict(os.environ, {"GITHUB_DEPLOYMENT_ENVIRONMENT": "production"}), patch(
            "eks_endpoint_access.newrelic_workflow_runs", return_value=[run]
        ), patch("eks_endpoint_access.load_lease", return_value=None) as load:
            self.assertEqual(
                reconcile_orphan_leases(
                    FakeAws(set()), "eks-autoflow-production", "us-east-1", "token", "org/repo", "999", 1
                ),
                0,
            )
        self.assertEqual(
            [call.args[0] for call in load.call_args_list],
            [
                "ci/production/eks-endpoint-lease-newrelic-207-1-plan.json",
                "ci/production/eks-endpoint-lease-newrelic-207-1-apply.json",
            ],
        )

    @patch("eks_endpoint_access.urlopen")
    def test_workflow_run_history_is_paginated_with_token_header(self, urlopen):
        from eks_endpoint_access import newrelic_workflow_runs

        first_page = [{"id": value} for value in range(100)]
        second_page = [{"id": 101}]
        urlopen.side_effect = [
            BytesIO(json.dumps({"workflow_runs": first_page}).encode()),
            BytesIO(json.dumps({"workflow_runs": second_page}).encode()),
        ]
        runs = newrelic_workflow_runs("opaque-token", "org/repo")
        self.assertEqual(len(runs), 101)
        self.assertIn("page=2", urlopen.call_args_list[1].args[0].full_url)
        self.assertEqual(urlopen.call_args_list[0].args[0].get_header("Authorization"), "Bearer opaque-token")

    def test_cleanup_retains_lease_when_restored_cidrs_do_not_confirm(self):
        aws = FakeAws({"189.6.8.245/32", "20.106.182.211/32"})
        update = aws.__call__

        def drift_after_update(*args):
            result = update(*args)
            if args[1] == "update-cluster-config":
                aws.cidrs.add("192.0.2.9/32")
            return result

        with patch("eks_endpoint_access.remove_lease") as remove:
            with self.assertRaisesRegex(RuntimeError, "não confirmados"):
                cleanup(drift_after_update, "eks-autoflow", "us-east-1", {
                    "temporary_cidr": "20.106.182.211/32", "original_cidrs": ["189.6.8.245/32"]
                })
        remove.assert_not_called()

    def test_concurrency_is_configured_at_workflow_scope(self):
        from pathlib import Path
        workflow = Path(__file__).parents[1] / ".github/workflows/pipeline.yml"
        content = workflow.read_text(encoding="utf-8")
        newrelic = (Path(__file__).parents[1] / ".github/workflows/newrelic.yml").read_text(encoding="utf-8")
        self.assertIn("group: autoflow-eks-endpoint-deploy-${{ github.ref_name }}", content)
        self.assertIn("group: autoflow-eks-endpoint-deploy-${{ github.ref_name }}", newrelic)
        self.assertIn("cancel-in-progress: false", content)
        self.assertIn("python scripts/eks_endpoint_access.py reconcile-orphans", newrelic)
        for job in ("plan", "apply"):
            section = newrelic.split(f"\n  {job}:", 1)[1]
            reconcile_position = section.index("python scripts/eks_endpoint_access.py reconcile-orphans")
            authorize_position = section.index("python scripts/eks_endpoint_access.py authorize")
            self.assertLess(reconcile_position, authorize_position)
        plan = content.split("  plan:", 1)[1].split("  apply:", 1)[0]
        apply = content.split("\n  apply:\n", 1)[1]
        selected_environment = "environment: ${{ github.ref == 'refs/heads/main' && 'production' || 'homolog' }}"
        self.assertIn(selected_environment, plan)
        self.assertIn(selected_environment, apply)
        self.assertIn("AWS_REGION: ${{ vars.AWS_REGION }}", plan)
        self.assertIn("AWS_REGION: ${{ vars.AWS_REGION }}", apply)
        self.assertIn("environment: ${{ github.ref == 'refs/heads/main' && 'production' || 'homolog' }}", apply)
        self.assertIn("scripts/validate_github_environment.py", apply)
        self.assertIn("--approval-gate", apply)

    def test_manual_plan_and_apply_require_explicit_authorization_and_environment_approval(self):
        from pathlib import Path
        workflow = Path(__file__).parents[1] / ".github/workflows/pipeline.yml"
        content = workflow.read_text(encoding="utf-8")
        plan = content.split("  plan:", 1)[1].split("  apply:", 1)[0]
        apply = content.split("\n  apply:\n", 1)[1]
        self.assertIn("github.event_name == 'workflow_dispatch' && inputs.approve_state_bucket_creation != true", plan)
        self.assertIn("default: false", content.split("approve_state_bucket_creation:", 1)[1].split("permissions:", 1)[0])
        self.assertIn("default: false", content.split("approve_eks_state_reconciliation:", 1)[1].split("allow_destructive:", 1)[0])
        self.assertIn("description: Autorizar exclusões/substituições após revisar o plan", content)
        self.assertIn("python ../scripts/review_eks_plan.py infra-plan.json --allow-destructive \"$ALLOW_DESTRUCTIVE\"", content)
        self.assertIn("default: false", content.split("allow_destructive:", 1)[1].split("permissions:", 1)[0])
        self.assertIn("ALLOW_DESTRUCTIVE: ${{ github.event_name == 'workflow_dispatch' && inputs.allow_destructive && 'true' || 'false' }}", plan)
        self.assertIn("ALLOW_DESTRUCTIVE: ${{ github.event_name == 'workflow_dispatch' && inputs.allow_destructive && 'true' || 'false' }}", apply)
        self.assertNotIn("github.event_name == 'push' && 'true'", plan)
        self.assertNotIn("github.event_name == 'push' && 'true'", apply)
        self.assertIn("inputs.approve_eks_state_reconciliation && 'true' || 'false'", plan)
        self.assertIn("inputs.approve_eks_state_reconciliation && 'true' || 'false'", apply)
        self.assertIn("prepare_eks_network_imports.py", plan)
        self.assertIn("prepare_eks_network_imports.py", apply)
        self.assertIn('--allow-reconciliation "$ALLOW_EKS_STATE_RECONCILIATION"', plan)
        self.assertIn('--allow-imports "$ALLOW_EKS_STATE_RECONCILIATION"', apply)
        plan_authorize = plan.split("- name: Autorizar IP público exclusivo no EKS e aguardar atualização", 1)[1].split("- uses:", 1)[0]
        apply_authorize = apply.split("- name: Atualizar endpoint e aguardar conclusão", 1)[1].split("- uses:", 1)[0]
        self.assertIn("if: steps.eks_preflight.outputs.exists == 'true'", plan_authorize)
        self.assertIn("if: steps.eks_preflight.outputs.exists == 'true'", apply_authorize)
        self.assertIn("steps.authorize_eks.outcome != 'skipped'", plan)
        self.assertIn("steps.authorize_eks.outcome != 'skipped'", apply)
        self.assertNotIn("github.event_name == 'push'", plan + apply)
        self.assertIn("github.event_name == 'workflow_dispatch' && inputs.apply == true", apply)
        self.assertIn("inputs.approve_state_bucket_creation != true", apply)
        self.assertNotIn("--approval-gate", plan)
        selected_environment = "environment: ${{ github.ref == 'refs/heads/main' && 'production' || 'homolog' }}"
        self.assertIn(selected_environment, apply)
        self.assertIn("python scripts/verify_aws_account.py", plan)
        self.assertIn("python scripts/verify_aws_account.py", apply)
        self.assertNotIn("TF_VAR_enable_newrelic", plan)
        self.assertIn("check-legacy-plan", plan)
        self.assertIn("check-legacy-plan", apply)
        self.assertIn("needs: plan", apply)
        self.assertIn("infra-tfplan-${{ github.run_id }}-${{ github.run_attempt }}-${{ github.sha }}", apply)
        download_position = apply.index("- uses: actions/download-artifact@v4")
        integrity_position = apply.index("- name: Validar fingerprint, run, commit e integridade antes de qualquer acesso AWS")
        decrypt_position = apply.index("gpg --batch --yes --pinentry-mode loopback --passphrase-fd 0 --decrypt --output infra.tfplan infra.tfplan.gpg")
        configure_aws_position = apply.index("aws-actions/configure-aws-credentials@v4")
        init_position = apply.index("- name: Inicializar Terraform")
        reconcile_position = apply.index("prepare_eks_network_imports.py")
        show_position = apply.index("terraform show -json infra.tfplan > infra-plan.json")
        newrelic_guard_position = apply.index("python ../scripts/newrelic_pipeline_guard.py check-legacy-plan infra-plan.json", show_position)
        eks_guard_position = apply.index('python ../scripts/review_eks_plan.py infra-plan.json --allow-destructive "$ALLOW_DESTRUCTIVE"', show_position)
        apply_position = apply.index("terraform apply -input=false infra.tfplan")
        self.assertLess(download_position, integrity_position)
        self.assertLess(integrity_position, decrypt_position)
        self.assertLess(decrypt_position, configure_aws_position)
        self.assertLess(decrypt_position, init_position)
        self.assertLess(init_position, show_position)
        self.assertLess(init_position, reconcile_position)
        self.assertLess(reconcile_position, show_position)
        self.assertLess(show_position, newrelic_guard_position)
        self.assertLess(newrelic_guard_position, eks_guard_position)
        self.assertLess(eks_guard_position, apply_position)
        integrity_step = apply.split("- name: Validar fingerprint, run, commit e integridade antes de qualquer acesso AWS", 1)[1].split("- name:", 1)[0]
        self.assertIn('test "$(cat infra.tfplan.commit)" = "$GITHUB_SHA"', integrity_step)
        self.assertIn("sha256sum --check infra.tfplan.sha256", integrity_step)
        self.assertIn("terraform_deployment_fingerprint.py vpc-eks verify", integrity_step)
        self.assertNotIn("newrelic", integrity_step)
        self.assertNotIn("terraform show", integrity_step)
        init_step = apply.split("- name: Inicializar Terraform", 1)[1].split("- name:", 1)[0]
        self.assertIn("working-directory: infra", init_step)
        self.assertIn("terraform init -input=false -lockfile=readonly -reconfigure", init_step)
        self.assertIn('backend-config="bucket=$TF_STATE_BUCKET"', init_step)
        self.assertLess(apply.index("terraform init -input=false -lockfile=readonly"), apply.index("terraform show -json infra.tfplan"))
        self.assertIn("terraform apply -input=false infra.tfplan", apply)
        self.assertNotIn("terraform plan", apply)
        self.assertIn("allow_destructive", content)
        self.assertNotIn("sys.exit(bool(changes))", plan)
        self.assertIn("review_eks_plan.py", plan)
        self.assertNotIn("kubectl rollout status", apply)
        self.assertNotIn("backend-deployment", apply)
        self.assertNotIn("frontend-deployment", apply)

    def test_terraform_keeps_permanent_cidr_and_ignores_temporary_lease_drift(self):
        from pathlib import Path
        root = Path(__file__).parents[1]
        variables = (root / "infra/vars.tf").read_text(encoding="utf-8")
        cluster = (root / "infra/eks-cluster.tf").read_text(encoding="utf-8")
        workflow = (root / ".github/workflows/pipeline.yml").read_text(encoding="utf-8")
        cidrs_variable = variables.split('variable "cluster_endpoint_public_access_cidrs"', 1)[1].split("\n}", 1)[0]
        self.assertIn('default     = ["189.6.8.245/32"]', cidrs_variable)
        self.assertIn("ignore_changes = [vpc_config[0].public_access_cidrs]", cluster)
        self.assertIn("public_access_cidrs     = var.cluster_endpoint_public_access_cidrs", cluster)
        self.assertIn('cidr != "0.0.0.0/0"', cidrs_variable)
        self.assertNotIn("TF_VAR_cluster_endpoint_public_access_cidrs", workflow)

    def test_missing_lease_is_successful_cleanup_without_endpoint_changes(self):
        aws = FakeAws({"189.6.8.245/32"})
        with patch("eks_endpoint_access.load_lease", return_value=None):
            self.assertFalse(cleanup_if_lease_exists(aws, "eks-autoflow", "us-east-1"))
        self.assertEqual(aws.calls, [])

    def test_confirmed_missing_s3_lease_allows_cleanup_without_cidr_changes(self):
        aws = FakeAws({"189.6.8.245/32", "198.51.100.7/32"})
        missing = SimpleNamespace(
            returncode=1,
            stderr="An error occurred (404) when calling the HeadObject operation: Not Found",
            stdout="",
        )
        with patch.dict(os.environ, {"EKS_LEASE_BUCKET": "state-bucket", "EKS_LEASE_KEY": "ci/lease.json"}), patch(
            "eks_endpoint_access.subprocess.run", return_value=missing
        ) as run, patch("eks_endpoint_access.load_lease", wraps=load_lease):
            self.assertFalse(cleanup_if_lease_exists(aws, "eks-autoflow", "us-east-1"))
        self.assertEqual(aws.calls, [])
        self.assertEqual(run.call_count, 1)

    def test_reset_cluster_discards_only_the_stale_lease_without_endpoint_mutation(self):
        lease = {"temporary_cidr": "198.51.100.7/32", "original_cidrs": ["189.6.8.245/32"]}
        with patch("eks_endpoint_access.cluster_config", return_value=None), patch(
            "eks_endpoint_access.remove_lease"
        ) as remove_lease:
            cleanup(FakeAws(set()), "eks-autoflow", "us-east-1", lease)
        remove_lease.assert_called_once_with()

    def test_s3_missing_key_and_404_are_treated_as_absent_lease(self):
        errors = (
            "fatal error: An error occurred (NoSuchKey) when calling the HeadObject operation",
            "fatal error: An error occurred (404) when calling the HeadObject operation: Key not found",
        )
        with patch.dict(os.environ, {"EKS_LEASE_BUCKET": "state-bucket", "EKS_LEASE_KEY": "ci/lease.json"}):
            for stderr in errors:
                with self.subTest(stderr=stderr), patch("eks_endpoint_access.subprocess.run", return_value=SimpleNamespace(returncode=1, stderr=stderr, stdout="")) as run:
                    self.assertIsNone(load_lease())
                    self.assertEqual(run.call_count, 1)
                    self.assertEqual(run.call_args.args[0][1:3], ["s3api", "head-object"])

    def test_s3_existing_lease_is_read_after_successful_head_object(self):
        lease_json = '{"temporary_cidr":"198.51.100.7/32","original_cidrs":["189.6.8.245/32"]}'
        with patch.dict(os.environ, {"EKS_LEASE_BUCKET": "state-bucket", "EKS_LEASE_KEY": "ci/lease.json"}), patch(
            "eks_endpoint_access.subprocess.run",
            side_effect=(
                SimpleNamespace(returncode=0, stderr="", stdout='{"ContentLength":86}'),
                SimpleNamespace(returncode=0, stderr="", stdout=lease_json),
            ),
        ) as run:
            self.assertEqual(load_lease(), {
                "temporary_cidr": "198.51.100.7/32",
                "original_cidrs": ["189.6.8.245/32"],
            })

        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].args[0][1:3], ["s3api", "head-object"])
        self.assertEqual(run.call_args_list[1].args[0][1:3], ["s3", "cp"])

    def test_s3_copy_failure_after_successful_head_object_fails_closed(self):
        with patch.dict(os.environ, {"EKS_LEASE_BUCKET": "state-bucket", "EKS_LEASE_KEY": "ci/lease.json"}), patch(
            "eks_endpoint_access.subprocess.run",
            side_effect=(
                SimpleNamespace(returncode=0, stderr="", stdout="{}"),
                SimpleNamespace(returncode=1, stderr="An error occurred (404) when calling the HeadObject operation", stdout=""),
            ),
        ):
            with self.assertRaises(LeaseReadError) as raised:
                load_lease()
        self.assertEqual(raised.exception.category, "unexpected")

    def test_s3_auth_permission_connectivity_and_unexpected_errors_are_distinguished(self):
        errors = {
            "ExpiredToken": "An error occurred (ExpiredToken) when calling HeadObject",
            "AccessDenied": "An error occurred (AccessDenied) when calling HeadObject",
            "connectivity": "Could not connect to the endpoint URL: https://s3.invalid",
            "missing_bucket": "An error occurred (NoSuchBucket) when calling HeadObject",
            "unrelated_404": "Proxy returned HTTP 404 while connecting to S3",
            "unexpected": "An error occurred (ServiceUnavailable) when calling HeadObject",
        }
        with patch.dict(os.environ, {"EKS_LEASE_BUCKET": "state-bucket", "EKS_LEASE_KEY": "ci/lease.json"}):
            for category, stderr in errors.items():
                with self.subTest(category=category), patch("eks_endpoint_access.subprocess.run", return_value=SimpleNamespace(returncode=1, stderr=stderr, stdout="")) as run:
                    with self.assertRaises(LeaseReadError) as raised:
                        load_lease()
                    self.assertEqual(raised.exception.category, {
                        "ExpiredToken": "expired_token",
                        "AccessDenied": "access_denied",
                        "connectivity": "connectivity",
                        "missing_bucket": "unexpected",
                        "unrelated_404": "unexpected",
                        "unexpected": "unexpected",
                    }[category])
                    self.assertNotIn(stderr, str(raised.exception))
                    self.assertEqual(run.call_count, 1)

    def test_unexpected_lease_read_reports_safe_operation_metadata_only(self):
        secret_marker = "credential-secret-marker"
        stderr = f"An error occurred (ServiceUnavailable) when calling HeadObject: {secret_marker}"
        with patch.dict(os.environ, {"EKS_LEASE_BUCKET": "state-bucket", "EKS_LEASE_KEY": "ci/lease.json"}), patch(
            "eks_endpoint_access.subprocess.run",
            return_value=SimpleNamespace(returncode=7, stderr=stderr, stdout=""),
        ):
            with self.assertRaises(LeaseReadError) as raised:
                load_lease()

        diagnostic = str(raised.exception)
        self.assertIn('"operation":"aws s3api head-object"', diagnostic)
        self.assertIn('"bucket":"state-bucket"', diagnostic)
        self.assertIn('"key":"ci/lease.json"', diagnostic)
        self.assertIn('"exit_code":7', diagnostic)
        self.assertIn('"category":"unexpected"', diagnostic)
        self.assertNotIn(secret_marker, diagnostic)

    def test_untrusted_lease_never_reads_or_updates_cluster_cidrs(self):
        aws = FakeAws({"189.6.8.245/32", "198.51.100.7/32"})
        invalid_leases = (
            {"temporary_cidr": "189.6.8.245/32", "original_cidrs": ["189.6.8.245/32"]},
            {"temporary_cidr": "198.51.100.7/32", "original_cidrs": ["203.0.113.1/32"]},
            {"temporary_cidr": "invalid", "original_cidrs": ["189.6.8.245/32"]},
        )
        for lease in invalid_leases:
            with self.subTest(lease=lease), self.assertRaises(LeaseReadError):
                cleanup(aws, "eks-autoflow", "us-east-1", lease)
        self.assertEqual(aws.calls, [])


if __name__ == "__main__":
    unittest.main()
