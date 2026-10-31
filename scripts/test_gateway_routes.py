"""Confronta allowlist Terraform com controllers reais no workspace/CI multirrepo."""
import os
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP = Path(os.environ.get("AUTOFLOW_REPO", str(ROOT.parent / "autoflow")))


class GatewayRoutesTest(unittest.TestCase):
    def test_manual_plan_maps_both_branches_and_apply_requires_explicit_authorization(self):
        workflow = (ROOT / ".github/workflows/api-gateway.yml").read_text(encoding="utf-8")
        plan, apply = workflow.split("  plan:", 1)[1].split("  apply:", 1)[0], workflow.split("\n  apply:\n", 1)[1]
        self.assertIn("(github.ref == 'refs/heads/develop' || github.ref == 'refs/heads/main') && github.event_name == 'workflow_dispatch'", plan)
        self.assertNotIn("refs/heads/feature/", plan)
        self.assertIn("environment: ${{ github.ref == 'refs/heads/main' && 'production' || 'homolog' }}", plan)
        self.assertIn("github.ref != 'refs/heads/main' || github.ref_protected", plan)
        self.assertIn("TF_VAR_environment: ${{ github.ref == 'refs/heads/main' && 'production' || 'homolog' }}", plan)
        self.assertIn("TF_VAR_lambda_function_name: autoflow-cpf-validator-${{ github.ref == 'refs/heads/main' && 'production' || 'homolog' }}", plan)
        self.assertIn("(github.ref == 'refs/heads/develop' || github.ref == 'refs/heads/main') && github.event_name == 'workflow_dispatch' && inputs.apply == true", apply)
        self.assertIn("environment: ${{ github.ref == 'refs/heads/main' && 'production' || 'homolog' }}", apply)
        self.assertIn("github.ref != 'refs/heads/main' || github.ref_protected", apply)
        self.assertIn("--approval-gate", apply)
        self.assertIn("TERRAFORM_APPLY_APPROVAL_CONFIGURED: ${{ vars.TERRAFORM_APPLY_APPROVAL_CONFIGURED }}", apply)
        self.assertLess(apply.index("Validar configuração de aprovação no Environment"), apply.index("aws-actions/configure-aws-credentials@v4"))
        self.assertIn("id: gateway_state", plan)
        self.assertIn('echo "initialized=true" >> "$GITHUB_OUTPUT"', plan)
        self.assertIn('echo "initialized=false" >> "$GITHUB_OUTPUT"', plan)
        self.assertIn("vars.AWS_EXPECTED_ACCOUNT_ID", plan)
        self.assertIn("--state-key AWS_TF_STATE_KEY_GATEWAY", plan)
        self.assertIn("--state-key AWS_TF_STATE_KEY_INFRA", plan)
        self.assertIn("--state-key AWS_TF_STATE_KEY_NEWRELIC", plan)

    def test_apply_initializes_locked_providers_before_applying_saved_plan(self):
        workflow = (ROOT / ".github/workflows/api-gateway.yml").read_text(encoding="utf-8")
        apply = workflow.split("\n  apply:\n", 1)[1]
        init_step = apply.split("- name: Inicializar state exclusivo do gateway", 1)[1].split("- name:", 1)[0]
        self.assertIn("working-directory: infra/api-gateway", init_step)
        self.assertIn("terraform init -input=false -lockfile=readonly", init_step)
        self.assertIn('backend-config="bucket=$TF_VAR_terraform_state_bucket"', init_step)
        self.assertIn('backend-config="key=$TF_STATE_KEY"', init_step)
        self.assertIn('backend-config="allowed_account_ids=$TF_VAR_aws_allowed_account_ids"', init_step)
        self.assertLess(apply.index("terraform init -input=false -lockfile=readonly"), apply.index("terraform apply -input=false gateway.tfplan"))

    def test_plan_and_apply_verify_the_same_readonly_lockfile(self):
        workflow = (ROOT / ".github/workflows/api-gateway.yml").read_text(encoding="utf-8")
        plan = workflow.split("  plan:", 1)[1].split("  apply:", 1)[0]
        apply = workflow.split("\n  apply:\n", 1)[1]

        self.assertIn("terraform init -input=false -lockfile=readonly", plan)
        self.assertIn("sha256sum gateway.tfplan.gpg .terraform.lock.hcl gateway.tfplan.commit gateway.tfplan.metadata.json gateway-deployment-config.sha256 > gateway.tfplan.sha256", plan)
        self.assertIn("gateway.tfplan.gpg", plan)
        self.assertIn("--decrypt --output gateway.tfplan gateway.tfplan.gpg", apply)
        self.assertIn("github.event_name == 'workflow_dispatch'", plan)
        self.assertIn("sha256sum --check gateway.tfplan.sha256", apply)

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
        self.assertEqual(workflow.count("Pré-requisito ausente: State VPC/EKS e cluster não encontrados."), 2)
        self.assertIn("terraform_deployment_fingerprint.py api-gateway create", workflow)
        self.assertEqual(workflow.count('head-object --bucket "$TF_VAR_terraform_state_bucket" --key "$TF_VAR_infra_state_key" --expected-bucket-owner "$TF_VAR_expected_account_id"'), 2)
        self.assertNotIn("aws eks list-clusters", workflow)
        self.assertNotIn("aws eks list-nodegroups", workflow)
        self.assertIn('[[ "$TF_STATE_KEY" == "$GITHUB_DEPLOYMENT_ENVIRONMENT/"* ]]', workflow)


if __name__ == "__main__":
    unittest.main()
