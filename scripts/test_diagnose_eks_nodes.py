import unittest

from diagnose_eks_nodes import compare_instances


def node(instance_id, ready):
    return {
        "spec": {"providerID": f"aws:///us-east-1a/{instance_id}"},
        "status": {"conditions": [{"type": "Ready", "status": "True" if ready else "False"}]},
    }


class DiagnoseEksNodesTests(unittest.TestCase):
    def test_detects_running_instances_missing_from_kubernetes(self):
        report = compare_instances({"i-ready", "i-missing"}, [node("i-ready", True)])

        self.assertEqual(report["ready"], ["i-ready"])
        self.assertEqual(report["not_registered"], ["i-missing"])
        self.assertEqual(report["not_ready"], [])

    def test_separates_registered_not_ready_and_stale_kubernetes_node(self):
        report = compare_instances({"i-running"}, [node("i-running", False), node("i-stopped", True)])

        self.assertEqual(report["not_ready"], ["i-running"])
        self.assertEqual(report["ready_not_running"], ["i-stopped"])

    def test_ignores_nodes_without_an_ec2_provider_id(self):
        report = compare_instances(set(), [{"spec": {"providerID": ""}, "status": {"conditions": []}}], desired_size=2)

        self.assertEqual(report["ready"], [])
        self.assertEqual(report["not_registered"], [])
        self.assertTrue(report["desired_mismatch"])


if __name__ == "__main__":
    unittest.main()
