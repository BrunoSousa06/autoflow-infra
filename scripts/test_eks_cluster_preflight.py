import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from eks_cluster_preflight import PreflightError, cluster_exists


class EksClusterPreflightTests(unittest.TestCase):
    def test_missing_cluster_after_reset_is_a_supported_first_provision(self):
        missing = subprocess.CalledProcessError(
            254, "aws", stderr="ResourceNotFoundException: No cluster found for name: eks-autoflow"
        )
        with patch("eks_cluster_preflight.subprocess.run", side_effect=missing):
            self.assertFalse(cluster_exists("eks-autoflow", "us-east-1"))

    def test_existing_cluster_is_detected(self):
        with patch(
            "eks_cluster_preflight.subprocess.run",
            return_value=SimpleNamespace(stdout="eks-autoflow\n"),
        ):
            self.assertTrue(cluster_exists("eks-autoflow", "us-east-1"))

    def test_access_denied_is_not_misclassified_as_missing(self):
        denied = subprocess.CalledProcessError(254, "aws", stderr="AccessDeniedException")
        with patch("eks_cluster_preflight.subprocess.run", side_effect=denied):
            with self.assertRaises(PreflightError):
                cluster_exists("eks-autoflow", "us-east-1")

    def test_workflow_uses_an_approved_plan_and_checks_license_only_for_existing_cluster(self):
        from pathlib import Path

        workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/pipeline.yml").read_text(
            encoding="utf-8"
        )
        infra = Path(__file__).resolve().parents[1] / "infra"
        plan = workflow.split("  plan:", 1)[1].split("  apply:", 1)[0]
        apply = workflow.split("\n  apply:\n", 1)[1]
        data_sources = (infra / "data.tf").read_text(encoding="utf-8")
        providers = (infra / "providers.tf").read_text(encoding="utf-8")
        self.assertIn("id: eks_preflight", plan)
        self.assertIn('PLAN_ARGS+=(-var=enable_newrelic_kubernetes=false)', plan)
        self.assertEqual(data_sources.count("count = var.enable_newrelic_kubernetes ? 1 : 0"), 2)
        self.assertIn(' : "https://127.0.0.1"', providers)
        self.assertIn('EKS_CLUSTER_EXISTS: ${{ steps.eks_preflight.outputs.exists }}', plan)
        self.assertIn(
            "if: env.TF_VAR_enable_newrelic_kubernetes == 'true' && steps.eks_preflight.outputs.exists == 'true'",
            apply,
        )
        self.assertIn("needs: plan", apply)
        self.assertIn("required_reviewers", apply)
        self.assertIn("terraform apply -input=false infra.tfplan", apply)
        self.assertNotIn("terraform apply -target", workflow)
        self.assertNotIn("terraform plan", apply)


if __name__ == "__main__":
    unittest.main()
