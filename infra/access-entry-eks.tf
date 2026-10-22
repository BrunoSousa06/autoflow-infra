resource "aws_eks_access_entry" "access_entry" {
  count = var.create_operator_access_entry ? 1 : 0

  cluster_name  = aws_eks_cluster.autoflow.name
  principal_arn = local.effective_access_role_arn
  type          = "STANDARD"
}

resource "aws_eks_access_policy_association" "labrole_admin" {
  count = var.create_operator_access_entry ? 1 : 0

  cluster_name  = aws_eks_cluster.autoflow.name
  principal_arn = local.effective_access_role_arn

  policy_arn = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"

  access_scope {
    type = "cluster"
  }

  depends_on = [
    aws_eks_access_entry.access_entry
  ]
}