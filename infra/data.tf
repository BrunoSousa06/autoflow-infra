
data "aws_eks_cluster" "autoflow" {
  count = var.enable_newrelic_kubernetes ? 1 : 0
  name  = aws_eks_cluster.autoflow.name
}

data "aws_eks_cluster_auth" "auth" {
  count = var.enable_newrelic_kubernetes ? 1 : 0
  name  = aws_eks_cluster.autoflow.name
}
