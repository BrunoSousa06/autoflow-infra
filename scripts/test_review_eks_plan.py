import unittest

from review_eks_plan import PlanReviewError, review_plan


def resource(address, actions, importing=None):
    change = {"actions": actions}
    if importing is not None:
        change["importing"] = importing
    return {"address": address, "change": change}


class ReviewEksPlanTests(unittest.TestCase):
    def test_accepts_import_create_update_and_noop_without_fixed_counts(self):
        plan = {"resource_changes": [
            resource("aws_vpc.main", ["no-op"], {"id": "vpc-actual"}),
            resource("aws_subnet.private", ["create"]),
            resource("aws_eks_cluster.main", ["update"]),
            resource("aws_eks_node_group.main", ["no-op"]),
        ]}
        counts, destructive = review_plan(plan)
        self.assertEqual(counts, {"no-op": 2, "create": 1, "update": 1})
        self.assertEqual(destructive, [])

    def test_blocks_destroy_and_replacement_by_default(self):
        plan = {"resource_changes": [
            resource("aws_subnet.private", ["delete"]),
            resource("aws_eks_cluster.main", ["delete", "create"]),
        ]}
        with self.assertRaises(PlanReviewError):
            review_plan(plan)

    def test_accepts_destructive_actions_only_with_explicit_authorization(self):
        plan = {"resource_changes": [resource("aws_subnet.private", ["delete", "create"])]}
        counts, destructive = review_plan(plan, allow_destructive=True)
        self.assertEqual(counts, {"delete,create": 1})
        self.assertEqual(destructive, ["aws_subnet.private"])

    def test_rejects_malformed_plan(self):
        with self.assertRaises(PlanReviewError):
            review_plan({"resource_changes": [{"address": "aws_vpc.main", "change": {}}]})


if __name__ == "__main__":
    unittest.main()
