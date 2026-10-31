from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def section(content: str, job: str, next_job: str | None = None) -> str:
    start = content.index(f"\n  {job}:\n") + 1
    end = content.index(f"\n  {next_job}:\n", start) if next_job else len(content)
    return content[start:end]


class CiCdWorkflowMatrixTests(unittest.TestCase):
    def test_ci_triggers_are_automatic_and_do_not_run_deployment_operations(self):
        ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
        triggers = ci.split("permissions:", 1)[0]
        self.assertIn("branches: [develop, main, 'feature/**']", triggers)
        self.assertIn("branches: [develop, main]", triggers)
        self.assertNotIn("workflow_dispatch:", triggers)
        self.assertNotRegex(ci, r"(?im)^\s*run:.*\bterraform\s+(?:plan|apply|destroy)\b")
        self.assertNotIn("aws-actions/configure-aws-credentials", ci)
        self.assertNotIn("docker/build-push-action", ci)
        self.assertNotIn("kubectl rollout", ci)

    def test_each_infrastructure_component_has_dispatch_only_cd_and_guarded_apply(self):
        for filename in ("pipeline.yml", "api-gateway.yml", "newrelic.yml"):
            with self.subTest(workflow=filename):
                content = (WORKFLOWS / filename).read_text(encoding="utf-8")
                triggers = content.split("permissions:", 1)[0]
                plan = section(content, "plan", "apply")
                apply = section(content, "apply")
                self.assertIn("on:\n  workflow_dispatch:", triggers)
                self.assertNotIn("  push:", triggers)
                self.assertNotIn("  pull_request:", triggers)
                self.assertIn("github.event_name == 'workflow_dispatch'", plan)
                self.assertIn("refs/heads/develop", plan)
                self.assertIn("refs/heads/main", plan)
                self.assertIn("github.ref_protected", plan)
                self.assertIn("github.event_name == 'workflow_dispatch'", apply)
                self.assertIn("inputs.apply == true", apply)
                self.assertIn("needs: plan", apply)
                self.assertIn("TERRAFORM_APPLY_APPROVAL_CONFIGURED", apply)
                self.assertIn("--approval-gate", apply)
                self.assertIn("environment: ${{ github.ref == 'refs/heads/main' && 'production' || 'homolog' }}", plan)
                self.assertIn("environment: ${{ github.ref == 'refs/heads/main' && 'production' || 'homolog' }}", apply)
                self.assertIn("terraform apply -input=false", apply)
                self.assertNotIn("github.event_name == 'push'", plan + apply)

    def test_plan_approval_does_not_depend_on_the_apply_flag(self):
        for filename in ("pipeline.yml", "api-gateway.yml", "newrelic.yml"):
            with self.subTest(workflow=filename):
                content = (WORKFLOWS / filename).read_text(encoding="utf-8")
                plan = section(content, "plan", "apply")
                self.assertNotIn("--approval-gate", plan)
                self.assertIn("environment: ${{ github.ref == 'refs/heads/main' && 'production' || 'homolog' }}", plan)

    def test_bootstrap_remains_isolated_from_plan_and_requires_explicit_gates(self):
        content = (WORKFLOWS / "pipeline.yml").read_text(encoding="utf-8")
        bootstrap = section(content, "bootstrap_state_bucket", "plan")
        plan = section(content, "plan", "apply")
        self.assertIn("inputs.approve_state_bucket_creation == true", bootstrap)
        self.assertIn("--approve-create", bootstrap)
        self.assertIn("--approval-gate", bootstrap)
        self.assertNotIn("needs:", bootstrap)
        self.assertIn("inputs.approve_state_bucket_creation != true", plan)
        self.assertNotIn("--approve-create", plan)

    def test_every_plan_artifact_uploaded_by_cd_is_encrypted(self):
        expected = {
            "pipeline.yml": "infra.tfplan.gpg",
            "api-gateway.yml": "gateway.tfplan.gpg",
            "newrelic.yml": "newrelic.tfplan.gpg",
        }
        for filename, encrypted_file in expected.items():
            with self.subTest(workflow=filename):
                content = (WORKFLOWS / filename).read_text(encoding="utf-8")
                self.assertIn(encrypted_file, content)
                self.assertRegex(content, rf"(?m)^\s+retention-days: 1$")


if __name__ == "__main__":
    unittest.main()
