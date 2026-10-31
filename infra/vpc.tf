resource "aws_vpc" "autoflow_vpc" {
  cidr_block           = var.cidr_vpc
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = var.project_name == "autoflow" ? "main-vpc" : "main-vpc-${var.project_name}"
  }
}
