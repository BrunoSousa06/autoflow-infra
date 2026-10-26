resource "aws_security_group" "sg" {
  name        = "${var.project_name}-sg"
  description = "Security group for EKS cluster"
  vpc_id      = aws_vpc.autoflow_vpc.id

  egress {
    description = "All"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_vpc_security_group_ingress_rule" "eks_self" {
  security_group_id            = aws_eks_cluster.autoflow.vpc_config[0].cluster_security_group_id
  referenced_security_group_id = aws_eks_cluster.autoflow.vpc_config[0].cluster_security_group_id
  ip_protocol                  = "-1"
  description                  = "Allow communication between EKS cluster security group members"
}
