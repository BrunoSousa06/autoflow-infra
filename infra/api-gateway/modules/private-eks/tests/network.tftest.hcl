mock_provider "aws" {}
variables {
  name                   = "autoflow-teste"
  vpc_id                 = "vpc-12345678"
  subnet_ids             = ["subnet-12345678", "subnet-87654321"]
  node_security_group_id = "sg-12345678"
  autoscaling_groups     = ["eks-asg-dinamico"]
}
run "rede_privada_e_targets_dinamicos" {
  command = plan
  assert {
    condition     = aws_lb.this.internal && aws_lb.this.load_balancer_type == "application"
    error_message = "O balanceador deve ser um ALB interno."
  }
  assert {
    condition     = alltrue([for rule in aws_vpc_security_group_ingress_rule.nodes : rule.cidr_ipv4 == null && rule.cidr_ipv6 == null])
    error_message = "NodePorts não podem aceitar CIDRs públicos."
  }
  assert {
    condition     = length(aws_security_group.link.egress) == 0 && length(aws_security_group.alb.egress) == 0
    error_message = "Os SGs não podem preservar a regra egress default 0.0.0.0/0."
  }
  assert {
    condition     = length(aws_autoscaling_attachment.this) == 2 && alltrue([for attachment in aws_autoscaling_attachment.this : attachment.autoscaling_group_name == "eks-asg-dinamico"])
    error_message = "Targets devem ser gerenciados pelo ASG, sem instâncias/IPs fixos."
  }
  assert {
    condition     = aws_lb_target_group.this["backend"].health_check[0].path == "/actuator/health/readiness" && aws_lb_target_group.this["backend"].port == 30081
    error_message = "Health deve atingir o backend pelo NodePort privado."
  }
}
