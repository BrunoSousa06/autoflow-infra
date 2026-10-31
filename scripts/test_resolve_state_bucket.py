import unittest

from resolve_state_bucket import resolve_state_bucket


class ResolveStateBucketTests(unittest.TestCase):
    def test_external_bucket_configuration_takes_precedence(self):
        self.assertEqual(
            resolve_state_bucket("approved-state-bucket", "123456789012", "us-east-1"),
            "approved-state-bucket",
        )

    def test_missing_bucket_is_derived_from_account_and_region(self):
        self.assertEqual(
            resolve_state_bucket(None, "123456789012", "us-east-1"),
            "autoflow-tfstate-learnerlab-123456789012-us-east-1",
        )
        self.assertEqual(
            resolve_state_bucket(None, "123456789012", "ap-southeast-2"),
            "autoflow-tfstate-learnerlab-123456789012-ap-southeast-2",
        )

    def test_invalid_account_or_region_blocks_derivation(self):
        for account, region in ((None, "us-east-1"), ("123", "us-east-1"), ("123456789012", None)):
            with self.subTest(account=account, region=region):
                with self.assertRaises(ValueError):
                    resolve_state_bucket(None, account, region)


if __name__ == "__main__":
    unittest.main()
