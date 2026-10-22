import unittest
import os
from types import SimpleNamespace
from unittest.mock import patch

from eks_endpoint_access import (
    LeaseReadError,
    authorize,
    cleanup,
    cleanup_if_lease_exists,
    load_lease,
)


class FakeAws:
    def __init__(self, cidrs):
        self.cidrs = set(cidrs)
        self.calls = []
        self.fail_update = False

    def __call__(self, *args):
        self.calls.append(args)
        if args[1] == "describe-cluster":
            return {"cluster": {"resourcesVpcConfig": {"publicAccessCidrs": sorted(self.cidrs)}}}
        if args[1] == "update-cluster-config":
            if self.fail_update:
                raise RuntimeError("falha simulada")
            values = next(x for x in args if x.startswith("publicAccessCidrs="))
            self.cidrs = set(values.split("=", 1)[1].split(","))
            return {"update": {"id": "update-1"}}
        if args[1] == "describe-update":
            return {"update": {"status": "Successful"}}
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
    def test_cleanup_removes_only_runner_ip_and_restores_original_cidrs(self, _sleep):
        aws = FakeAws({"189.6.8.245/32", "198.51.100.7/32"})
        cleanup(aws, "eks-autoflow", "us-east-1", {
            "temporary_cidr": "198.51.100.7/32", "original_cidrs": ["189.6.8.245/32", "203.0.113.4/32"]
        })
        self.assertEqual(aws.cidrs, {"189.6.8.245/32", "203.0.113.4/32"})
        self.assertEqual([c[1] for c in aws.calls].count("describe-update"), 1)

    def test_concurrency_is_configured_at_workflow_scope(self):
        from pathlib import Path
        workflow = Path(__file__).parents[1] / ".github/workflows/pipeline.yml"
        content = workflow.read_text(encoding="utf-8")
        self.assertIn("group: autoflow-eks-endpoint-deploy", content)
        self.assertIn("cancel-in-progress: false", content)
        plan = content.split("  plan:", 1)[1].split("  apply:", 1)[0]
        apply = content.split("\n  apply:\n", 1)[1]
        selected_environment = "environment: ${{ github.ref == 'refs/heads/main' && 'production' || 'homolog' }}"
        self.assertIn(selected_environment, plan)
        self.assertIn(selected_environment, apply)
        self.assertIn("AWS_REGION: ${{ vars.AWS_REGION }}", plan)
        self.assertIn("AWS_REGION: ${{ vars.AWS_REGION }}", apply)
        self.assertIn("required_reviewers", apply)

    def test_develop_push_plans_and_applies_only_after_environment_approval(self):
        from pathlib import Path
        workflow = Path(__file__).parents[1] / ".github/workflows/pipeline.yml"
        content = workflow.read_text(encoding="utf-8")
        plan = content.split("  plan:", 1)[1].split("  apply:", 1)[0]
        apply = content.split("\n  apply:\n", 1)[1]
        self.assertIn("if: (github.ref == 'refs/heads/develop' || github.ref == 'refs/heads/main') && (github.event_name == 'push' || github.event_name == 'workflow_dispatch')", plan)
        self.assertIn("default: true", content.split("approve_state_bucket_creation:", 1)[1].split("permissions:", 1)[0])
        self.assertIn("description: Autorizar exclusões/substituições após revisar o plan", content)
        self.assertIn("python ../scripts/review_eks_plan.py infra-plan.json --allow-destructive \"$ALLOW_DESTRUCTIVE\"", content)
        self.assertIn("default: false", content.split("allow_destructive:", 1)[1].split("permissions:", 1)[0])
        self.assertIn("ALLOW_DESTRUCTIVE: ${{ github.event_name == 'push' && 'true' || (github.event_name == 'workflow_dispatch' && inputs.allow_destructive && 'true' || 'false') }}", plan)
        self.assertIn("ALLOW_DESTRUCTIVE: ${{ github.event_name == 'push' && 'true' || (github.event_name == 'workflow_dispatch' && inputs.allow_destructive && 'true' || 'false') }}", apply)
        self.assertIn("inputs.approve_state_bucket_creation || 'true'", plan)
        self.assertIn("github.event_name == 'push'", apply)
        self.assertIn("github.event_name == 'workflow_dispatch' && inputs.apply", apply)
        self.assertIn("((github.ref == 'refs/heads/develop' && github.event_name == 'push') || ((github.ref == 'refs/heads/develop' || github.ref == 'refs/heads/main') && github.event_name == 'workflow_dispatch' && inputs.apply))", apply)
        selected_environment = "environment: ${{ github.ref == 'refs/heads/main' && 'production' || 'homolog' }}"
        self.assertIn(selected_environment, apply)
        self.assertIn("python scripts/verify_aws_account.py", plan)
        self.assertIn("python scripts/verify_aws_account.py", apply)
        self.assertIn("python scripts/newrelic_pipeline_guard.py validate", plan)
        self.assertIn("python scripts/newrelic_pipeline_guard.py validate", apply)
        self.assertIn("python ../scripts/newrelic_pipeline_guard.py check-plan", plan)
        self.assertIn("python ../scripts/newrelic_pipeline_guard.py check-plan", apply)
        self.assertIn("needs: plan", apply)
        self.assertIn("infra-tfplan-${{ github.run_id }}-${{ github.run_attempt }}-${{ github.sha }}", apply)
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

    def test_s3_missing_key_and_404_are_treated_as_absent_lease(self):
        errors = (
            "fatal error: An error occurred (NoSuchKey) when calling the HeadObject operation",
            "fatal error: An error occurred (404) when calling the HeadObject operation: Key not found",
        )
        with patch.dict(os.environ, {"EKS_LEASE_BUCKET": "state-bucket", "EKS_LEASE_KEY": "ci/lease.json"}):
            for stderr in errors:
                with self.subTest(stderr=stderr), patch("eks_endpoint_access.subprocess.run", return_value=SimpleNamespace(returncode=1, stderr=stderr, stdout="")):
                    self.assertIsNone(load_lease())

    def test_s3_auth_permission_connectivity_and_unexpected_errors_are_distinguished(self):
        errors = {
            "ExpiredToken": "An error occurred (ExpiredToken) when calling HeadObject",
            "AccessDenied": "An error occurred (AccessDenied) when calling HeadObject",
            "connectivity": "Could not connect to the endpoint URL: https://s3.invalid",
            "missing_bucket": "An error occurred (NoSuchBucket) when calling HeadObject",
            "unexpected": "An error occurred (ServiceUnavailable) when calling HeadObject",
        }
        with patch.dict(os.environ, {"EKS_LEASE_BUCKET": "state-bucket", "EKS_LEASE_KEY": "ci/lease.json"}):
            for category, stderr in errors.items():
                with self.subTest(category=category), patch("eks_endpoint_access.subprocess.run", return_value=SimpleNamespace(returncode=1, stderr=stderr, stdout="")):
                    with self.assertRaises(LeaseReadError) as raised:
                        load_lease()
                    self.assertEqual(raised.exception.category, {
                        "ExpiredToken": "expired_token",
                        "AccessDenied": "access_denied",
                        "connectivity": "connectivity",
                        "missing_bucket": "unexpected",
                        "unexpected": "unexpected",
                    }[category])
                    self.assertNotIn(stderr, str(raised.exception))

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
