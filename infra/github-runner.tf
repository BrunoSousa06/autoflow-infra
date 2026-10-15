data "aws_ssm_parameter" "ubuntu_2404_ami" {
  count = var.create_github_runner ? 1 : 0

  name = "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
}

resource "aws_iam_role" "github_runner" {
  count = var.create_github_runner ? 1 : 0

  name = "${var.project_name}-github-runner"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
  tags = { Name = "${var.project_name}-github-runner-role", Component = "github-runner" }
}

resource "aws_iam_role_policy" "github_runner_secret" {
  count = var.create_github_runner && var.github_app_private_key_secret_arn != "" ? 1 : 0

  name = "read-github-app-private-key"
  role = aws_iam_role.github_runner[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = var.github_app_private_key_secret_arn
    }]
  })
}

resource "aws_iam_instance_profile" "github_runner" {
  count = var.create_github_runner ? 1 : 0

  name = "${var.project_name}-github-runner"
  role = aws_iam_role.github_runner[0].name
}

resource "aws_security_group" "github_runner" {
  count = var.create_github_runner ? 1 : 0

  name        = "${var.project_name}-github-runner"
  description = "Saida HTTPS para GitHub/AWS e sem acesso de entrada ao runner"
  vpc_id      = aws_vpc.autoflow_vpc.id

  egress {
    description = "HTTPS de saida para GitHub, AWS APIs e dependencias"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project_name}-github-runner", Component = "github-runner" }
}

resource "aws_vpc_security_group_ingress_rule" "eks_from_github_runner" {
  count = var.create_github_runner ? 1 : 0

  description                  = "HTTPS do runner AutoFlow para a API privada do EKS"
  security_group_id            = aws_security_group.sg.id
  referenced_security_group_id = aws_security_group.github_runner[0].id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
}

resource "aws_instance" "github_runner" {
  count = var.create_github_runner ? 1 : 0

  ami                         = data.aws_ssm_parameter.ubuntu_2404_ami[0].value
  instance_type               = var.github_runner_instance_type
  subnet_id                   = aws_subnet.subnet_private[0].id
  vpc_security_group_ids      = [aws_security_group.github_runner[0].id]
  iam_instance_profile        = aws_iam_instance_profile.github_runner[0].name
  associate_public_ip_address = false
  user_data = templatefile("${path.module}/github-runner-bootstrap.sh.tftpl", {
    app_id             = var.github_app_id
    installation_id    = var.github_app_installation_id
    repository         = var.github_runner_repository
    private_key_secret = var.github_app_private_key_secret_arn
  })
  user_data_replace_on_change = true

  root_block_device {
    volume_type           = "gp3"
    volume_size           = 30
    encrypted             = true
    delete_on_termination = true
  }

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }

  tags = {
    Name      = "autoflow-github-runner"
    Component = "github-runner"
    Project   = "autoflow"
  }

  depends_on = [
    aws_iam_role_policy.github_runner_secret,
    aws_vpc_security_group_ingress_rule.eks_from_github_runner,
  ]

  lifecycle {
    precondition {
      condition     = var.github_app_id != "" && var.github_app_installation_id != "" && var.github_app_private_key_secret_arn != ""
      error_message = "Para criar o runner, configure GitHub App ID, installation ID e ARN do segredo com a chave privada."
    }
  }
}

output "github_runner_instance_id" {
  description = "ID da EC2 privada dedicada ao runner GitHub Actions."
  value       = var.create_github_runner ? aws_instance.github_runner[0].id : null
}
