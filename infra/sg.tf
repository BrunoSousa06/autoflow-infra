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
