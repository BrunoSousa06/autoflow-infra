import json
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from discover_operator_access_role import (
    OperatorRoleDiscoveryError,
    discover_operator_access_role,
)


ACCOUNT = "123456789012"
CLUSTER_ARN = f"arn:aws:iam::{ACCOUNT}:role/cluster-role"
NODE_ARN = f"arn:aws:iam::{ACCOUNT}:role/node-role"
OPERATOR_ARN = f"arn:aws:iam::{ACCOUNT}:role/team/operator"
ROLE_ID = "AROAEXAMPLEOPERATOR"


def response(payload):
    return SimpleNamespace(stdout=json.dumps(payload))


def caller(account=ACCOUNT, arn=None, user_id=f"{ROLE_ID}:session"):
    return {
        "Account": account,
        "Arn": arn or f"arn:aws:sts::{ACCOUNT}:assumed-role/operator/session",
        "UserId": user_id,
    }


def operator_role(arn=OPERATOR_ARN, role_id=ROLE_ID):
    return {"RoleName": "operator", "Path": "/team/", "Arn": arn, "RoleId": role_id}


class DiscoverOperatorRoleTests(unittest.TestCase):
    def test_maps_assumed_session_to_unique_iam_role_and_preserves_path(self):
        run = Mock(side_effect=[response(caller()), response({"Roles": [operator_role()]})])
        self.assertEqual(
            discover_operator_access_role(ACCOUNT, CLUSTER_ARN, NODE_ARN, run), OPERATOR_ARN
        )
        self.assertEqual(run.call_count, 2)
        self.assertIn("sts", run.call_args_list[0].args[0])
        self.assertIn("list-roles", run.call_args_list[1].args[0])

    def test_rejects_caller_from_unexpected_account_before_listing_roles(self):
        run = Mock(return_value=response(caller(account="999999999999")))
        with self.assertRaisesRegex(OperatorRoleDiscoveryError, "conta diferente"):
            discover_operator_access_role(ACCOUNT, CLUSTER_ARN, NODE_ARN, run)
        self.assertEqual(run.call_count, 1)

    def test_rejects_session_arn_without_role_session_identity(self):
        run = Mock(return_value=response(caller(arn=f"arn:aws:iam::{ACCOUNT}:user/operator")))
        with self.assertRaisesRegex(OperatorRoleDiscoveryError, "sessão IAM Role"):
            discover_operator_access_role(ACCOUNT, CLUSTER_ARN, NODE_ARN, run)
        self.assertEqual(run.call_count, 1)

    def test_rejects_missing_or_ambiguous_role_match(self):
        for candidates in ([], [operator_role(), operator_role(arn=f"arn:aws:iam::{ACCOUNT}:role/operator")]):
            with self.subTest(count=len(candidates)):
                run = Mock(side_effect=[response(caller()), response({"Roles": candidates})])
                with self.assertRaisesRegex(OperatorRoleDiscoveryError, "IAM Roles compatíveis"):
                    discover_operator_access_role(ACCOUNT, CLUSTER_ARN, NODE_ARN, run)

    def test_rejects_recreated_role_id_mismatch(self):
        run = Mock(side_effect=[response(caller()), response({"Roles": [operator_role(role_id="AROAOLDROLE")]})])
        with self.assertRaisesRegex(OperatorRoleDiscoveryError, "RoleId.*diverge"):
            discover_operator_access_role(ACCOUNT, CLUSTER_ARN, NODE_ARN, run)

    def test_rejects_operator_role_equal_to_cluster_or_node_role(self):
        for arn in (CLUSTER_ARN, NODE_ARN):
            with self.subTest(arn=arn):
                role = operator_role(arn=arn)
                run = Mock(side_effect=[response(caller()), response({"Roles": [role]})])
                with self.assertRaisesRegex(OperatorRoleDiscoveryError, "coincide"):
                    discover_operator_access_role(ACCOUNT, CLUSTER_ARN, NODE_ARN, run)

    def test_access_denied_does_not_fall_back_to_constructed_arn(self):
        error = subprocess.CalledProcessError(1, "aws iam list-roles", stderr="AccessDenied")
        run = Mock(side_effect=[response(caller()), error])
        with self.assertRaisesRegex(OperatorRoleDiscoveryError, "iam:ListRoles"):
            discover_operator_access_role(ACCOUNT, CLUSTER_ARN, NODE_ARN, run)


if __name__ == "__main__":
    unittest.main()
