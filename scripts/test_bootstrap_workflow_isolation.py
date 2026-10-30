from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/pipeline.yml"


def job_section(workflow, name):
    start = workflow.index(f"\n  {name}:\n")
    next_job = re.search(r"\n  [a-z_][a-z0-9_-]*:\n", workflow[start + 1 :])
    end = start + 1 + next_job.start() if next_job else len(workflow)
    return workflow[start:end]


class BootstrapWorkflowIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.bootstrap = job_section(cls.workflow, "bootstrap_state_bucket")
        cls.validate = job_section(cls.workflow, "validate")
        cls.plan = job_section(cls.workflow, "plan")
        cls.apply = job_section(cls.workflow, "apply")

    def test_bootstrap_requires_dispatch_approval_and_supported_protected_branch(self):
        condition = self.bootstrap.split("    if: ", 1)[1].splitlines()[0]
        self.assertIn("github.event_name == 'workflow_dispatch'", condition)
        self.assertIn("inputs.approve_state_bucket_creation == true", condition)
        self.assertIn("github.ref == 'refs/heads/develop'", condition)
        self.assertIn("github.ref == 'refs/heads/main'", condition)
        self.assertIn("github.ref_protected", condition)
        self.assertNotIn("needs:", self.bootstrap)
        self.assertIn("default: false", self.workflow.split("approve_state_bucket_creation:", 1)[1].split("approve_eks_state_reconciliation:", 1)[0])

    def test_bootstrap_uses_only_selected_environment_configuration_and_secrets(self):
        self.assertIn("environment: ${{ github.ref == 'refs/heads/main' && 'production' || 'homolog' }}", self.bootstrap)
        for name in ("AWS_EXPECTED_ACCOUNT_ID", "AWS_REGION", "AWS_TERRAFORM_STATE_BUCKET"):
            self.assertIn(f"{name}: ${{{{ vars.{name} }}}}", self.bootstrap)
        for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
            self.assertIn(f"secrets.{name}", self.bootstrap)
        self.assertNotIn("APPROVE_CREATE", self.bootstrap)
        self.assertNotIn("resolve_state_bucket", self.bootstrap)

    def test_configuration_and_independent_approval_gate_are_checked_before_aws_credentials(self):
        guard_position = self.bootstrap.index("Validar configuração obrigatória do Environment")
        validator_position = self.bootstrap.index("scripts/validate_github_environment.py")
        credentials_position = self.bootstrap.index("aws-actions/configure-aws-credentials@v4")
        identity_position = self.bootstrap.index("python scripts/verify_aws_account.py")
        mutation_position = self.bootstrap.index("python scripts/bootstrap_state_bucket.py --approve-create")

        self.assertIn("--approval-gate", self.bootstrap)
        self.assertIn("--secret AWS_ACCESS_KEY_ID", self.bootstrap)
        self.assertLess(guard_position, validator_position)
        self.assertLess(validator_position, credentials_position)
        self.assertLess(credentials_position, identity_position)
        self.assertLess(identity_position, mutation_position)
        self.assertIn("environment: ${{ github.ref == 'refs/heads/main' && 'production' || 'homolog' }}", self.bootstrap)

    def test_authorized_bootstrap_dispatch_skips_validation_plan_and_apply(self):
        self.assertIn("inputs.approve_state_bucket_creation != true", self.validate)
        self.assertIn("inputs.approve_state_bucket_creation != true", self.plan)
        self.assertIn("inputs.approve_state_bucket_creation != true", self.apply)
        self.assertIn("needs: validate", self.plan)
        self.assertIn("needs: plan", self.apply)
        self.assertIn("terraform -chdir=infra init -backend=false", self.validate)
        self.assertNotIn("needs:", self.bootstrap)
        self.assertNotIn("needs: bootstrap_state_bucket", self.workflow)
        self.assertNotIn("hashicorp/setup-terraform", self.bootstrap)
        self.assertNotIn("terraform init", self.bootstrap.lower())
        self.assertNotIn("terraform plan", self.bootstrap.lower())
        self.assertNotIn("terraform apply", self.bootstrap.lower())

    def test_bootstrap_dispatch_has_no_cross_workflow_fanout(self):
        workflow_dir = ROOT / ".github/workflows"
        for path in (*workflow_dir.glob("*.yml"), *workflow_dir.glob("*.yaml")):
            if path.name == "pipeline.yml":
                continue
            content = path.read_text(encoding="utf-8")
            self.assertNotRegex(content, r"(?m)^\s{2}workflow_run:", path.name)
            self.assertNotRegex(content, r"(?m)^\s{2}workflow_call:", path.name)

    def test_plan_only_checks_backend_bucket_without_creation_authorization(self):
        bucket_check = self.plan.split("Verificar existência e conformidade do bucket de Terraform State", 1)[1].split("      - name:", 1)[0]
        self.assertIn("python scripts/bootstrap_state_bucket.py", bucket_check)
        self.assertNotIn("--approve-create", bucket_check)
        self.assertNotIn("APPROVE_CREATE", self.plan)
        self.assertNotIn("Verificar/bootstrap seguro do bucket", self.plan)


if __name__ == "__main__":
    unittest.main()
