terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
}
variable "name" { type = string }
variable "vpc_id" { type = string }
variable "subnet_ids" { type = list(string) }
variable "node_security_group_id" { type = string }
variable "autoscaling_groups" { type = set(string) }

locals {
  services = {
    # O health agregado também inclui mail; use o readiness group alinhado ao
    # probe Kubernetes, que verifica disponibilidade efetiva do serviço.
    backend  = { port = 30081, listener = 8081, health = "/actuator/health/readiness" }
    frontend = { port = 30080, listener = 8080, health = "/" }
  }
  attachments = { for pair in setproduct(var.autoscaling_groups, keys(local.services)) : "${pair[0]}-${pair[1]}" => { asg = pair[0], service = pair[1] } }
}
resource "aws_security_group" "link" {
  name_prefix = "${var.name}-link-"
  description = "Saida do VPC Link exclusivamente para o ALB interno"
  vpc_id      = var.vpc_id
  ingress     = []
  egress      = []
  # As regras são gerenciadas pelos recursos aws_vpc_security_group_*_rule.
  # Evita que o provider tente removê-las ao reconciliar atributos inline.
  lifecycle { ignore_changes = [ingress, egress] }
}
resource "aws_security_group" "alb" {
  name_prefix = "${var.name}-alb-"
  description = "ALB privado acessivel somente pelo VPC Link"
  vpc_id      = var.vpc_id
  ingress     = []
  egress      = []
  lifecycle { ignore_changes = [ingress, egress] }
}
resource "aws_vpc_security_group_egress_rule" "link" {
  for_each                     = local.services
  security_group_id            = aws_security_group.link.id
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = each.value.listener
  to_port                      = each.value.listener
}
resource "aws_vpc_security_group_ingress_rule" "alb" {
  for_each                     = local.services
  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = aws_security_group.link.id
  ip_protocol                  = "tcp"
  from_port                    = each.value.listener
  to_port                      = each.value.listener
}
resource "aws_vpc_security_group_egress_rule" "alb" {
  for_each                     = local.services
  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = var.node_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = each.value.port
  to_port                      = each.value.port
}
resource "aws_vpc_security_group_ingress_rule" "nodes" {
  for_each                     = local.services
  security_group_id            = var.node_security_group_id
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = each.value.port
  to_port                      = each.value.port
}
resource "aws_lb" "this" {
  name                       = "${var.name}-private"
  internal                   = true
  load_balancer_type         = "application"
  subnets                    = var.subnet_ids
  security_groups            = [aws_security_group.alb.id]
  drop_invalid_header_fields = true
}
resource "aws_lb_target_group" "this" {
  for_each    = local.services
  name_prefix = each.key == "backend" ? "afbe-" : "affe-"
  port        = each.value.port
  protocol    = "HTTP"
  target_type = "instance"
  vpc_id      = var.vpc_id
  health_check {
    path                = each.value.health
    port                = "traffic-port"
    protocol            = "HTTP"
    matcher             = "200"
    interval            = 30
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
  lifecycle { create_before_destroy = true }
}
resource "aws_lb_listener" "this" {
  for_each          = local.services
  load_balancer_arn = aws_lb.this.arn
  port              = each.value.listener
  protocol          = "HTTP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this[each.key].arn
  }
}
# O ASG registra/desregistra instâncias automaticamente. Não gerenciar o ASG
# do EKS inteiro nem substituir seu health_check_type por ELB.
resource "aws_autoscaling_attachment" "this" {
  for_each               = local.attachments
  autoscaling_group_name = each.value.asg
  lb_target_group_arn    = aws_lb_target_group.this[each.value.service].arn
}
resource "aws_apigatewayv2_vpc_link" "this" {
  name               = var.name
  subnet_ids         = var.subnet_ids
  security_group_ids = [aws_security_group.link.id]
}
output "listener_arns" { value = { for key, value in aws_lb_listener.this : key => value.arn } }
output "vpc_link_id" { value = aws_apigatewayv2_vpc_link.this.id }
output "load_balancer_arn" { value = aws_lb.this.arn }
output "load_balancer_suffix" { value = aws_lb.this.arn_suffix }
output "target_group_arns" { value = { for key, value in aws_lb_target_group.this : key => value.arn } }
output "target_group_suffixes" { value = { for key, value in aws_lb_target_group.this : key => value.arn_suffix } }
output "node_ports" { value = { for key, value in local.services : key => value.port } }
