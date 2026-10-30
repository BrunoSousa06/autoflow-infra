import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = (
    ROOT / ".github/workflows/pipeline.yml",
    ROOT / ".github/workflows/newrelic.yml",
    ROOT / ".github/workflows/api-gateway.yml",
)


def remote_init_commands():
    commands = []
    for workflow in WORKFLOWS:
        text = workflow.read_text(encoding="utf-8")
        text = re.sub(r"\\\r?\n\s*", " ", text)
        for match in re.finditer(r"\bterraform(?:\s+-chdir=\S+)?\s+init\b([^\r\n]*)", text):
            command = match.group(0)
            if "-backend=false" not in command:
                commands.append((workflow.name, command))
    return commands


class TerraformBackendConfigTests(unittest.TestCase):
    def test_all_s3_backend_blocks_omit_unsupported_arguments(self):
        backend_files = []
        for terraform_file in (ROOT / "infra").rglob("*.tf"):
            text = terraform_file.read_text(encoding="utf-8")
            if re.search(r'backend\s+"s3"', text):
                backend_files.append(terraform_file)
                self.assertNotIn("expected_bucket_owner", text, str(terraform_file))
        self.assertEqual(len(backend_files), 3)

    def test_all_remote_init_commands_use_supported_s3_backend_arguments(self):
        commands = remote_init_commands()
        self.assertTrue(commands, "Nenhum terraform init remoto foi encontrado nos workflows.")
        for workflow, command in commands:
            with self.subTest(workflow=workflow, command=command):
                self.assertNotIn("expected_bucket_owner", command)
                self.assertIn('backend-config="allowed_account_ids=$TF_VAR_aws_allowed_account_ids"', command)
                self.assertIn('backend-config="encrypt=true"', command)
                self.assertIn('backend-config="use_lockfile=true"', command)
        for workflow in WORKFLOWS:
            self.assertIn(
                'TF_VAR_aws_allowed_account_ids: \'["${{ vars.AWS_EXPECTED_ACCOUNT_ID }}"]\'',
                workflow.read_text(encoding="utf-8"),
            )

    def test_remote_state_uses_the_externally_supplied_account_allowlist(self):
        remote_state = (ROOT / "infra/api-gateway/main.tf").read_text(encoding="utf-8")
        self.assertIn("allowed_account_ids = [var.expected_account_id]", remote_state)
        self.assertNotIn("expected_bucket_owner", remote_state)

    def test_both_environments_keep_distinct_external_state_keys(self):
        pipeline, newrelic, gateway = (path.read_text(encoding="utf-8") for path in WORKFLOWS)
        for workflow in (pipeline, newrelic, gateway):
            self.assertIn("github.ref == 'refs/heads/main' && 'production' || 'homolog'", workflow)
        self.assertIn("--state-key AWS_TF_STATE_KEY_INFRA", pipeline)
        self.assertIn("--state-key AWS_TF_STATE_KEY_NEWRELIC", newrelic)
        self.assertIn("--state-key AWS_TF_STATE_KEY_GATEWAY", gateway)
        self.assertIn('head-object --bucket "$TF_STATE_BUCKET" --key "$TF_STATE_KEY" --expected-bucket-owner "$AWS_EXPECTED_ACCOUNT_ID"', pipeline)
        self.assertIn("--expected-bucket-owner", (ROOT / "scripts/bootstrap_state_bucket.py").read_text(encoding="utf-8"))

    def test_real_s3_backend_init_validates_schema_and_is_confined_to_loopback(self):
        terraform = shutil.which("terraform")
        self.assertIsNotNone(terraform, "Terraform precisa estar disponível para testar o backend S3.")
        version = subprocess.run(
            [terraform, "version", "-json"], capture_output=True, text=True, check=True
        )
        self.assertEqual(json.loads(version.stdout)["terraform_version"], "1.16.5")

        with tempfile.TemporaryDirectory(prefix="autoflow-s3-backend-test-") as temporary:
            directory = Path(temporary)
            (directory / "main.tf").write_text('terraform {\n  backend "s3" {}\n}\n', encoding="utf-8")
            (directory / "credentials").write_text("", encoding="utf-8")
            (directory / "config").write_text("", encoding="utf-8")
            (directory / "terraform.tfrc").write_text("", encoding="utf-8")
            (directory / "backend.hcl").write_text(
                '\n'.join((
                    'bucket = "autoflow-backend-validation-only"',
                    'key = "validation/terraform.tfstate"',
                    'region = "us-east-1"',
                    f"allowed_account_ids = {json.dumps(['0' * 12])}",
                    'encrypt = true',
                    'use_lockfile = true',
                    'endpoint = "http://127.0.0.1:1"',
                    'skip_credentials_validation = true',
                    'skip_region_validation = true',
                    'skip_requesting_account_id = true',
                    'skip_metadata_api_check = true',
                )) + '\n',
                encoding="utf-8",
            )
            blocked_prefixes = ("AWS_", "TF_TOKEN_")
            blocked_names = {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "TF_CLI_CONFIG_FILE"}
            environment = {
                key: value for key, value in os.environ.items()
                if key.upper() not in blocked_names
                and not any(key.upper().startswith(prefix) for prefix in blocked_prefixes)
            }
            environment.update({
                "AWS_EC2_METADATA_DISABLED": "true",
                "AWS_SHARED_CREDENTIALS_FILE": str(directory / "credentials"),
                "AWS_CONFIG_FILE": str(directory / "config"),
                "AWS_REGION": "us-east-1",
                "TF_CLI_CONFIG_FILE": str(directory / "terraform.tfrc"),
            })
            result = subprocess.run(
                [
                    terraform,
                    "init",
                    "-input=false",
                    "-reconfigure",
                    "-backend-config=backend.hcl",
                ],
                cwd=directory,
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
            )

        output = (result.stdout + result.stderr).lower()
        self.assertNotEqual(result.returncode, 0, "O endpoint S3 local de teste deve impedir inicialização remota.")
        self.assertNotRegex(output, r"unsupported argument|unexpected argument|unexpected attribute|invalid backend configuration")
        self.assertTrue(
            any(marker in output for marker in ("127.0.0.1:1", "credential", "no valid credential", "no credential")),
            output,
        )


if __name__ == "__main__":
    unittest.main()
