"""Confronta allowlist Terraform com controllers reais no workspace/CI multirrepo."""
import os
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP = Path(os.environ.get("AUTOFLOW_REPO", str(ROOT.parent / "autoflow")))


class GatewayRoutesTest(unittest.TestCase):
    def test_manual_dispatch_runs_plan_and_approved_apply_on_develop(self):
        workflow = (ROOT / ".github/workflows/api-gateway.yml").read_text(encoding="utf-8")
        plan, apply = workflow.split("  plan:", 1)[1].split("  apply:", 1)[0], workflow.split("  apply:", 1)[1]
        self.assertIn("github.ref == 'refs/heads/develop' && (github.event_name == 'push' || github.event_name == 'workflow_dispatch')", plan)
        self.assertNotIn("refs/heads/feature/", plan)
        self.assertIn("github.ref == 'refs/heads/develop' && (github.event_name == 'push' || github.event_name == 'workflow_dispatch')", apply)
        self.assertIn("environment: homolog", apply)
        self.assertIn("required_reviewers", apply)

    def test_apply_initializes_locked_providers_before_applying_saved_plan(self):
        workflow = (ROOT / ".github/workflows/api-gateway.yml").read_text(encoding="utf-8")
        apply = workflow.split("  apply:", 1)[1]
        init_step = apply.split("- name: Inicializar state exclusivo do gateway", 1)[1].split("- name:", 1)[0]
        self.assertIn("working-directory: infra/api-gateway", init_step)
        self.assertIn("terraform init -input=false -lockfile=readonly", init_step)
        self.assertIn('backend-config="bucket=$TF_VAR_terraform_state_bucket"', init_step)
        self.assertIn('backend-config="key=$TF_STATE_KEY"', init_step)
        self.assertLess(apply.index("terraform init -input=false -lockfile=readonly"), apply.index("terraform apply -input=false gateway.tfplan"))

    def test_allowlist_corresponde_aos_controllers(self):
        controllers = list((APP / "backend/src/main/java/com/autoflow/presentation").rglob("*Controller.java"))
        self.assertTrue(controllers, "Disponibilize autoflow em AUTOFLOW_REPO")
        expected = set()
        for controller in controllers:
            text = controller.read_text(encoding="utf-8")
            prefix = re.search(r'@RequestMapping\("([^"\n]+)"\)', text)
            if not prefix:
                continue
            for match in re.finditer(r'@(Get|Post|Put|Patch|Delete)Mapping(?:\(([^\n]*)\))?', text):
                suffix = re.search(r'"([^"\n]*)"', match[2] or "")
                path = prefix[1] + (suffix[1] if suffix else "")
                if path != "/auth/login":
                    expected.add((match[1].upper(), path))
        actual = set()
        routes = (ROOT / "infra/api-gateway/routes.tf").read_text(encoding="utf-8")
        for path, methods in re.findall(r'"(/[^"\n]+)"\s*=\s*\[([^\]]+)\]', routes):
            actual.update((method, path) for method in re.findall(r'"([A-Z]+)"', methods))
        self.assertEqual(expected, actual)

    def test_remote_eks_state_absence_is_diagnosed_against_cluster(self):
        workflow = (ROOT / ".github/workflows/api-gateway.yml").read_text(encoding="utf-8")
        self.assertEqual(workflow.count("state_resource_guard.py --bucket \"$TF_VAR_terraform_state_bucket\" --key \"$TF_VAR_infra_state_key\""), 2)
        self.assertEqual(workflow.count("Pré-requisito ausente: State EKS e cluster não encontrados."), 2)
        self.assertNotIn('head-object --bucket "$TF_VAR_terraform_state_bucket" --key "$TF_VAR_infra_state_key"', workflow)


if __name__ == "__main__":
    unittest.main()
