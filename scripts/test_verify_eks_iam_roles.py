import json
from pathlib import Path
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from verify_eks_iam_roles import (
    CLUSTER_SERVICE,
    NODE_SERVICE,
    REQUIRED_POLICIES,
    RolePreflightError,
    cluster_role_matches,
    validate_attached_policies,
    validate_role_configuration,
    validate_trust_policy,
    verify_eks_iam_roles,
)


ACCOUNT = "123456789012"
CLUSTER_ROLE = f"arn:aws:iam::{ACCOUNT}:role/path/eks-control-plane"
NODE_ROLE = f"arn:aws:iam::{ACCOUNT}:role/path/eks-workers"


def trust(service):
    return {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": service},
            "Action": "sts:AssumeRole",
        }],
    }


def policy_documents(names, partition="aws"):
    return [{
        "PolicyName": name,
        "PolicyArn": f"arn:{partition}:iam::aws:policy/{name}",
    } for name in names]


class VerifyEksIamRolesTests(unittest.TestCase):
    def test_role_arns_must_be_present_distinct_and_in_expected_account(self):
        with self.assertRaisesRegex(RolePreflightError, "roles diferentes"):
            validate_role_configuration(CLUSTER_ROLE, CLUSTER_ROLE, ACCOUNT)
        with self.assertRaisesRegex(RolePreflightError, "conta AWS esperada"):
            validate_role_configuration(CLUSTER_ROLE, NODE_ROLE.replace(ACCOUNT, "999999999999"), ACCOUNT)
        with self.assertRaisesRegex(RolePreflightError, "AWS_EKS_NODE_ROLE_ARN ausente"):
            validate_role_configuration(CLUSTER_ROLE, None, ACCOUNT)

    def test_inverted_service_trust_policies_are_rejected(self):
        with self.assertRaisesRegex(RolePreflightError, "eks.amazonaws.com"):
            validate_trust_policy(trust(NODE_SERVICE), CLUSTER_SERVICE, "cluster")
        with self.assertRaisesRegex(RolePreflightError, "ec2.amazonaws.com"):
            validate_trust_policy(trust(CLUSTER_SERVICE), NODE_SERVICE, "node")

    def test_trust_policy_with_explicit_deny_or_unknown_condition_fails_closed(self):
        denied = trust(CLUSTER_SERVICE)
        denied["Statement"].append({
            "Effect": "Deny",
            "Principal": {"Service": CLUSTER_SERVICE},
            "Action": "sts:AssumeRole",
        })
        with self.assertRaisesRegex(RolePreflightError, "contém Deny"):
            validate_trust_policy(denied, CLUSTER_SERVICE, "cluster")

        conditional = trust(CLUSTER_SERVICE)
        conditional["Statement"][0]["Condition"] = {"StringEquals": {"aws:SourceAccount": ACCOUNT}}
        with self.assertRaisesRegex(RolePreflightError, "Condition não verificável"):
            validate_trust_policy(conditional, CLUSTER_SERVICE, "cluster")

        wildcard = trust("*")
        with self.assertRaisesRegex(RolePreflightError, "Service principal wildcard"):
            validate_trust_policy(wildcard, CLUSTER_SERVICE, "cluster")

    def test_required_managed_policies_are_checked_by_role(self):
        validate_attached_policies(
            policy_documents(REQUIRED_POLICIES["cluster"]),
            REQUIRED_POLICIES["cluster"], "aws", "cluster",
        )
        with self.assertRaisesRegex(RolePreflightError, "AmazonEKS_CNI_Policy"):
            validate_attached_policies(
                policy_documents(REQUIRED_POLICIES["node"][:-1]),
                REQUIRED_POLICIES["node"], "aws", "node",
            )

    def test_missing_iam_role_is_reported_without_attempting_any_mutation(self):
        runner = Mock(side_effect=subprocess.CalledProcessError(
            254, ["aws", "iam", "get-role"], stderr="An error occurred (NoSuchEntity)"
        ))
        with self.assertRaisesRegex(RolePreflightError, "não existe"):
            verify_eks_iam_roles("eks-autoflow", "us-east-1", ACCOUNT, CLUSTER_ROLE, NODE_ROLE, runner)
        self.assertIn("get-role", runner.call_args.args[0])
        self.assertTrue(runner.call_args.kwargs["check"])

    def test_existing_cluster_role_must_match_configured_role(self):
        cluster_role_matches(CLUSTER_ROLE, CLUSTER_ROLE)
        with self.assertRaisesRegex(RolePreflightError, "reconstrução controlada"):
            cluster_role_matches(CLUSTER_ROLE, f"arn:aws:iam::{ACCOUNT}:role/other-role")

    def test_preflight_accepts_valid_roles_and_missing_cluster_without_changes(self):
        roles = {
            CLUSTER_ROLE: (CLUSTER_SERVICE, REQUIRED_POLICIES["cluster"]),
            NODE_ROLE: (NODE_SERVICE, REQUIRED_POLICIES["node"]),
        }

        def runner(command, **kwargs):
            if command[1:3] == ["iam", "get-role"]:
                reference = next(arn for arn in roles if arn.endswith("/" + command[command.index("--role-name") + 1]))
                service, _ = roles[reference]
                payload = {"Role": {"Arn": reference, "AssumeRolePolicyDocument": trust(service)}}
            elif command[1:3] == ["iam", "list-attached-role-policies"]:
                reference = next(arn for arn in roles if arn.endswith("/" + command[command.index("--role-name") + 1]))
                payload = {"AttachedPolicies": policy_documents(roles[reference][1])}
            elif command[1:3] == ["eks", "describe-cluster"]:
                raise subprocess.CalledProcessError(
                    254, command, stderr="ResourceNotFoundException: cluster not found"
                )
            else:
                raise AssertionError("Preflight tentou uma operação fora de leitura/inventário esperado")
            return SimpleNamespace(stdout=json.dumps(payload))

        run_role = Mock(side_effect=runner)
        verify_eks_iam_roles("eks-autoflow", "us-east-1", ACCOUNT, CLUSTER_ROLE, NODE_ROLE, run_role)
        self.assertEqual(run_role.call_count, 5)
        self.assertTrue(all(call.args[0][1:3] in (["iam", "get-role"], ["iam", "list-attached-role-policies"], ["eks", "describe-cluster"]) for call in run_role.call_args_list))

    def test_preflight_rejects_cluster_with_different_effective_role(self):
        roles = {
            CLUSTER_ROLE: (CLUSTER_SERVICE, REQUIRED_POLICIES["cluster"]),
            NODE_ROLE: (NODE_SERVICE, REQUIRED_POLICIES["node"]),
        }

        def runner(command, **kwargs):
            if command[1:3] == ["iam", "get-role"]:
                arn = next(item for item in roles if item.endswith("/" + command[command.index("--role-name") + 1]))
                service, _ = roles[arn]
                payload = {"Role": {"Arn": arn, "AssumeRolePolicyDocument": trust(service)}}
            elif command[1:3] == ["iam", "list-attached-role-policies"]:
                arn = next(item for item in roles if item.endswith("/" + command[command.index("--role-name") + 1]))
                payload = {"AttachedPolicies": policy_documents(roles[arn][1])}
            elif command[1:3] == ["eks", "describe-cluster"]:
                payload = {"cluster": {"roleArn": f"arn:aws:iam::{ACCOUNT}:role/previous-cluster-role"}}
            else:
                raise AssertionError("Preflight tentou uma operação fora de leitura/inventário esperado")
            return SimpleNamespace(stdout=json.dumps(payload))

        with self.assertRaisesRegex(RolePreflightError, "reconstrução controlada"):
            verify_eks_iam_roles(
                "eks-autoflow", "us-east-1", ACCOUNT, CLUSTER_ROLE, NODE_ROLE, runner
            )

    def test_workflow_validates_roles_before_plan_and_apply(self):
        workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/pipeline.yml").read_text(encoding="utf-8")
        plan = workflow.split("  plan:", 1)[1].split("\n  apply:\n", 1)[0]
        apply = workflow.split("\n  apply:\n", 1)[1]
        command = "scripts/verify_eks_iam_roles.py"
        plan_role_check = plan.index(command)
        apply_role_check = apply.index(command)
        self.assertLess(plan.index("python scripts/verify_aws_account.py"), plan_role_check)
        self.assertLess(plan_role_check, plan.index("eks_cluster_preflight.py"))
        self.assertLess(apply.index("python scripts/verify_aws_account.py"), apply_role_check)
        self.assertLess(apply_role_check, apply.index("eks_endpoint_access.py authorize"))
        self.assertIn("AWS_EKS_CLUSTER_ROLE_ARN: ${{ vars.AWS_EKS_CLUSTER_ROLE_ARN }}", plan)
        self.assertIn("AWS_EKS_NODE_ROLE_ARN: ${{ vars.AWS_EKS_NODE_ROLE_ARN }}", plan)


if __name__ == "__main__":
    unittest.main()
