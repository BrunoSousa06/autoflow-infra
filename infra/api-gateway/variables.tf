variable "aws_region" {
  type    = string
  default = "us-east-1"
}
variable "expected_account_id" {
  type        = string
  description = "Conta aprovada para a implantação; obrigatória também no CI."
  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "Informe uma conta AWS de 12 dígitos."
  }
}
variable "environment" {
  type    = string
  default = "homolog"
}
variable "terraform_state_bucket" {
  type        = string
  description = "Bucket existente, provisionado fora deste state."
}
variable "infra_state_key" {
  type    = string
  default = "eks/terraform.tfstate"
}
variable "cluster_name" {
  type    = string
  default = "eks-autoflow"
}
variable "nodegroup_name" {
  type    = string
  default = "nodeg-autoflow"
}
variable "lambda_function_name" {
  type        = string
  description = "Nome da Lambda existente; não usa Function URL."
}
variable "cors_origins" {
  type        = set(string)
  default     = []
  description = "Origens HTTPS externas efetivamente usadas. Vazio: frontend e API same-origin, sem CORS cross-origin."
  validation {
    condition     = alltrue([for origin in var.cors_origins : can(regex("^https://[a-zA-Z0-9.-]+(:[0-9]+)?$", origin))])
    error_message = "CORS exige origens HTTPS exatas, sem wildcard, path ou barra final."
  }
}
variable "alarm_actions" {
  type        = list(string)
  default     = []
  description = "ARNs de tópicos SNS existentes e autorizados. Vazio mantém alarmes consultáveis sem notificações."
}
variable "enable_detailed_gateway_metrics" {
  type        = bool
  default     = false
  description = "Habilita métricas CloudWatch detalhadas por rota HTTP API; pode aumentar custos AWS. Habilitar após aprovação."
}
