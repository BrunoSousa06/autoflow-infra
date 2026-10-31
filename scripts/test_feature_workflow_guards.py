from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class FeatureWorkflowGuardTests(unittest.TestCase):
    def test_state_bucket_bootstrap_is_a_dedicated_approved_job(self):
        workflow = (ROOT / ".github/workflows/pipeline.yml").read_text(encoding="utf-8")
        bootstrap = workflow.split("  bootstrap_state_bucket:", 1)[1].split("\n  plan:", 1)[0]
        plan = workflow.split("  plan:", 1)[1].split("\n  apply:", 1)[0]

        self.assertIn("github.event_name == 'workflow_dispatch'", bootstrap)
        self.assertIn("inputs.approve_state_bucket_creation == true", bootstrap)
        self.assertIn("github.ref == 'refs/heads/develop'", bootstrap)
        self.assertIn("github.ref == 'refs/heads/main'", bootstrap)
        self.assertNotIn("needs:", bootstrap)
        self.assertNotIn("--approve-create", plan)
        self.assertIn("inputs.approve_state_bucket_creation != true", plan)

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

        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("branches: [develop, main, 'feature/**']", ci)
        self.assertIn("on:\n  workflow_dispatch:", workflow)
        self.assertNotIn("  push:", workflow.split("permissions:", 1)[0])
        self.assertNotIn("  pull_request:", workflow.split("permissions:", 1)[0])
        self.assertNotIn("refs/heads/feature/", plan)
        self.assertIn("needs: validate", plan)
        self.assertIn("environment: ${{ github.ref == 'refs/heads/main' && 'production' || 'homolog' }}", plan)
        self.assertIn("TF_VAR_project_name: ${{ github.ref == 'refs/heads/main' && 'autoflow-production' || 'autoflow' }}", plan)
        self.assertIn("EKS_CLUSTER_NAME: eks-${{ github.ref == 'refs/heads/main' && 'autoflow-production' || 'autoflow' }}", plan)
        self.assertIn("EKS_LEASE_KEY: ci/${{ github.ref == 'refs/heads/main' && 'production' || 'homolog' }}/eks-endpoint-lease.json", plan)
        self.assertNotIn("NEWRELIC_DEACTIVATION_APPROVED", plan)
        self.assertIn("(github.ref == 'refs/heads/develop' || github.ref == 'refs/heads/main') && github.event_name == 'workflow_dispatch' && inputs.apply == true && inputs.approve_state_bucket_creation != true", apply)
        self.assertNotIn("refs/heads/feature/", apply)
        self.assertIn("needs: plan", apply)
        self.assertIn("github.event_name == 'workflow_dispatch' && inputs.allow_destructive", plan)
        self.assertIn("github.event_name == 'workflow_dispatch' && inputs.allow_destructive", apply)
        self.assertNotIn("github.event_name == 'push' && 'true'", plan)
        self.assertNotIn("github.event_name == 'push' && 'true'", apply)
        self.assertIn("--approval-gate", apply)
        self.assertIn("TERRAFORM_APPLY_APPROVAL_CONFIGURED: ${{ vars.TERRAFORM_APPLY_APPROVAL_CONFIGURED }}", apply)
        self.assertLess(plan.index("Validar configuração obrigatória antes do acesso AWS"), plan.index("aws-actions/configure-aws-credentials@v4"))
        self.assertNotIn("--approval-gate", plan)
        self.assertLess(apply.index("Validar configuração obrigatória antes do Apply"), apply.index("aws-actions/configure-aws-credentials@v4"))
        self.assertIn("vars.AWS_EXPECTED_ACCOUNT_ID", plan)
        self.assertIn("--state-key AWS_TF_STATE_KEY_INFRA", plan)
        self.assertIn("github.ref == 'refs/heads/develop' || github.ref == 'refs/heads/main'", plan)
        self.assertIn("rm -f infra.tfplan infra-plan.json", plan)
        self.assertIn("if: success() && (github.ref == 'refs/heads/develop' || github.ref == 'refs/heads/main')", plan)

    def test_gateway_feature_branches_run_validation_without_plan_or_apply(self):
        workflow = (ROOT / ".github/workflows/api-gateway.yml").read_text(encoding="utf-8")
        plan = workflow.split("  plan:", 1)[1].split("  apply:", 1)[0]
        apply = workflow.split("\n  apply:\n", 1)[1]

        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("branches: [develop, main, 'feature/**']", ci)
        self.assertIn("on:\n  workflow_dispatch:", workflow)
        self.assertNotIn("refs/heads/feature/", plan)
        self.assertIn("needs: validate", plan)
        self.assertIn("environment: ${{ github.ref == 'refs/heads/main' && 'production' || 'homolog' }}", plan)
        self.assertNotIn("Exigir Required reviewers no environment para feature Plan", plan)
        self.assertIn("(github.ref == 'refs/heads/develop' || github.ref == 'refs/heads/main') && github.event_name == 'workflow_dispatch' && inputs.apply == true", apply)
        self.assertNotIn("refs/heads/feature/", apply)
        self.assertIn("(github.ref == 'refs/heads/develop' || github.ref == 'refs/heads/main') && github.event_name == 'workflow_dispatch'", plan)
        self.assertIn("--approval-gate", apply)
        self.assertIn("environment: ${{ github.ref == 'refs/heads/main' && 'production' || 'homolog' }}", apply)
        self.assertIn("--state-key AWS_TF_STATE_KEY_GATEWAY", plan)

    def test_newrelic_pr_and_feature_events_validate_without_plan_or_apply(self):
        workflow = (ROOT / ".github/workflows/newrelic.yml").read_text(encoding="utf-8")
        plan = workflow.split("  plan:", 1)[1].split("  apply:", 1)[0]
        apply = workflow.split("\n  apply:\n", 1)[1]

        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("pull_request:", ci)
        self.assertIn("branches: [develop, main, 'feature/**']", ci)
        self.assertIn("(github.ref == 'refs/heads/develop' || github.ref == 'refs/heads/main') && github.event_name == 'workflow_dispatch'", plan)
        self.assertNotIn("refs/heads/feature/", plan)
        self.assertNotIn("github.event_name == 'pull_request'", plan)
        self.assertNotIn("refs/heads/feature/", apply)
        self.assertNotIn("github.event_name == 'pull_request'", apply)

    def test_feature_push_does_not_create_a_pull_request_automatically(self):
        workflow = (ROOT / ".github/workflows/pr-automatico.yaml").read_text(encoding="utf-8")
        self.assertIn("branches: [main]", workflow)
        self.assertNotIn("branches-ignore:", workflow)


if __name__ == "__main__":
    unittest.main()
