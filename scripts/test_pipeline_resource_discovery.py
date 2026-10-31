from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PipelineResourceDiscoveryTests(unittest.TestCase):
    def test_eks_outputs_are_published_by_platform_state(self):
        outputs = (ROOT / "infra/output.tf").read_text(encoding="utf-8")
        self.assertIn('output "eks_cluster_name"', outputs)
        self.assertIn('output "eks_node_group_name"', outputs)
        self.assertIn('output "eks_cluster_role_arn"', outputs)
        self.assertIn('output "eks_node_role_arn"', outputs)

    def test_gateway_pipeline_selects_cluster_node_group_lambda_and_state_by_environment(self):
        workflow = (ROOT / ".github/workflows/api-gateway.yml").read_text(encoding="utf-8")
        self.assertNotIn("vars.EKS_CLUSTER_NAME", workflow)
        self.assertNotIn("vars.EKS_NODEGROUP_NAME", workflow)
        self.assertIn("EKS_PROJECT_NAME: ${{ github.ref == 'refs/heads/main' && 'autoflow-production' || 'autoflow' }}", workflow)
        self.assertIn("EKS_CLUSTER_NAME: eks-${{ github.ref == 'refs/heads/main' && 'autoflow-production' || 'autoflow' }}", workflow)
        self.assertIn("EKS_NODEGROUP_NAME: nodeg-${{ github.ref == 'refs/heads/main' && 'autoflow-production' || 'autoflow' }}", workflow)
        self.assertIn("TF_VAR_lambda_function_name: autoflow-cpf-validator-${{ github.ref == 'refs/heads/main' && 'production' || 'homolog' }}", workflow)
        self.assertIn("aws eks describe-cluster --name \"$TF_VAR_cluster_name\"", workflow)
        self.assertIn("aws eks describe-nodegroup --cluster-name \"$TF_VAR_cluster_name\" --nodegroup-name \"$TF_VAR_nodegroup_name\"", workflow)
        self.assertNotIn("aws eks list-clusters", workflow)
        self.assertNotIn("aws eks list-nodegroups", workflow)
        self.assertIn('[[ "$TF_STATE_KEY" == "$GITHUB_DEPLOYMENT_ENVIRONMENT/"* ]]', workflow)
        self.assertIn('[[ "$TF_VAR_infra_state_key" == "$GITHUB_DEPLOYMENT_ENVIRONMENT/"* ]]', workflow)

    def test_platform_names_and_subnet_discovery_tags_follow_the_project_name(self):
        pipeline = (ROOT / ".github/workflows/pipeline.yml").read_text(encoding="utf-8")
        subnet = (ROOT / "infra/subnet.tf").read_text(encoding="utf-8")
        for job in (pipeline.split("  plan:", 1)[1].split("  apply:", 1)[0], pipeline.split("\n  apply:\n", 1)[1]):
            self.assertIn("TF_VAR_project_name: ${{ github.ref == 'refs/heads/main' && 'autoflow-production' || 'autoflow' }}", job)
            self.assertIn("EKS_CLUSTER_NAME: eks-${{ github.ref == 'refs/heads/main' && 'autoflow-production' || 'autoflow' }}", job)
            self.assertIn('--project-name "$TF_VAR_project_name"', job)
        self.assertEqual(subnet.count('"kubernetes.io/cluster/eks-${var.project_name}" = "shared"'), 2)
        self.assertNotIn('"kubernetes.io/cluster/eks-autoflow"', subnet)
        vpc = (ROOT / "infra/vpc.tf").read_text(encoding="utf-8")
        routes = (ROOT / "infra/route-t.tf").read_text(encoding="utf-8")
        cluster = (ROOT / "infra/eks-cluster.tf").read_text(encoding="utf-8")
        node_group = (ROOT / "infra/eks-node.tf").read_text(encoding="utf-8")
        security_group = (ROOT / "infra/sg.tf").read_text(encoding="utf-8")
        self.assertIn('Name = var.project_name == "autoflow" ? "main-vpc" : "main-vpc-${var.project_name}"', vpc)
        self.assertIn('name     = "eks-${var.project_name}"', cluster)
        self.assertIn('node_group_name = "nodeg-${var.project_name}"', node_group)
        self.assertIn('name        = "${var.project_name}-sg"', security_group)
        for tag in ("public-rt", "private-rt", "nat-eip", "nat-gateway"):
            self.assertIn(f'"${{var.project_name}}-{tag}"', routes)
        network_imports = (ROOT / "scripts/prepare_eks_network_imports.py").read_text(encoding="utf-8")
        self.assertIn('cluster_name = f"eks-{project_name}"', network_imports)
        self.assertIn('nodegroup_name = f"nodeg-{project_name}"', network_imports)
        self.assertNotIn('cluster_exists("eks-autoflow"', network_imports)

    def test_newrelic_selects_the_environment_cluster_without_account_wide_uniqueness(self):
        workflow = (ROOT / ".github/workflows/newrelic.yml").read_text(encoding="utf-8")
        self.assertIn("EKS_CLUSTER_NAME: eks-${{ github.ref == 'refs/heads/main' && 'autoflow-production' || 'autoflow' }}", workflow)
        self.assertIn('aws eks describe-cluster --name "$EKS_CLUSTER_NAME"', workflow)
        self.assertNotIn("aws eks list-clusters", workflow)
        self.assertIn("TF_VAR_newrelic_environment: ${{ github.ref == 'refs/heads/main' && 'production' || 'homolog' }}", workflow)
        self.assertIn("EKS_LEASE_KEY: ci/${{ github.ref == 'refs/heads/main' && 'production' || 'homolog' }}/eks-endpoint-lease-newrelic-", workflow)

    def test_aws_account_is_environment_input_and_fails_closed_before_aws_credentials(self):
        for workflow_name, preflight_name in (
            ("pipeline.yml", "Validar configuração obrigatória antes do acesso AWS"),
            ("api-gateway.yml", "Exigir credenciais temporárias e CORS explícito"),
            ("newrelic.yml", "Validar configuração antes de acessar AWS"),
        ):
            with self.subTest(workflow=workflow_name):
                workflow = (ROOT / ".github/workflows" / workflow_name).read_text(encoding="utf-8")
                plan = workflow.split("\n  plan:", 1)[1].split("\n  apply:", 1)[0]
                validator = (ROOT / "scripts/validate_github_environment.py").read_text(encoding="utf-8")
                self.assertRegex(workflow, r"AWS_EXPECTED_ACCOUNT_ID: \$\{\{ vars\.AWS_EXPECTED_ACCOUNT_ID \}\}")
                self.assertIn("AWS_ACCOUNT_ID_PATTERN", validator)
                self.assertIn("--environment \"$GITHUB_DEPLOYMENT_ENVIRONMENT\"", plan)
                self.assertIn("scripts/validate_github_environment.py", plan)
                self.assertLess(plan.index(preflight_name), plan.index("aws-actions/configure-aws-credentials@v4"))
                self.assertNotRegex(workflow, r"(?<!\d)\d{12}(?!\d)")

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
