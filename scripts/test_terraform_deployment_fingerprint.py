import unittest

from terraform_deployment_fingerprint import (
    FIELDS,
    FingerprintError,
    calculate_fingerprint,
    validate_fingerprint,
)


def values_for(root):
    return {name: f"configured-{name}" for name in FIELDS[root]}


class TerraformDeploymentFingerprintTests(unittest.TestCase):
    def test_fingerprint_is_stable_and_does_not_expose_configuration_values(self):
        values = values_for("vpc-eks")
        fingerprint = calculate_fingerprint("vpc-eks", values)
        self.assertEqual(fingerprint, calculate_fingerprint("vpc-eks", values.copy()))
        self.assertEqual(len(fingerprint), 64)
        self.assertNotIn("configured", fingerprint)

    def test_apply_rejects_environment_account_region_backend_and_identity_changes(self):
        for field in FIELDS["api-gateway"]:
            with self.subTest(field=field):
                planned = values_for("api-gateway")
                applied = planned.copy()
                applied[field] = "changed"
                with self.assertRaises(FingerprintError):
                    validate_fingerprint("api-gateway", applied, calculate_fingerprint("api-gateway", planned))

    def test_missing_required_backend_or_resource_configuration_fails_closed(self):
        values = values_for("vpc-eks")
        for field in ("AWS_EXPECTED_ACCOUNT_ID", "AWS_REGION", "TF_STATE_BUCKET", "TF_STATE_KEY", "EKS_CLUSTER_NAME"):
            with self.subTest(field=field):
                incomplete = values.copy()
                incomplete[field] = " "
                with self.assertRaises(FingerprintError):
                    calculate_fingerprint("vpc-eks", incomplete)

    def test_apply_rejects_missing_or_malformed_expected_fingerprint(self):
        values = values_for("api-gateway")
        for expected in ("", "invalid", "A" * 64):
            with self.subTest(expected=expected):
                with self.assertRaises(FingerprintError):
                    validate_fingerprint("api-gateway", values, expected)


if __name__ == "__main__":
    unittest.main()
