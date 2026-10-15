import unittest
from unittest.mock import patch

from eks_endpoint_access import authorize, cleanup


class FakeAws:
    def __init__(self, cidrs):
        self.cidrs = set(cidrs)
        self.calls = []
        self.fail_update = False

    def __call__(self, *args):
        self.calls.append(args)
        if args[1] == "describe-cluster":
            return {"cluster": {"resourcesVpcConfig": {"publicAccessCidrs": sorted(self.cidrs)}}}
        if args[1] == "update-cluster-config":
            if self.fail_update:
                raise RuntimeError("falha simulada")
            values = next(x for x in args if x.startswith("publicAccessCidrs="))
            self.cidrs = set(values.split("=", 1)[1].split(","))
            return {"update": {"id": "update-1"}}
        if args[1] == "describe-update":
            return {"update": {"status": "Successful"}}
        raise AssertionError(args)


class EndpointAccessTests(unittest.TestCase):
    def setUp(self):
        self.lease = None
        self.patches = [
            patch("eks_endpoint_access.save_lease", side_effect=lambda value: setattr(self, "lease", value)),
            patch("eks_endpoint_access.load_lease", side_effect=lambda: self.lease),
            patch("eks_endpoint_access.remove_lease", side_effect=lambda: setattr(self, "lease", None)),
        ]
        for mocked in self.patches:
            mocked.start()
            self.addCleanup(mocked.stop)

    @patch("eks_endpoint_access.time.sleep")
    def test_authorize_preserves_existing_and_waits_for_update(self, _sleep):
        aws = FakeAws({"189.6.8.245/32", "203.0.113.4/32"})
        lease = authorize(aws, "eks-autoflow", "us-east-1", "198.51.100.7", ["189.6.8.245/32"])
        self.assertEqual(aws.cidrs, {"189.6.8.245/32", "203.0.113.4/32", "198.51.100.7/32"})
        self.assertEqual(lease["original_cidrs"], ["189.6.8.245/32", "203.0.113.4/32"])
        self.assertEqual([c[1] for c in aws.calls].count("describe-update"), 1)

    def test_fails_closed_if_permanent_cidr_missing(self):
        aws = FakeAws({"203.0.113.4/32"})
        with self.assertRaises(RuntimeError):
            authorize(aws, "eks-autoflow", "us-east-1", "198.51.100.7", ["189.6.8.245/32"])
        self.assertFalse(any(c[1] == "update-cluster-config" for c in aws.calls))

    def test_failure_does_not_change_cidrs(self):
        aws = FakeAws({"189.6.8.245/32"})
        aws.fail_update = True
        with self.assertRaisesRegex(RuntimeError, "simulada"):
            authorize(aws, "eks-autoflow", "us-east-1", "198.51.100.7", ["189.6.8.245/32"])
        self.assertEqual(aws.cidrs, {"189.6.8.245/32"})

    @patch("eks_endpoint_access.time.sleep")
    def test_cleanup_removes_only_runner_ip_and_restores_original_cidrs(self, _sleep):
        aws = FakeAws({"189.6.8.245/32", "198.51.100.7/32"})
        cleanup(aws, "eks-autoflow", "us-east-1", {
            "temporary_cidr": "198.51.100.7/32", "original_cidrs": ["189.6.8.245/32", "203.0.113.4/32"]
        })
        self.assertEqual(aws.cidrs, {"189.6.8.245/32", "203.0.113.4/32"})
        self.assertEqual([c[1] for c in aws.calls].count("describe-update"), 1)

    def test_concurrency_is_configured_at_workflow_scope(self):
        from pathlib import Path
        workflow = Path(__file__).parents[1] / ".github/workflows/pipeline.yml"
        content = workflow.read_text(encoding="utf-8")
        self.assertIn("group: autoflow-eks-endpoint-deploy", content)
        self.assertIn("cancel-in-progress: false", content)
        plan = content.split("  plan:", 1)[1].split("  apply:", 1)[0]
        apply = content.split("\n  apply:\n", 1)[1]
        self.assertNotIn("environment:", plan)
        self.assertIn("environment: homolog", apply)
        self.assertIn("required_reviewers", apply)

    def test_develop_push_plans_and_applies_only_after_environment_approval(self):
        from pathlib import Path
        workflow = Path(__file__).parents[1] / ".github/workflows/pipeline.yml"
        content = workflow.read_text(encoding="utf-8")
        plan = content.split("  plan:", 1)[1].split("  apply:", 1)[0]
        apply = content.split("\n  apply:\n", 1)[1]
        self.assertIn("if: github.ref == 'refs/heads/develop' && (github.event_name == 'push'", plan)
        self.assertIn("ALLOW_DESTRUCTIVE: ${{ inputs.allow_destructive || 'false' }}", plan)
        self.assertIn("github.event_name == 'push'", apply)
        self.assertIn("github.event_name == 'workflow_dispatch' && inputs.apply", apply)
        self.assertIn("environment: homolog", apply)
        self.assertIn("needs: plan", apply)
        self.assertIn("infra-tfplan-${{ github.run_id }}-${{ github.run_attempt }}-${{ github.sha }}", apply)
        self.assertIn("terraform apply -input=false infra.tfplan", apply)
        self.assertNotIn("terraform plan", apply)
        self.assertIn("ALLOW_DESTRUCTIVE: ${{ inputs.allow_destructive || 'false' }}", apply)
        self.assertNotIn("kubectl rollout status", apply)
        self.assertNotIn("backend-deployment", apply)
        self.assertNotIn("frontend-deployment", apply)


if __name__ == "__main__":
    unittest.main()
