from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class FeatureWorkflowGuardTests(unittest.TestCase):
    def test_eks_feature_branches_can_plan_but_never_apply(self):
        workflow = (ROOT / ".github/workflows/pipeline.yml").read_text(encoding="utf-8")
        plan = workflow.split("  plan:", 1)[1].split("  apply:", 1)[0]
        apply = workflow.split("\n  apply:\n", 1)[1]

        self.assertIn("branches: [develop, main, 'feature/**']", workflow)
        self.assertIn("startsWith(github.ref, 'refs/heads/feature/')", plan)
        self.assertIn("needs: validate", plan)
        self.assertIn("environment: ${{ github.ref == 'refs/heads/main' && 'production' || 'homolog' }}", plan)
        self.assertIn("Exigir Required reviewers no environment para feature Plan", plan)
        self.assertIn('test "$REVIEWERS" -gt 0', plan)
        self.assertLess(plan.index("Exigir Required reviewers no environment para feature Plan"), plan.index("- uses: actions/checkout@v4"))
        self.assertIn("NEWRELIC_DEACTIVATION_APPROVED: ${{ (github.ref == 'refs/heads/develop' || github.ref == 'refs/heads/main')", plan)
        self.assertIn("((github.ref == 'refs/heads/develop' && github.event_name == 'push') || ((github.ref == 'refs/heads/develop' || github.ref == 'refs/heads/main') && github.event_name == 'workflow_dispatch' && inputs.apply))", apply)
        self.assertNotIn("refs/heads/feature/", apply)
        self.assertIn("needs: plan", apply)
        self.assertIn("github.ref == 'refs/heads/develop' || github.ref == 'refs/heads/main'", plan)
        self.assertIn("rm -f infra.tfplan infra-plan.json", plan)
        self.assertIn("if: success() && (github.ref == 'refs/heads/develop' || github.ref == 'refs/heads/main')", plan)

    def test_gateway_feature_branches_can_plan_but_never_apply(self):
        workflow = (ROOT / ".github/workflows/api-gateway.yml").read_text(encoding="utf-8")
        plan = workflow.split("  plan:", 1)[1].split("  apply:", 1)[0]
        apply = workflow.split("\n  apply:\n", 1)[1]

        self.assertIn("branches: [develop, main, 'feature/**']", workflow)
        self.assertIn("startsWith(github.ref, 'refs/heads/feature/')", plan)
        self.assertIn("needs: validate", plan)
        self.assertIn("environment: homolog", plan)
        self.assertIn("Exigir Required reviewers no environment para feature Plan", plan)
        self.assertIn('test "$REVIEWERS" -gt 0', plan)
        self.assertLess(plan.index("Exigir Required reviewers no environment para feature Plan"), plan.index("- uses: actions/checkout@v4"))
        self.assertIn("github.ref == 'refs/heads/develop' && (github.event_name == 'push' || github.event_name == 'workflow_dispatch')", apply)
        self.assertNotIn("refs/heads/feature/", apply)
        self.assertIn("if: github.ref == 'refs/heads/develop'", plan)

    def test_feature_push_does_not_create_a_pull_request_automatically(self):
        workflow = (ROOT / ".github/workflows/pr-automatico.yaml").read_text(encoding="utf-8")
        self.assertIn("branches: [main]", workflow)
        self.assertNotIn("branches-ignore:", workflow)


if __name__ == "__main__":
    unittest.main()
