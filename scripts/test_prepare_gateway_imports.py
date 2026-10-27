import subprocess
import unittest
from unittest.mock import patch

import prepare_gateway_imports as gateway_imports


class GatewayImportTests(unittest.TestCase):
    def test_imports_existing_vpc_link_and_attached_security_group_missing_from_state(self):
        links = [{
            "Name": "autoflow-homolog",
            "VpcLinkId": "a1b2c3d4",
            "SecurityGroupIds": ["sg-0123456789abcdef0"],
        }]
        self.assertEqual(
            gateway_imports.discover_imports(set(), links, "autoflow-homolog"),
            [
                (gateway_imports.VPC_LINK_ADDRESS, "a1b2c3d4"),
                (gateway_imports.VPC_LINK_SECURITY_GROUP_ADDRESS, "sg-0123456789abcdef0"),
            ],
        )

    def test_imports_only_security_group_when_vpc_link_is_already_in_state(self):
        links = [{
            "Name": "autoflow-homolog",
            "VpcLinkId": "a1b2c3d4",
            "SecurityGroupIds": ["sg-0123456789abcdef0"],
        }]
        self.assertEqual(
            gateway_imports.discover_imports({gateway_imports.VPC_LINK_ADDRESS}, links, "autoflow-homolog"),
            [(gateway_imports.VPC_LINK_SECURITY_GROUP_ADDRESS, "sg-0123456789abcdef0")],
        )

    def test_does_not_import_vpc_link_or_security_group_already_in_state(self):
        links = [{
            "Name": "autoflow-homolog",
            "VpcLinkId": "a1b2c3d4",
            "SecurityGroupIds": ["sg-0123456789abcdef0"],
        }]
        self.assertEqual(
            gateway_imports.discover_imports(
                {gateway_imports.VPC_LINK_ADDRESS, gateway_imports.VPC_LINK_SECURITY_GROUP_ADDRESS},
                links,
                "autoflow-homolog",
            ),
            [],
        )

    def test_no_matching_vpc_link_needs_no_import(self):
        self.assertEqual(gateway_imports.discover_imports(set(), [], "autoflow-homolog"), [])

    def test_ambiguous_or_invalid_vpc_links_fail_closed(self):
        for links in (
            [{"Name": "autoflow-homolog", "VpcLinkId": "vpclink1", "SecurityGroupIds": ["sg-0123456789abcdef0"]},
             {"Name": "autoflow-homolog", "VpcLinkId": "vpclink2", "SecurityGroupIds": ["sg-0123456789abcdef0"]}],
            [{"Name": "autoflow-homolog", "VpcLinkId": "not a valid id", "SecurityGroupIds": ["sg-0123456789abcdef0"]}],
            [{"Name": "autoflow-homolog", "VpcLinkId": "validid", "SecurityGroupIds": ["sg-0123456789abcdef0", "sg-abcdef01234567890"]}],
            [{"Name": "autoflow-homolog", "VpcLinkId": "validid", "SecurityGroupIds": ["not-a-security-group"]}],
        ):
            with self.subTest(links=links), self.assertRaises(RuntimeError):
                gateway_imports.discover_imports(set(), links, "autoflow-homolog")

    def test_renders_declarative_vpc_link_import(self):
        actual = gateway_imports.render_imports([
            (gateway_imports.VPC_LINK_ADDRESS, "a1b2c3d4"),
            (gateway_imports.VPC_LINK_SECURITY_GROUP_ADDRESS, "sg-0123456789abcdef0"),
        ])
        self.assertIn(f"to = {gateway_imports.VPC_LINK_ADDRESS}", actual)
        self.assertIn(f"to = {gateway_imports.VPC_LINK_SECURITY_GROUP_ADDRESS}", actual)
        self.assertIn('id = "a1b2c3d4"', actual)
        self.assertIn('id = "sg-0123456789abcdef0"', actual)

    def test_state_list_failure_with_missing_s3_object_means_empty_state(self):
        terraform_error = subprocess.CalledProcessError(1, "terraform state list", stderr="backend failed")
        s3_error = subprocess.CalledProcessError(1, "aws s3api head-object", stderr="NoSuchKey 404")
        with patch("prepare_gateway_imports.subprocess.run", side_effect=[terraform_error, s3_error]):
            self.assertEqual(gateway_imports.state_addresses("bucket", "api-gateway/state"), set())

    def test_state_list_permission_error_fails_when_s3_object_exists(self):
        terraform_error = subprocess.CalledProcessError(1, "terraform state list", stderr="backend failed")
        with patch("prepare_gateway_imports.subprocess.run", side_effect=[terraform_error, None]):
            with self.assertRaisesRegex(RuntimeError, "embora o objeto exista"):
                gateway_imports.state_addresses("bucket", "api-gateway/state")


if __name__ == "__main__":
    unittest.main()
