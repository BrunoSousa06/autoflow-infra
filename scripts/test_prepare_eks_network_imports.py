import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import prepare_eks_network_imports as imports


ACCOUNT = "123456789012"
VPC_ID = "vpc-0123456789abcdef0"
RT_ID = "rtb-0123456789abcdef0"
SUBNETS = (
    (0, "10.0.64.0/20", "us-east-1a", "subnet-00000000000000001", "rtbassoc-00000000000000001"),
    (1, "10.0.80.0/20", "us-east-1b", "subnet-00000000000000002", "rtbassoc-00000000000000002"),
    (2, "10.0.96.0/20", "us-east-1c", "subnet-00000000000000003", "rtbassoc-00000000000000003"),
)


def vpc(project_name="autoflow"):
    name = "main-vpc" if project_name == "autoflow" else f"main-vpc-{project_name}"
    return {"VpcId": VPC_ID, "OwnerId": ACCOUNT, "CidrBlock": "10.0.0.0/16",
            "Tags": [{"Key": "Name", "Value": name}]}


def subnets(project_name="autoflow"):
    result = []
    for _, cidr, zone, subnet_id, _ in SUBNETS:
        result.append({
            "SubnetId": subnet_id,
            "VpcId": VPC_ID,
            "OwnerId": ACCOUNT,
            "CidrBlock": cidr,
            "AvailabilityZone": zone,
            "MapPublicIpOnLaunch": False,
            "Tags": [
                {"Key": "Name", "Value": "private-subnet"},
                {"Key": "kubernetes.io/role/internal-elb", "Value": "1"},
                {"Key": f"kubernetes.io/cluster/eks-{project_name}", "Value": "shared"},
            ],
        })
    return result


def route_tables(association_table_id=RT_ID, project_name="autoflow"):
    associations = []
    for _, _, _, subnet_id, association_id in SUBNETS:
        associations.append({
            "RouteTableAssociationId": association_id,
            "RouteTableId": association_table_id,
            "SubnetId": subnet_id,
            "Main": False,
        })
    return [{
        "RouteTableId": RT_ID,
        "VpcId": VPC_ID,
        "OwnerId": ACCOUNT,
        "Tags": [{"Key": "Name", "Value": f"{project_name}-private-rt"}],
        "Associations": associations,
    }]


