from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class FeatureWorkflowGuardTests(unittest.TestCase):
    def test_state_bucket_bootstrap_variable_is_limited_to_develop_and_defaults_closed(self):
        workflow = (ROOT / ".github/workflows/pipeline.yml").read_text(encoding="utf-8")
        bootstrap = workflow.split("      - name: Verificar/bootstrap seguro do bucket de Terraform State", 1)[1]
        bootstrap = bootstrap.split("      - name:", 1)[0]

        self.assertIn("github.ref == 'refs/heads/develop' && vars.APPROVE_CREATE == 'true'", bootstrap)
        self.assertIn("github.event_name == 'workflow_dispatch' && inputs.approve_state_bucket_creation", bootstrap)
        self.assertIn("|| 'false'", bootstrap)

    def test_eks_network_reconciliation_variable_is_scoped_and_defaults_closed(self):
        workflow = (ROOT / ".github/workflows/pipeline.yml").read_text(encoding="utf-8")
        plan = workflow.split("  plan:", 1)[1].split("  apply:", 1)[0]
        apply_job = workflow.split("\n  apply:\n", 1)[1]
        network = workflow.split("      - name: Preparar imports declarativos da rede EKS", 1)[1]
        network = network.split("      - name:", 1)[0]
        access = workflow.split("      - name: Preparar imports declarativos de acesso EKS", 1)[1]
        access = access.split("      - name:", 1)[0]
        apply_imports = apply_job.split("      - name: Preparar imports declarativos usados pelo plan aprovado", 1)[1]
        apply_imports = apply_imports.split("      - name:", 1)[0]

        resolution = "${{ github.ref == 'refs/heads/develop' && vars.ALLOW_EKS_STATE_RECONCILIATION == 'true' && 'true' || (github.event_name == 'workflow_dispatch' && inputs.approve_eks_state_reconciliation && 'true' || 'false') }}"
        self.assertIn(f"ALLOW_EKS_STATE_RECONCILIATION: {resolution}", plan)
        self.assertIn(f"ALLOW_EKS_STATE_RECONCILIATION: {resolution}", apply_job)
        self.assertNotIn("vars.ALLOW_EKS_STATE_RECONCILIATION", network)
        self.assertNotIn("        env:\n          ALLOW_EKS_STATE_RECONCILIATION:", network)
        self.assertIn("--allow-reconciliation \"$ALLOW_EKS_STATE_RECONCILIATION\"", network)
        self.assertIn('--allow-imports "$ALLOW_EKS_STATE_RECONCILIATION"', access)
        self.assertNotIn("vars.ALLOW_EKS_STATE_RECONCILIATION", access)
        for output in ("infra/eks-network-imports.auto.tf", "infra/eks-access-imports.auto.tf"):
            self.assertIn(output, plan)
            self.assertIn(output, apply_imports)
        self.assertIn('--allow-imports "$ALLOW_EKS_STATE_RECONCILIATION"', apply_imports)

    def test_eks_feature_branches_run_validation_without_plan_or_apply(self):
        workflow = (ROOT / ".github/workflows/pipeline.yml").read_text(encoding="utf-8")
        plan = workflow.split("  plan:", 1)[1].split("  apply:", 1)[0]
        apply = workflow.split("\n  apply:\n", 1)[1]

        self.assertIn("branches: [develop, main, 'feature/**']", workflow)
        self.assertNotIn("refs/heads/feature/", plan)
        self.assertIn("needs: validate", plan)
        self.assertIn("environment: ${{ github.ref == 'refs/heads/main' && 'production' || 'homolog' }}", plan)
        self.assertNotIn("NEWRELIC_DEACTIVATION_APPROVED", plan)
        self.assertIn("((github.ref == 'refs/heads/develop' && github.event_name == 'push') || ((github.ref == 'refs/heads/develop' || github.ref == 'refs/heads/main') && github.event_name == 'workflow_dispatch' && inputs.apply))", apply)
        self.assertNotIn("refs/heads/feature/", apply)
        self.assertIn("needs: plan", apply)
        self.assertIn("github.ref == 'refs/heads/develop' || github.ref == 'refs/heads/main'", plan)
        self.assertIn("rm -f infra.tfplan infra-plan.json", plan)
        self.assertIn("if: success() && (github.ref == 'refs/heads/develop' || github.ref == 'refs/heads/main')", plan)

    def test_gateway_feature_branches_run_validation_without_plan_or_apply(self):
        workflow = (ROOT / ".github/workflows/api-gateway.yml").read_text(encoding="utf-8")
        plan = workflow.split("  plan:", 1)[1].split("  apply:", 1)[0]
        apply = workflow.split("\n  apply:\n", 1)[1]

        self.assertIn("branches: [develop, main, 'feature/**']", workflow)
        self.assertNotIn("refs/heads/feature/", plan)
        self.assertIn("needs: validate", plan)
        self.assertIn("environment: homolog", plan)
        self.assertNotIn("Exigir Required reviewers no environment para feature Plan", plan)
        self.assertIn("github.ref == 'refs/heads/develop' && (github.event_name == 'push' || github.event_name == 'workflow_dispatch')", apply)
        self.assertNotIn("refs/heads/feature/", apply)
        self.assertIn("if: github.ref == 'refs/heads/develop' && (github.event_name == 'push' || github.event_name == 'workflow_dispatch')", plan)

    def test_feature_push_does_not_create_a_pull_request_automatically(self):
        workflow = (ROOT / ".github/workflows/pr-automatico.yaml").read_text(encoding="utf-8")
        self.assertIn("branches: [main]", workflow)
        self.assertNotIn("branches-ignore:", workflow)


if __name__ == "__main__":
    unittest.main()
