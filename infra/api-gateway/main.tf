data "terraform_remote_state" "eks" {
  backend = "s3"
  config = {
    bucket = var.terraform_state_bucket
    key    = var.infra_state_key
    region = var.aws_region
  }
}
data "aws_eks_cluster" "this" { name = var.cluster_name }
data "aws_eks_node_group" "this" {
  cluster_name    = var.cluster_name
  node_group_name = var.nodegroup_name
}
data "aws_lambda_function" "login" { function_name = var.lambda_function_name }

module "private_eks" {
  source                 = "./modules/private-eks"
  name                   = "autoflow-${var.environment}"
  vpc_id                 = data.terraform_remote_state.eks.outputs.vpc_id
  subnet_ids             = data.terraform_remote_state.eks.outputs.private_subnet_ids
  node_security_group_id = data.aws_eks_cluster.this.vpc_config[0].cluster_security_group_id
  autoscaling_groups     = toset(data.aws_eks_node_group.this.resources[0].autoscaling_groups[*].name)
}

resource "aws_apigatewayv2_api" "this" {
  name          = "autoflow-${var.environment}"
  protocol_type = "HTTP"
  dynamic "cors_configuration" {
    for_each = length(var.cors_origins) > 0 ? [1] : []
    content {
      allow_origins = sort(tolist(var.cors_origins))
      allow_methods = ["GET", "POST", "PATCH", "DELETE", "OPTIONS"]
      allow_headers = ["authorization", "content-type", "accept"]
      max_age       = 300
    }
  }
}

resource "aws_apigatewayv2_integration" "login" {
  api_id                 = aws_apigatewayv2_api.this.id
  integration_type       = "AWS_PROXY"
  integration_uri        = data.aws_lambda_function.login.invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
  timeout_milliseconds   = 20000
}
resource "aws_lambda_permission" "login" {
  statement_id   = "AllowAutoflowHttpApiLogin"
  action         = "lambda:InvokeFunction"
  function_name  = data.aws_lambda_function.login.function_name
  principal      = "apigateway.amazonaws.com"
  source_account = var.expected_account_id
  source_arn     = "${aws_apigatewayv2_api.this.execution_arn}/$default/POST/auth/login"
}
resource "aws_apigatewayv2_route" "login" {
  api_id    = aws_apigatewayv2_api.this.id
  route_key = "POST /auth/login"
  target    = "integrations/${aws_apigatewayv2_integration.login.id}"
}

# Uma integração por path mantém /api somente no contrato externo, sem regex
# de proxy genérico. Parâmetros e query strings continuam preservados.
resource "aws_apigatewayv2_integration" "backend" {
  for_each               = local.backend_paths
  api_id                 = aws_apigatewayv2_api.this.id
  integration_type       = "HTTP_PROXY"
  integration_method     = "ANY"
  integration_uri        = module.private_eks.listener_arns["backend"]
  connection_type        = "VPC_LINK"
  connection_id          = module.private_eks.vpc_link_id
  payload_format_version = "1.0"
  timeout_milliseconds   = 29000
  request_parameters = {
    "overwrite:path" = join("/", [for part in split("/", each.key) : startswith(part, "{") ? "$${request.path.${trim(part, "{}")}}" : part])
  }
}
resource "aws_apigatewayv2_route" "backend" {
  for_each  = local.backend_routes
  api_id    = aws_apigatewayv2_api.this.id
  route_key = each.key
  target    = "integrations/${aws_apigatewayv2_integration.backend[each.value].id}"
}
resource "aws_apigatewayv2_integration" "frontend" {
  api_id                 = aws_apigatewayv2_api.this.id
  integration_type       = "HTTP_PROXY"
  integration_method     = "GET"
  integration_uri        = module.private_eks.listener_arns["frontend"]
  connection_type        = "VPC_LINK"
  connection_id          = module.private_eks.vpc_link_id
  payload_format_version = "1.0"
  timeout_milliseconds   = 29000
  request_parameters     = { "overwrite:path" = "$request.path" }
}
resource "aws_apigatewayv2_route" "frontend" {
  for_each  = local.frontend_routes
  api_id    = aws_apigatewayv2_api.this.id
  route_key = "GET ${each.key}"
  target    = "integrations/${aws_apigatewayv2_integration.frontend.id}"
}

resource "aws_cloudwatch_log_group" "access" {
  name              = "/aws/apigateway/autoflow-${var.environment}"
  retention_in_days = 7
}
resource "aws_apigatewayv2_stage" "this" {
  api_id      = aws_apigatewayv2_api.this.id
  name        = "$default"
  auto_deploy = true
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.access.arn
    # routeKey contém o template, nunca path real, query, IP, body ou headers.
    format = jsonencode({ requestId = "$context.requestId", route = "$context.routeKey", status = "$context.status", latency = "$context.responseLatency", integrationStatus = "$context.integrationStatus" })
  }
  default_route_settings {
    throttling_burst_limit   = 100
    throttling_rate_limit    = 50
    detailed_metrics_enabled = var.enable_detailed_gateway_metrics
  }
  route_settings {
    route_key                = "POST /auth/login"
    throttling_burst_limit   = 10
    throttling_rate_limit    = 5
    detailed_metrics_enabled = true
  }
  depends_on = [aws_lambda_permission.login, aws_apigatewayv2_route.login]
}
resource "aws_cloudwatch_metric_alarm" "errors" {
  alarm_name          = "autoflow-${var.environment}-gateway-5xx"
  namespace           = "AWS/ApiGateway"
  metric_name         = "5xx"
  dimensions          = { ApiId = aws_apigatewayv2_api.this.id }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 5
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = var.alarm_actions
}
resource "aws_cloudwatch_metric_alarm" "targets" {
  for_each            = module.private_eks.target_group_suffixes
  alarm_name          = "autoflow-${var.environment}-${each.key}-sem-targets"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HealthyHostCount"
  dimensions          = { LoadBalancer = module.private_eks.load_balancer_suffix, TargetGroup = each.value }
  statistic           = "Minimum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = var.alarm_actions
}
