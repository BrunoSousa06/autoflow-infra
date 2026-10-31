mock_provider "aws" {
  mock_data "aws_eks_cluster" {
    defaults = { vpc_config = [{ cluster_security_group_id = "sg-12345678" }] }
  }
  mock_data "aws_eks_node_group" {
    defaults = { resources = [{ autoscaling_groups = [{ name = "eks-test-asg" }] }] }
  }
  mock_data "aws_lambda_function" {
    defaults = {
      function_name = "autoflow-test"
      invoke_arn    = "mock-lambda-invoke-uri"
    }
  }
}
override_data {
  target = data.terraform_remote_state.eks
  values = { outputs = { vpc_id = "vpc-12345678", private_subnet_ids = ["subnet-12345678", "subnet-87654321"] } }
}
override_resource {
  target = module.private_eks.aws_security_group.link
  values = {
    id          = "sg-0123456789abcdef0"
    name        = "autoflow-homolog-link-test"
    description = "Saida do VPC Link exclusivamente para o ALB interno"
    vpc_id      = "vpc-12345678"
    ingress     = []
    egress      = []
    tags_all    = { Project = "autoflow", Environment = "homolog", ManagedBy = "Terraform" }
  }
}
override_resource {
  target = module.private_eks.aws_apigatewayv2_vpc_link.this
  values = {
    id                 = "testvpclink"
    name               = "autoflow-homolog"
    subnet_ids         = ["subnet-12345678", "subnet-87654321"]
    security_group_ids = ["sg-0123456789abcdef0"]
  }
}
variables {
  expected_account_id    = format("%012d", 1234)
  terraform_state_bucket = "autoflow-teste-state"
  infra_state_key        = "homolog/test-infra.tfstate"
  lambda_function_name   = "autoflow-test"
}
run "contratos_e_isolamento" {
  command = plan
  assert {
    condition     = aws_apigatewayv2_integration.login.integration_type == "AWS_PROXY" && aws_apigatewayv2_integration.login.payload_format_version == "2.0"
    error_message = "Login deve usar integração nativa Lambda v2."
  }
  assert {
    condition     = !contains(keys(aws_apigatewayv2_route.backend), "POST /api/auth/login") && !contains(keys(aws_apigatewayv2_route.backend), "ANY /api/{proxy+}")
    error_message = "Backend não pode oferecer login concorrente nem proxy genérico."
  }
  assert {
    condition     = aws_apigatewayv2_integration.backend["/clientes/{id}/status"].request_parameters["overwrite:path"] == "/clientes/$${request.path.id}/status"
    error_message = "O prefixo /api deve ser removido preservando os parâmetros."
  }
  assert {
    condition     = length(aws_apigatewayv2_api.this.cors_configuration) == 0
    error_message = "Same-origin não deve abrir CORS."
  }
  assert {
    condition     = aws_lambda_permission.login.principal == "apigateway.amazonaws.com" && aws_lambda_permission.login.source_account == var.expected_account_id
    error_message = "Permissão de invocação deve restringir principal e conta."
  }
  assert {
    condition     = aws_apigatewayv2_stage.this.default_route_settings[0].detailed_metrics_enabled == false
    error_message = "Métricas detalhadas por rota devem permanecer desabilitadas por padrão até aprovação de custo."
  }
  assert {
    condition     = anytrue([for setting in aws_apigatewayv2_stage.this.route_settings : setting.route_key == "POST /auth/login" && setting.detailed_metrics_enabled])
    error_message = "A rota de login deve preservar sua configuração explícita de métricas detalhadas."
  }
  assert {
    condition     = !strcontains(aws_apigatewayv2_stage.this.access_log_settings[0].format, "$context.path") && !strcontains(aws_apigatewayv2_stage.this.access_log_settings[0].format, "sourceIp")
    error_message = "Logs não podem incluir path real ou IP."
  }
}
run "metricas_detalhadas_aprovadas" {
  command = plan
  variables { enable_detailed_gateway_metrics = true }
  assert {
    condition     = aws_apigatewayv2_stage.this.default_route_settings[0].detailed_metrics_enabled == true
    error_message = "A opção aprovada deve habilitar métricas detalhadas nas rotas padrão."
  }
}
run "cors_explicito" {
  command = plan
  variables { cors_origins = ["https://frontend.example.com"] }
  assert {
    condition     = aws_apigatewayv2_api.this.cors_configuration[0].allow_origins == toset(["https://frontend.example.com"])
    error_message = "CORS deve refletir somente a origem aprovada."
  }
}
run "rejeitar_cors_aberto" {
  command = plan
  variables { cors_origins = ["*"] }
  expect_failures = [var.cors_origins]
}
