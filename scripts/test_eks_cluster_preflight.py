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

    def test_cluster_creator_bootstrap_is_disabled_when_operator_entry_is_explicit(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "infra"
        cluster = (root / "eks-cluster.tf").read_text(encoding="utf-8")
        access = (root / "access-entry-eks.tf").read_text(encoding="utf-8")
        self.assertIn('authentication_mode                         = "API"', cluster)
        self.assertIn("bootstrap_cluster_creator_admin_permissions = false", cluster)
        self.assertIn("cluster_name  = aws_eks_cluster.autoflow.name", access)
        self.assertIn("principal_arn = local.effective_access_role_arn", access)
        self.assertIn("AmazonEKSClusterAdminPolicy", access)
        self.assertIn("aws_eks_access_entry.access_entry", access.split("depends_on = [", 1)[1])

    def test_eks_managed_self_ingress_is_not_declared_or_a_node_group_dependency(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "infra"
        security_group = (root / "sg.tf").read_text(encoding="utf-8")
        node_group = (root / "eks-node.tf").read_text(encoding="utf-8")
        self.assertNotIn('resource "aws_vpc_security_group_ingress_rule" "eks_self"', security_group)
        self.assertNotIn("aws_vpc_security_group_ingress_rule.eks_self", node_group)

    def test_access_denied_is_not_misclassified_as_missing(self):
        denied = subprocess.CalledProcessError(254, "aws", stderr="AccessDeniedException")
        with patch("eks_cluster_preflight.subprocess.run", side_effect=denied):
            with self.assertRaises(PreflightError):
                cluster_exists("eks-autoflow", "us-east-1")

    def test_vpc_eks_root_is_separate_from_newrelic_installation(self):
        from pathlib import Path

        workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/pipeline.yml").read_text(
            encoding="utf-8"
        )
        plan = workflow.split("  plan:", 1)[1].split("  apply:", 1)[0]
        apply = workflow.split("\n  apply:\n", 1)[1]
        root = Path(__file__).resolve().parents[1] / "infra"
        nr_workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/newrelic.yml").read_text(encoding="utf-8")
        self.assertNotIn("helm_release", "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.tf")))
        self.assertNotIn("TF_VAR_enable_newrelic", plan)
        self.assertIn("helm_release", (root / "newrelic/kubernetes.tf").read_text(encoding="utf-8"))
        self.assertIn("verify-secret", nr_workflow)
        self.assertIn("check-legacy-plan", workflow)
        self.assertIn("needs: plan", apply)
        self.assertIn("environment: ${{ github.ref == 'refs/heads/main' && 'production' || 'homolog' }}", apply)
        self.assertIn("scripts/validate_github_environment.py", apply)
        self.assertIn("--approval-gate", apply)
        self.assertIn("terraform apply -input=false infra.tfplan", apply)
        self.assertNotIn("terraform apply -target", workflow)
        self.assertNotIn("terraform plan", apply)

    def test_newrelic_plan_configures_kube_access_before_secret_and_helm_checks(self):
        from pathlib import Path

        workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/newrelic.yml").read_text(encoding="utf-8")
        plan = workflow.split("  plan:", 1)[1].split("\n  apply:\n", 1)[0]
        authorize = plan.index("eks_endpoint_access.py authorize")
        kubeconfig = plan.index("aws eks update-kubeconfig")
        secret_check = plan.index("newrelic_pipeline_guard.py verify-secret")
        helm_inventory = plan.index("helm list --all-namespaces")
        self.assertLess(authorize, kubeconfig)
        self.assertLess(kubeconfig, secret_check)
        self.assertLess(secret_check, helm_inventory)


if __name__ == "__main__":
    unittest.main()
