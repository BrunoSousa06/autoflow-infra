
output "vpc_id" {
  description = "ID da VPC do AutoFlow"
  value       = aws_vpc.autoflow_vpc.id
}

output "vpc_cidr_block" {
  description = "CIDR da VPC do AutoFlow"
  value       = aws_vpc.autoflow_vpc.cidr_block
}

output "private_subnet_ids" {
  description = "IDs das subnets privadas"
  value       = aws_subnet.subnet_private[*].id
}

output "eks_security_group_id" {
  description = "Security Group utilizado pelo EKS"
  value       = aws_security_group.sg.id
}

output "eks_cluster_name" {
  description = "Nome do cluster EKS criado por este state"
  value       = aws_eks_cluster.autoflow.name
}

output "eks_node_group_name" {
  description = "Nome do node group criado por este state"
  value       = aws_eks_node_group.node_group.node_group_name
}

output "eks_cluster_role_arn" {
  description = "Role IAM usada exclusivamente pelo control plane EKS"
  value       = aws_eks_cluster.autoflow.role_arn
}

output "eks_node_role_arn" {
  description = "Role IAM usada exclusivamente pelos nodes EKS"
  value       = aws_eks_node_group.node_group.node_role_arn
}

