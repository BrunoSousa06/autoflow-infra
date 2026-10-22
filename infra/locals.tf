locals {
  effective_cluster_role_arn = var.cluster_role_arn != null ? var.cluster_role_arn : var.role_arn
  effective_node_role_arn    = var.node_role_arn != null ? var.node_role_arn : var.role_arn
  effective_access_role_arn  = var.operator_access_role_arn != null ? var.operator_access_role_arn : var.role_arn
}
