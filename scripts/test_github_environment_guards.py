from pathlib import Path
import re
import unittest

from validate_github_environment import ConfigurationError, validate_configuration


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"


def valid_values():
    return {
        "AWS_EXPECTED_ACCOUNT_ID": "123456789012",
        "AWS_REGION": "us-east-1",
        "AWS_TERRAFORM_STATE_BUCKET": "autoflow-state-example",
        "AWS_TF_STATE_KEY_INFRA": "homolog/infra.tfstate",
        "AWS_TF_STATE_KEY_NEWRELIC": "homolog/newrelic.tfstate",
        "AWS_TF_STATE_KEY_GATEWAY": "homolog/gateway.tfstate",
        "API_GATEWAY_CORS_ORIGINS": "[]",
        "TERRAFORM_APPLY_APPROVAL_CONFIGURED": "true",
        "AWS_ACCESS_KEY_ID": "example-access-key",
        "AWS_SECRET_ACCESS_KEY": "example-secret-key",
        "AWS_SESSION_TOKEN": "example-session-token",
        "TERRAFORM_PLAN_ENCRYPTION_PASSPHRASE": "example-passphrase",
        "NEW_RELIC_API_KEY": "example-newrelic-key",
        "NEW_RELIC_REGION": "US",
    }


class GitHubEnvironmentValidationTests(unittest.TestCase):
    def test_empty_required_variable_blocks_before_aws_access(self):
        values = valid_values()
        values["AWS_TERRAFORM_STATE_BUCKET"] = "  "

        with self.assertRaisesRegex(ConfigurationError, "AWS_TERRAFORM_STATE_BUCKET"):
            validate_configuration("homolog", values, (), (), require_approval_gate=True)

    def test_missing_required_secret_blocks_without_disclosing_values(self):
        values = valid_values()
        values["AWS_SESSION_TOKEN"] = ""

        with self.assertRaisesRegex(ConfigurationError, "Secret AWS_SESSION_TOKEN") as raised:
            validate_configuration("homolog", values, (), ("AWS_SESSION_TOKEN",))
        self.assertNotIn("example-secret-key", str(raised.exception))

    def test_invalid_account_and_region_are_rejected(self):
        for name, value in (("AWS_EXPECTED_ACCOUNT_ID", "123"), ("AWS_REGION", "not-a-region")):
            with self.subTest(name=name):
                values = valid_values()
                values[name] = value
                with self.assertRaises(ConfigurationError):
                    validate_configuration("homolog", values, (), ())

    def test_state_key_must_be_isolated_to_selected_environment(self):
        values = valid_values()
        values["AWS_TF_STATE_KEY_INFRA"] = "production/infra.tfstate"

        with self.assertRaisesRegex(ConfigurationError, "AWS_TF_STATE_KEY_INFRA"):
            validate_configuration("homolog", values, (), (), ("AWS_TF_STATE_KEY_INFRA",))

    def test_state_keys_must_be_unique(self):
        values = valid_values()
        values["AWS_TF_STATE_KEY_NEWRELIC"] = values["AWS_TF_STATE_KEY_INFRA"]

        with self.assertRaisesRegex(ConfigurationError, "exclusivas"):
            validate_configuration(
                "homolog", values, (), (), ("AWS_TF_STATE_KEY_INFRA", "AWS_TF_STATE_KEY_NEWRELIC")
            )

    def test_approval_marker_is_an_independent_required_gate(self):
        for marker in ("", "false", "TRUE"):
            with self.subTest(marker=marker):
                values = valid_values()
                values["TERRAFORM_APPLY_APPROVAL_CONFIGURED"] = marker
                with self.assertRaisesRegex(ConfigurationError, "TERRAFORM_APPLY_APPROVAL_CONFIGURED"):
                    validate_configuration(
                        "homolog", values, ("TERRAFORM_APPLY_APPROVAL_CONFIGURED",), (), require_approval_gate=True
                    )

    def test_environment_must_be_one_of_the_protected_environments(self):
        with self.assertRaisesRegex(ConfigurationError, "Environment"):
            validate_configuration("feature/foo", valid_values(), (), ())

    def test_workflows_do_not_query_administrative_environment_apis(self):
        for name in ("pipeline.yml", "newrelic.yml", "api-gateway.yml"):
            with self.subTest(workflow=name):
                content = (WORKFLOWS / name).read_text(encoding="utf-8")
                self.assertNotIn("/environments/", content)
                self.assertNotRegex(content, r"(?im)\b(?:gh\s+api|curl|wget)\b[^\n]*protection_rules")
                self.assertNotRegex(content, r"(?im)\b(?:VARIABLE_NAMES|SECRET_NAMES|REVIEWERS)=")
                self.assertNotIn("variables?per_page=", content)
                self.assertNotIn("secrets?per_page=", content)
                self.assertNotIn("protection_rules", content)

    def test_every_protected_job_uses_direct_context_values_and_closed_gate(self):
        jobs = {
            "pipeline.yml": {
                "bootstrap_state_bucket": (
                    ("AWS_EXPECTED_ACCOUNT_ID", "AWS_REGION", "AWS_TERRAFORM_STATE_BUCKET", "TERRAFORM_APPLY_APPROVAL_CONFIGURED"),
                    ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"),
                    (),
                ),
                "plan": (
                    ("AWS_EXPECTED_ACCOUNT_ID", "AWS_REGION", "AWS_TERRAFORM_STATE_BUCKET", "AWS_TF_STATE_KEY_INFRA", "TERRAFORM_APPLY_APPROVAL_CONFIGURED"),
                    ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "TERRAFORM_PLAN_ENCRYPTION_PASSPHRASE"),
                    ("AWS_TF_STATE_KEY_INFRA",),
                ),
                "apply": (
                    ("AWS_EXPECTED_ACCOUNT_ID", "AWS_REGION", "AWS_TERRAFORM_STATE_BUCKET", "AWS_TF_STATE_KEY_INFRA", "TERRAFORM_APPLY_APPROVAL_CONFIGURED"),
                    ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "TERRAFORM_PLAN_ENCRYPTION_PASSPHRASE"),
                    ("AWS_TF_STATE_KEY_INFRA",),
                ),
            },
            "newrelic.yml": {
                "plan": (
                    ("AWS_EXPECTED_ACCOUNT_ID", "AWS_REGION", "AWS_TERRAFORM_STATE_BUCKET", "AWS_TF_STATE_KEY_INFRA", "AWS_TF_STATE_KEY_NEWRELIC", "NEW_RELIC_REGION", "TERRAFORM_APPLY_APPROVAL_CONFIGURED"),
                    ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "TERRAFORM_PLAN_ENCRYPTION_PASSPHRASE", "NEW_RELIC_API_KEY"),
                    ("AWS_TF_STATE_KEY_INFRA", "AWS_TF_STATE_KEY_NEWRELIC"),
                ),
                "apply": (
                    ("AWS_EXPECTED_ACCOUNT_ID", "AWS_REGION", "AWS_TERRAFORM_STATE_BUCKET", "AWS_TF_STATE_KEY_INFRA", "AWS_TF_STATE_KEY_NEWRELIC", "NEW_RELIC_REGION", "TERRAFORM_APPLY_APPROVAL_CONFIGURED"),
                    ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "TERRAFORM_PLAN_ENCRYPTION_PASSPHRASE", "NEW_RELIC_API_KEY"),
                    ("AWS_TF_STATE_KEY_INFRA", "AWS_TF_STATE_KEY_NEWRELIC"),
                ),
            },
            "api-gateway.yml": {
                "plan": (
                    ("AWS_EXPECTED_ACCOUNT_ID", "AWS_REGION", "AWS_TERRAFORM_STATE_BUCKET", "AWS_TF_STATE_KEY_GATEWAY", "AWS_TF_STATE_KEY_INFRA", "AWS_TF_STATE_KEY_NEWRELIC", "API_GATEWAY_CORS_ORIGINS", "TERRAFORM_APPLY_APPROVAL_CONFIGURED"),
                    ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "TERRAFORM_PLAN_ENCRYPTION_PASSPHRASE"),
                    ("AWS_TF_STATE_KEY_GATEWAY", "AWS_TF_STATE_KEY_INFRA", "AWS_TF_STATE_KEY_NEWRELIC"),
                ),
                "apply": (
                    ("AWS_EXPECTED_ACCOUNT_ID", "AWS_REGION", "AWS_TERRAFORM_STATE_BUCKET", "AWS_TF_STATE_KEY_GATEWAY", "AWS_TF_STATE_KEY_INFRA", "AWS_TF_STATE_KEY_NEWRELIC", "API_GATEWAY_CORS_ORIGINS", "TERRAFORM_APPLY_APPROVAL_CONFIGURED"),
                    ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "TERRAFORM_PLAN_ENCRYPTION_PASSPHRASE"),
                    ("AWS_TF_STATE_KEY_GATEWAY", "AWS_TF_STATE_KEY_INFRA", "AWS_TF_STATE_KEY_NEWRELIC"),
                ),
            },
        }

        for workflow_name, workflow_jobs in jobs.items():
            content = (WORKFLOWS / workflow_name).read_text(encoding="utf-8")
            for job_name, (variables, secrets, state_keys) in workflow_jobs.items():
                with self.subTest(workflow=workflow_name, job=job_name):
                    job = self._job_section(content, job_name)
                    self.assertIn("environment: ${{ github.ref == 'refs/heads/main' && 'production' || 'homolog' }}", job)
                    for name in variables:
                        self.assertRegex(job, rf"(?m)^\s+{name}: \$\{{\{{ vars\.{name} \}}\}}$")
                    for name in secrets:
                        self.assertRegex(job, rf"(?m)^\s+{name}: \$\{{\{{ secrets\.{name} \}}\}}$")
                    self.assertIn("scripts/validate_github_environment.py", job)
                    self.assertEqual("--approval-gate" in job, job_name != "plan")
                    for name in state_keys:
                        self.assertIn(f"--state-key {name}", job)
                    self.assertIn("aws-actions/configure-aws-credentials@v4", job)
                    self.assertLess(job.index("scripts/validate_github_environment.py"), job.index("aws-actions/configure-aws-credentials@v4"))

    @staticmethod
    def _job_section(workflow: str, name: str) -> str:
        start = workflow.index(f"\n  {name}:\n")
        next_job = re.search(r"\n  [a-z_][a-z0-9_-]*:\n", workflow[start + 1 :])
        end = start + 1 + next_job.start() if next_job else len(workflow)
        return workflow[start:end]


if __name__ == "__main__":
    unittest.main()
