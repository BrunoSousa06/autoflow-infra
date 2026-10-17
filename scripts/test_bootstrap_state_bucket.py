import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bootstrap_state_bucket import bootstrap


class BootstrapTests(unittest.TestCase):
    @patch("bootstrap_state_bucket.run")
    def test_existing_bucket_is_hardened_idempotently_without_state_overwrite(self, run):
        run.side_effect = [
            SimpleNamespace(stdout=""),
            SimpleNamespace(stdout='{"PublicAccessBlockConfiguration":{"BlockPublicAcls":true,"IgnorePublicAcls":true,"BlockPublicPolicy":true,"RestrictPublicBuckets":true}}'),
            SimpleNamespace(stdout='{"Status":"Enabled"}'),
            SimpleNamespace(stdout='{"SSEAlgorithm":"AES256"}'),
            SimpleNamespace(stdout=""),
        ]
        bootstrap("tfstate-example", "us-east-1", "123456789012", False)
        self.assertEqual(run.call_count, 5)
        self.assertFalse(any("put-" in item.args[0][1] for item in run.call_args_list))

    @patch("bootstrap_state_bucket.run")
    def test_missing_bucket_requires_approval_and_then_creates(self, run):
        run.side_effect = [subprocess.CalledProcessError(1, "aws", stderr="404 Not Found")]
        with self.assertRaisesRegex(RuntimeError, "aprovação"):
            bootstrap("tfstate-example", "us-east-1", "123456789012", False)
        run.reset_mock()
        run.side_effect = [subprocess.CalledProcessError(1, "aws", stderr="404 Not Found")] + [SimpleNamespace(stdout="") for _ in range(5)]
        bootstrap("tfstate-example", "us-east-1", "123456789012", True)
        self.assertEqual(run.call_args_list[1].args[1], "create-bucket")

    @patch("bootstrap_state_bucket.run", side_effect=subprocess.CalledProcessError(1, "aws", stderr="AccessDenied"))
    def test_aws_permission_failure_is_not_treated_as_absent(self, _run):
        with self.assertRaises(subprocess.CalledProcessError):
            bootstrap("tfstate-example", "us-east-1", "123456789012", True)


if __name__ == "__main__":
    unittest.main()