class NetworkImportTests(unittest.TestCase):
    def setUp(self):
        self.commands = []
        self.nodegroups = ["nodeg-autoflow"]
        self.responses = {
            "describe-vpcs": {"Vpcs": [vpc()]},
            "describe-vpc-attribute": {"EnableDnsSupport": {"Value": True},
                                       "EnableDnsHostnames": {"Value": True}},
            "describe-subnets": {"Subnets": subnets()},
            "describe-route-tables": {"RouteTables": route_tables()},
            "describe-internet-gateways": {"InternetGateways": []},
            "describe-addresses": {"Addresses": []},
            "describe-nat-gateways": {"NatGateways": []},
            "describe-security-groups": {"SecurityGroups": []},
        }

    def run_json(self, command, run=None):
        self.commands.append(command)
        if "list-nodegroups" in command:
            return {"nodegroups": self.nodegroups}
        operation = next(part for part in command if part.startswith("describe-"))
        return self.responses[operation]

    def discover(self, addresses=set(), state_ids=None, project_name="autoflow", cluster_present=False):
        with patch.object(imports, "run_json", side_effect=self.run_json), patch.object(
            imports, "cluster_exists", return_value=cluster_present
        ):
            return imports.discover_imports(
                ACCOUNT, "us-east-1", set(addresses), state_ids or {}, project_name=project_name
            )

    def test_discovers_only_the_eight_matching_resources(self):
        found = self.discover()
        self.assertEqual(found, [
            ("aws_vpc.autoflow_vpc", VPC_ID),
            ("aws_subnet.subnet_private[0]", SUBNETS[0][3]),
            ("aws_subnet.subnet_private[1]", SUBNETS[1][3]),
            ("aws_subnet.subnet_private[2]", SUBNETS[2][3]),
            ("aws_route_table.route_table_private", RT_ID),
            ("aws_route_table_association.private_association[0]", f"{SUBNETS[0][3]}/{RT_ID}"),
            ("aws_route_table_association.private_association[1]", f"{SUBNETS[1][3]}/{RT_ID}"),
            ("aws_route_table_association.private_association[2]", f"{SUBNETS[2][3]}/{RT_ID}"),
        ])

    def test_existing_matching_state_addresses_are_not_imported_again(self):
        addresses = {address for address, _ in self.discover()}
        state_ids = {
            "aws_vpc.autoflow_vpc": VPC_ID,
            "aws_subnet.subnet_private[0]": SUBNETS[0][3],
            "aws_subnet.subnet_private[1]": SUBNETS[1][3],
            "aws_subnet.subnet_private[2]": SUBNETS[2][3],
            "aws_route_table.route_table_private": RT_ID,
            "aws_route_table_association.private_association[0]": SUBNETS[0][4],
            "aws_route_table_association.private_association[1]": SUBNETS[1][4],
            "aws_route_table_association.private_association[2]": SUBNETS[2][4],
        }
        self.assertEqual(self.discover(addresses, state_ids), [])

    def test_state_id_collision_blocks_reconciliation(self):
        with self.assertRaisesRegex(imports.NetworkImportError, "já contém um recurso diferente"):
            self.discover({"aws_vpc.autoflow_vpc"}, {"aws_vpc.autoflow_vpc": "vpc-other"})

    def test_ambiguous_vpc_blocks_reconciliation(self):
        self.responses["describe-vpcs"]["Vpcs"].append(vpc())
        with self.assertRaisesRegex(imports.NetworkImportError, "Mais de uma VPC candidata"):
            self.discover()

    def test_foreign_vpc_blocks_reconciliation(self):
        self.responses["describe-vpcs"]["Vpcs"][0]["OwnerId"] = "999999999999"
        with self.assertRaisesRegex(imports.NetworkImportError, "owner/CIDR/tag"):
            self.discover()

    def test_subnet_tag_or_configuration_mismatch_blocks_reconciliation(self):
        self.responses["describe-subnets"]["Subnets"][0]["MapPublicIpOnLaunch"] = True
        with self.assertRaisesRegex(imports.NetworkImportError, "não corresponde integralmente"):
            self.discover()

    def test_association_to_another_route_table_blocks_reconciliation(self):
        other = {
            "RouteTableId": "rtb-other",
            "VpcId": VPC_ID,
            "OwnerId": ACCOUNT,
            "Tags": [{"Key": "Name", "Value": "other-table"}],
            "Associations": [{"RouteTableId": "rtb-other", "SubnetId": SUBNETS[0][3], "Main": False}],
        }
        self.responses["describe-route-tables"]["RouteTables"] = route_tables() + [other]
        with self.assertRaisesRegex(imports.NetworkImportError, "outra route table"):
            self.discover()

    def test_missing_vpc_allows_normal_empty_rebuild(self):
        self.responses["describe-vpcs"]["Vpcs"] = []
        self.assertEqual(self.discover(), [])

    def test_production_discovery_uses_environment_specific_tags_and_eks_names(self):
        project_name = "autoflow-production"
        self.responses["describe-vpcs"]["Vpcs"] = [vpc(project_name)]
        self.responses["describe-subnets"]["Subnets"] = subnets(project_name)
        self.responses["describe-route-tables"]["RouteTables"] = route_tables(project_name=project_name)
        self.nodegroups = ["nodeg-autoflow-production"]
        addresses = {"aws_eks_cluster.autoflow", "aws_eks_node_group.node_group"}
        state_ids = {
            "aws_eks_cluster.autoflow": "eks-autoflow-production",
            "aws_eks_node_group.node_group": "eks-autoflow-production:nodeg-autoflow-production",
        }

        self.discover(addresses, state_ids, project_name, cluster_present=True)

        self.assertIn("Name=tag:Name,Values=main-vpc-autoflow-production", self.commands[0])
        self.assertTrue(any("Name=tag:Name,Values=autoflow-production-nat-eip" in command for command in self.commands))
        self.assertEqual(
            ["aws", "eks", "list-nodegroups", "--cluster-name", "eks-autoflow-production", "--region", "us-east-1"],
            next(command for command in self.commands if "list-nodegroups" in command),
        )

    def test_public_subnet_survivor_outside_supported_import_set_blocks_plan(self):
        public = {
            "SubnetId": "subnet-public",
            "VpcId": VPC_ID,
            "OwnerId": ACCOUNT,
            "CidrBlock": "10.0.0.0/20",
            "AvailabilityZone": "us-east-1a",
            "MapPublicIpOnLaunch": True,
            "Tags": [
                {"Key": "Name", "Value": "public-subnet"},
                {"Key": "kubernetes.io/role/elb", "Value": "1"},
                {"Key": "kubernetes.io/cluster/eks-autoflow", "Value": "shared"},
            ],
        }
        self.responses["describe-subnets"]["Subnets"].append(public)
        with self.assertRaisesRegex(imports.NetworkImportError, "fora do conjunto de imports automáticos"):
            self.discover()

    def test_igw_survivor_outside_state_blocks_plan(self):
        self.responses["describe-internet-gateways"]["InternetGateways"] = [{
            "InternetGatewayId": "igw-0123456789abcdef0",
            "OwnerId": ACCOUNT,
            "Attachments": [{"VpcId": VPC_ID, "State": "available"}],
        }]
        with self.assertRaisesRegex(imports.NetworkImportError, "fora do conjunto de imports automáticos"):
            self.discover()

    def test_existing_cluster_without_state_is_not_recreated(self):
        with patch.object(imports, "run_json", side_effect=self.run_json), patch.object(
            imports, "cluster_exists", return_value=True
        ):
            with self.assertRaisesRegex(imports.NetworkImportError, "Cluster EKS existente não está no State"):
                imports.discover_imports(ACCOUNT, "us-east-1", set(), {})

    def test_imports_require_explicit_approval(self):
        with self.assertRaisesRegex(imports.NetworkImportError, "approve_eks_state_reconciliation=true"):
            imports.require_approval([("aws_vpc.autoflow_vpc", VPC_ID)], False)
        imports.require_approval([("aws_vpc.autoflow_vpc", VPC_ID)], True)
        imports.require_approval([], False)

    def test_access_denied_inventory_query_blocks_reconciliation(self):
        def deny(*args, **kwargs):
            raise subprocess.CalledProcessError(1, args[0], stderr="AccessDenied")

        with self.assertRaisesRegex(imports.NetworkImportError, "inconclusiva"):
            imports.run_json(["aws", "ec2", "describe-vpcs"], deny)

    def test_rendered_import_addresses_keep_count_indices(self):
        text = imports.render_imports([
            ("aws_subnet.subnet_private[1]", SUBNETS[1][3]),
            ("aws_route_table_association.private_association[2]", f"{SUBNETS[2][3]}/{RT_ID}"),
        ])
        self.assertIn("to = aws_subnet.subnet_private[1]", text)
        self.assertIn(f'id = "{SUBNETS[2][3]}/{RT_ID}"', text)

    def test_state_id_parser_does_not_emit_state_values(self):
        run = lambda *args, **kwargs: SimpleNamespace(stdout='id = "vpc-0123456789abcdef0"\n')
        self.assertEqual(
            imports.state_resource_ids({"aws_vpc.autoflow_vpc"}, run),
            {"aws_vpc.autoflow_vpc": VPC_ID},
        )


if __name__ == "__main__":
    unittest.main()
