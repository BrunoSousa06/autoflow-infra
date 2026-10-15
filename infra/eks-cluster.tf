resource "aws_eks_cluster" "autoflow" {
  name     = "eks-${var.project_name}"
  role_arn = local.effective_cluster_role_arn
  version  = "1.35"

  access_config {
    authentication_mode                         = "API"
    bootstrap_cluster_creator_admin_permissions = true

  }

  vpc_config {
    subnet_ids              = concat(aws_subnet.subnet_public[*].id, aws_subnet.subnet_private[*].id)
    security_group_ids      = [aws_security_group.sg.id]
    endpoint_private_access = var.cluster_endpoint_private_access
    endpoint_public_access  = var.cluster_endpoint_public_access
    public_access_cidrs     = var.cluster_endpoint_public_access_cidrs
  }

  lifecycle {
    # A pipeline gerencia CIDRs efêmeros; Terraform não deve revertê-los entre Plan e Apply.
    ignore_changes = [vpc_config[0].public_access_cidrs]
  }
}
