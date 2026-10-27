import unittest
import subprocess
from unittest.mock import patch

import prepare_eks_access_imports as imports


class AccessImportTests(unittest.TestCase):
    def discover(self, state, entry=True, association=True):
        with patch.object(imports, "access_entry_exists", return_value=entry), patch.object(
            imports, "run_json", return_value={"associatedAccessPolicies": ([{"policyArn": imports.POLICY_ARN}] if association else [])}
        ):
            return imports.discover_imports([], set(state), "cluster", "arn:role", "us-east-1")

    def test_a_imports_both_existing_resources_missing_from_state(self):
        self.assertEqual(len(self.discover(set())), 2)

    def test_b_creates_resources_when_neither_exists(self):
        self.assertEqual(self.discover(set(), entry=False, association=False), [])

    def test_c_does_not_import_resources_already_in_state(self):
        self.assertEqual(self.discover({imports.ENTRY_ADDRESS, imports.ASSOCIATION_ADDRESS}), [])

    def test_d_imports_entry_and_creates_missing_association(self):
        actual = self.discover(set(), association=False)
        self.assertEqual(actual, [(imports.ENTRY_ADDRESS, "cluster:arn:role")])

    def test_e_imports_only_resource_missing_from_state(self):
        actual = self.discover({imports.ENTRY_ADDRESS})
        self.assertEqual(actual, [(imports.ASSOCIATION_ADDRESS,
                                  f"cluster#arn:role#{imports.POLICY_ARN}")])

    def test_e_imports_entry_when_only_association_is_already_in_state(self):
        actual = self.discover({imports.ASSOCIATION_ADDRESS})
        self.assertEqual(actual, [(imports.ENTRY_ADDRESS, "cluster:arn:role")])

    def test_f_generated_configuration_has_no_historical_resource_identifiers(self):
        self.assertEqual(imports.render_imports(self.discover(set(), entry=False, association=False)), "")

    def test_existing_access_resources_require_explicit_reconciliation_approval(self):
        with self.assertRaisesRegex(RuntimeError, "reconciliação manual"):
            imports.require_approval(self.discover(set()), False)
        imports.require_approval(self.discover(set()), True)
        imports.require_approval([], False)

    def test_non_not_found_aws_error_fails_closed(self):
        with patch("subprocess.run", return_value=type("Result", (), {
            "returncode": 1, "stderr": "ExpiredTokenException"
        })()):
            with self.assertRaisesRegex(RuntimeError, "credenciais e permissões"):
                imports.access_entry_exists(["aws"], "cluster", "arn:role", "us-east-1")

    def test_missing_terraform_state_is_an_empty_address_set(self):
        error = __import__("subprocess").CalledProcessError(
            1, "terraform state list", stderr="No state file was found!"
        )
        with patch("prepare_eks_access_imports.subprocess.run", side_effect=error):
            self.assertEqual(imports.state_addresses(), set())

    def test_missing_state_is_detected_from_s3_when_terraform_error_differs(self):
        terraform_error = subprocess.CalledProcessError(1, "terraform state list", stderr="backend returned empty state")
        missing_object = subprocess.CalledProcessError(1, "aws s3api head-object", stderr="An error occurred (NoSuchKey) 404")
        with patch.dict("os.environ", {"TF_STATE_BUCKET": "state-bucket", "TF_STATE_KEY": "eks/state"}), \
                patch("prepare_eks_access_imports.subprocess.run", side_effect=[terraform_error, missing_object]):
            self.assertEqual(imports.state_addresses(), set())

    def test_s3_permission_failure_is_not_misclassified_as_missing_state(self):
        terraform_error = subprocess.CalledProcessError(1, "terraform state list", stderr="backend failed")
        access_error = subprocess.CalledProcessError(1, "aws s3api head-object", stderr="AccessDenied")
        with patch.dict("os.environ", {"TF_STATE_BUCKET": "state-bucket", "TF_STATE_KEY": "eks/state"}), \
                patch("prepare_eks_access_imports.subprocess.run", side_effect=[terraform_error, access_error]):
            with self.assertRaisesRegex(RuntimeError, "ausência do Terraform State no S3"):
                imports.state_addresses()

    def test_terraform_state_access_errors_still_fail_closed(self):
        error = __import__("subprocess").CalledProcessError(
            1, "terraform state list", stderr="AccessDenied: S3 operation forbidden"
        )
        with patch("prepare_eks_access_imports.subprocess.run", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, "acesso ao bucket de State"):
                imports.state_addresses()


if __name__ == "__main__":
    unittest.main()
