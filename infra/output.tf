
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

