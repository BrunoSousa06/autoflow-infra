from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PIPELINE = (ROOT / ".github/workflows/pipeline.yml").read_text(encoding="utf-8")
GATEWAY = (ROOT / ".github/workflows/api-gateway.yml").read_text(encoding="utf-8")


class TerraformStateRootContractTests(unittest.TestCase):
    def test_vpc_eks_gateway_and_newrelic_keys_are_environment_variables(self):
        self.assertIn("AWS_TF_STATE_KEY_INFRA", PIPELINE)
        self.assertIn("AWS_TF_STATE_KEY_GATEWAY", GATEWAY)
        self.assertIn("AWS_TF_STATE_KEY_NEWRELIC", GATEWAY)
        self.assertIn("AWS_TF_STATE_KEY_NEWRELIC", (ROOT / ".github/workflows/newrelic.yml").read_text(encoding="utf-8"))
        key_variable = (ROOT / "infra/api-gateway/variables.tf").read_text(encoding="utf-8").split('variable "infra_state_key"', 1)[1].split("}", 1)[0]
        self.assertNotIn("default", key_variable)

    def test_gateway_backend_pins_owner_and_remote_state_is_preflighted(self):
        gateway_data = (ROOT / "infra/api-gateway/main.tf").read_text(encoding="utf-8")
        self.assertNotIn("expected_bucket_owner", gateway_data)
        self.assertGreaterEqual(GATEWAY.count('expected_bucket_owner=$TF_VAR_expected_account_id'), 2)
        self.assertGreaterEqual(GATEWAY.count('aws s3api head-object --bucket "$TF_VAR_terraform_state_bucket" --key "$TF_VAR_infra_state_key" --expected-bucket-owner "$TF_VAR_expected_account_id"'), 2)
        self.assertIn('expected_bucket_owner=$AWS_EXPECTED_ACCOUNT_ID', PIPELINE)

    def test_gateway_state_key_is_required_and_has_no_legacy_default(self):
        variables = (ROOT / "infra/api-gateway/variables.tf").read_text(encoding="utf-8")
        key_variable = variables.split('variable "infra_state_key"', 1)[1].split("}", 1)[0]
        self.assertNotIn("default", key_variable)
        self.assertIn('"$TF_VAR_infra_state_key" == "$GITHUB_DEPLOYMENT_ENVIRONMENT/"*', GATEWAY)

    def test_production_plan_and_apply_require_protected_main(self):
        newrelic = (ROOT / ".github/workflows/newrelic.yml").read_text(encoding="utf-8")
        for workflow in (PIPELINE, GATEWAY, newrelic):
            plan = workflow.split("  plan:", 1)[1].split("\n  apply:", 1)[0]
            apply = workflow.split("\n  apply:", 1)[1]
            self.assertIn("github.ref != 'refs/heads/main' || github.ref_protected", plan)
            self.assertIn("github.ref != 'refs/heads/main' || github.ref_protected", apply)

    def test_gateway_apply_checks_run_commit_fingerprint_before_any_aws_operation(self):
        apply = GATEWAY.split("\n  apply:\n", 1)[1]
        verify = apply.index("terraform_deployment_fingerprint.py api-gateway verify")
        configure_aws = apply.index("aws-actions/configure-aws-credentials")
        terraform_init = apply.index("terraform init")
        self.assertLess(verify, configure_aws)
        self.assertLess(configure_aws, terraform_init)
        self.assertIn("github.run_attempt", apply)
        self.assertIn("github.sha", apply)

    def test_vpc_eks_apply_checks_fingerprint_before_any_aws_operation(self):
        apply = PIPELINE.split("\n  apply:\n", 1)[1]
        verify = apply.index("terraform_deployment_fingerprint.py vpc-eks verify")
        configure_aws = apply.index("aws-actions/configure-aws-credentials")
        terraform_init = apply.index("terraform init")
        self.assertLess(verify, configure_aws)
        self.assertLess(configure_aws, terraform_init)
        self.assertIn("infra-deployment-config.sha256", apply)


if __name__ == "__main__":
    unittest.main()
