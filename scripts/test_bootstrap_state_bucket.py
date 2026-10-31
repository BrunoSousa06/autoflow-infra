import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import call, patch

from bootstrap_state_bucket import bootstrap


EXPECTED_OWNER = f"{0:012d}"
BUCKET = "tfstate-example"
REGION = "us-east-1"


def aws_result(stdout=""):
    return SimpleNamespace(stdout=stdout)


def existing_controls(public_block=True, versioning="Enabled", encryption="AES256"):
    return [
        aws_result(
            '{"PublicAccessBlockConfiguration":'
            '{"BlockPublicAcls":%s,"IgnorePublicAcls":%s,"BlockPublicPolicy":%s,"RestrictPublicBuckets":%s}}'
            % (str(public_block).lower(), str(public_block).lower(), str(public_block).lower(), str(public_block).lower())
        ),
        aws_result('{"Status":"%s"}' % versioning),
        aws_result(
            '{"ServerSideEncryptionConfiguration":{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"%s"}}]}}'
            % encryption
        ),
    ]


class BootstrapTests(unittest.TestCase):
    def identity(self, account=EXPECTED_OWNER):
        return aws_result(account)

    def head_bucket(self):
        return call(
            "s3api",
            "head-bucket",
            "--bucket",
            BUCKET,
            "--expected-bucket-owner",
            EXPECTED_OWNER,
            "--region",
            REGION,
        )

    @patch("bootstrap_state_bucket.run")
    def test_existing_compliant_bucket_is_idempotent_and_never_rewrites_state(self, run):
        run.side_effect = [
            self.identity(),
            aws_result(),
            *existing_controls(),
            aws_result(),
            self.identity(),
            aws_result(),
            *existing_controls(),
            aws_result(),
        ]

        bootstrap(BUCKET, REGION, EXPECTED_OWNER, False)
        bootstrap(BUCKET, REGION, EXPECTED_OWNER, False)

        self.assertEqual(run.call_count, 12)
        self.assertFalse(any("put-" in item.args for item in run.call_args_list))
        self.assertFalse(any("create-bucket" in item.args for item in run.call_args_list))
        self.assertEqual(run.call_args_list[1], self.head_bucket())

    @patch("bootstrap_state_bucket.run")
    def test_missing_bucket_requires_explicit_authorization(self, run):
        run.side_effect = [
            self.identity(),
            subprocess.CalledProcessError(1, "aws", stderr="An error occurred (404) when calling HeadBucket: Not Found"),
        ]

        with self.assertRaisesRegex(RuntimeError, "aprovação explícita"):
            bootstrap(BUCKET, REGION, EXPECTED_OWNER, False)

        self.assertEqual(run.call_count, 2)
        self.assertFalse(any("create-bucket" in item.args for item in run.call_args_list))
        self.assertFalse(any("put-" in item.args for item in run.call_args_list))

    @patch("bootstrap_state_bucket.run")
    def test_authorized_missing_bucket_is_created_and_all_controls_are_verified(self, run):
        run.side_effect = [
            self.identity(),
            subprocess.CalledProcessError(1, "aws", stderr="An error occurred (404) when calling HeadBucket: Not Found"),
            aws_result(),  # resposta create-bucket
            aws_result(),  # resposta put-public-access-block
            aws_result(),  # resposta put-bucket-versioning
            aws_result(),  # resposta put-bucket-encryption
            *existing_controls(),
            aws_result(),  # verificação final de propriedade
        ]

        bootstrap(BUCKET, REGION, EXPECTED_OWNER, True)

        self.assertEqual(run.call_args_list[2].args[:3], ("s3api", "create-bucket", "--bucket"))
        self.assertEqual(run.call_count, 10)
        for operation in ("put-public-access-block", "put-bucket-versioning", "put-bucket-encryption"):
            matching = [item for item in run.call_args_list if operation in item.args]
            self.assertEqual(len(matching), 1)
            self.assertIn(EXPECTED_OWNER, matching[0].args)

    @patch("bootstrap_state_bucket.run")
    def test_existing_incompatible_bucket_fails_without_modification(self, run):
        run.side_effect = [
            self.identity(),
            aws_result(),
            *existing_controls(public_block=False),
        ]

        with self.assertRaisesRegex(RuntimeError, "nenhuma configuração foi alterada"):
            bootstrap(BUCKET, REGION, EXPECTED_OWNER, True)

        self.assertEqual(run.call_count, 5)
        self.assertFalse(any("put-" in item.args for item in run.call_args_list))
        self.assertFalse(any("create-bucket" in item.args for item in run.call_args_list))

    @patch("bootstrap_state_bucket.run")
    def test_identity_mismatch_fails_before_any_s3_operation(self, run):
        run.return_value = self.identity(f"{1:012d}")

        with self.assertRaisesRegex(ValueError, "não corresponde à conta esperada"):
            bootstrap(BUCKET, REGION, EXPECTED_OWNER, True)

        run.assert_called_once_with("sts", "get-caller-identity", "--query", "Account", "--output", "text")

    @patch("bootstrap_state_bucket.run")
    def test_wrong_bucket_owner_fails_closed_without_create_or_put(self, run):
        run.side_effect = [
            self.identity(),
            subprocess.CalledProcessError(1, "aws", stderr="An error occurred (403) when calling HeadBucket: Forbidden"),
        ]

        with self.assertRaises(subprocess.CalledProcessError):
            bootstrap(BUCKET, REGION, EXPECTED_OWNER, True)

        self.assertEqual(run.call_args_list[1], self.head_bucket())
        self.assertFalse(any("create-bucket" in item.args for item in run.call_args_list))
        self.assertFalse(any("put-" in item.args for item in run.call_args_list))


if __name__ == "__main__":
    unittest.main()
