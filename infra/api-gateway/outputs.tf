output "gateway_url" { value = aws_apigatewayv2_api.this.api_endpoint }
output "api_id" { value = aws_apigatewayv2_api.this.id }
output "vpc_link_id" { value = module.private_eks.vpc_link_id }
output "load_balancer_arn" { value = module.private_eks.load_balancer_arn }
output "target_group_arns" { value = module.private_eks.target_group_arns }
output "backend_routes" { value = sort(keys(local.backend_routes)) }
output "node_ports" { value = module.private_eks.node_ports }
output "cors_origins" { value = var.cors_origins }
