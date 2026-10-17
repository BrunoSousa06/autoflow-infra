import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from state_resource_guard import check


class StateResourceGuardTests(unittest.TestCase):
    @patch("state_resource_guard.subprocess.run")
    def test_empty_environment_allows_absent_state_and_resource(self, run):
        run.side_effect = [subprocess.CalledProcessError(1, "aws", stderr="NoSuchKey 404"),
                           subprocess.CalledProcessError(1, "aws", stderr="ResourceNotFoundException")]
        self.assertEqual(check("bucket", "eks/state", ["aws", "eks", "describe-cluster"]), "state-and-resource-absent")

    @patch("state_resource_guard.subprocess.run")
    def test_existing_state_allows_normal_deployment_without_probe(self, run):
        run.return_value = SimpleNamespace(stdout="{}")
        self.assertEqual(check("bucket", "eks/state", ["aws", "eks", "describe-cluster"]), "state-present")
        self.assertEqual(run.call_count, 1)

    @patch("state_resource_guard.subprocess.run")
    def test_partial_reset_blocks_existing_resource_without_state(self, run):
        run.side_effect = [subprocess.CalledProcessError(1, "aws", stderr="NoSuchKey 404"), SimpleNamespace(stdout='{"status":"ACTIVE"}')]
        with self.assertRaisesRegex(RuntimeError, "State eks/state ausente, mas o recurso consultado já existe"):
            check("bucket", "eks/state", ["aws", "eks", "describe-cluster"])

    @patch("state_resource_guard.subprocess.run", side_effect=subprocess.CalledProcessError(1, "aws", stderr="AccessDenied"))
    def test_aws_permission_failure_is_not_misclassified_as_absence(self, _run):
        with self.assertRaisesRegex(RuntimeError, "classificar o Terraform State"):
            check("bucket", "eks/state", ["aws", "eks", "describe-cluster"])


if __name__ == "__main__":
    unittest.main()
