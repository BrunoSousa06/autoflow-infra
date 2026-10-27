from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PipelineResourceDiscoveryTests(unittest.TestCase):
    def test_eks_outputs_are_published_by_platform_state(self):
        outputs = (ROOT / "infra/output.tf").read_text(encoding="utf-8")
        self.assertIn('output "eks_cluster_name"', outputs)
        self.assertIn('output "eks_node_group_name"', outputs)
        self.assertIn('output "eks_cluster_role_arn"', outputs)
        self.assertIn('output "eks_node_role_arn"', outputs)

    def test_gateway_pipeline_discovers_cluster_and_node_group(self):
        workflow = (ROOT / ".github/workflows/api-gateway.yml").read_text(encoding="utf-8")
        self.assertNotIn("vars.EKS_CLUSTER_NAME", workflow)
        self.assertNotIn("vars.EKS_NODEGROUP_NAME", workflow)
        self.assertIn("aws eks list-clusters", workflow)
        self.assertIn("aws eks list-nodegroups", workflow)
        self.assertIn('"${#NODEGROUPS[@]}" -eq 1', workflow)

    def test_cluster_roles_cannot_fall_back_to_a_shared_arn(self):
        variables = (ROOT / "infra/vars.tf").read_text(encoding="utf-8")
        locals_tf = (ROOT / "infra/locals.tf").read_text(encoding="utf-8")
        self.assertNotIn('variable "role_arn"', variables)
        self.assertNotIn("var.role_arn", locals_tf)
        for variable_name in ("cluster_role_arn", "node_role_arn", "operator_access_role_arn"):
            block = variables.split(f'variable "{variable_name}"', 1)[1].split("\n}", 1)[0]
            self.assertNotIn("default", block)

    def test_operator_role_is_derived_from_the_verified_aws_caller(self):
        workflow = (ROOT / ".github/workflows/pipeline.yml").read_text(encoding="utf-8")
        self.assertEqual(workflow.count("scripts/discover_operator_access_role.py"), 2)
        self.assertNotIn("vars.AWS_EKS_OPERATOR_ACCESS_ROLE_ARN", workflow)
        self.assertIn('echo "TF_VAR_operator_access_role_arn=$OPERATOR_ROLE_ARN" >> "$GITHUB_ENV"', workflow)


if __name__ == "__main__":
    unittest.main()
