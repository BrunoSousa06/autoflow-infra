variable "aws_region" {
  description = "Região AWS esperada, fornecida pelo Environment do GitHub."
  type        = string
}
variable "aws_allowed_account_ids" {
  description = "Contas AWS permitidas pelo provider, derivadas da configuração externa."
  type        = list(string)
}
variable "eks_cluster_name" {
  description = "Nome do EKS existente a consultar; nunca cria o cluster."
  type        = string
}
variable "enable_newrelic_kubernetes" {
  description = "Habilita o release nri-bundle somente após EKS e Secret estarem prontos."
  type        = bool
  default     = false
}
variable "enable_newrelic_account_resources" {
  description = "Habilita dashboard, alert policy/conditions e Synthetic após aprovação externa."
  type        = bool
  default     = false
}
variable "newrelic_account_id" {
  description = "Account ID New Relic não secreto, obrigatório para recursos de conta."
  type        = number
  default     = null
  nullable    = true
}
variable "newrelic_api_key" {
  description = "User API key New Relic para provider; fornecida por Secret do Environment."
  type        = string
  default     = null
  sensitive   = true
  nullable    = true
}
variable "newrelic_region" {
  description = "Região da conta New Relic."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.newrelic_region == null || contains(["US", "EU"], var.newrelic_region)
    error_message = "newrelic_region deve ser US ou EU quando fornecida."
  }
}
variable "newrelic_namespace" {
  description = "Namespace dos workloads filtrados pela integração Kubernetes."
  type        = string
  default     = "default"

  validation {
    condition     = length(var.newrelic_namespace) <= 63 && can(regex("^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", var.newrelic_namespace))
    error_message = "newrelic_namespace precisa ser um nome de namespace Kubernetes válido."
  }
}
variable "newrelic_license_secret_name" {
  description = "Nome do Secret Kubernetes existente; Terraform referencia apenas o nome."
  type        = string
  default     = "newrelic-license"

  validation {
    condition     = length(var.newrelic_license_secret_name) <= 63 && can(regex("^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", var.newrelic_license_secret_name))
    error_message = "newrelic_license_secret_name precisa ser um nome Kubernetes válido."
  }
}
variable "newrelic_license_secret_key" {
  description = "Chave dentro do Secret externo contendo a License Key."
  type        = string
  default     = "licenseKey"

  validation {
    condition     = can(regex("^[A-Za-z0-9._-]+$", var.newrelic_license_secret_key))
    error_message = "newrelic_license_secret_key deve conter somente caracteres permitidos."
  }
}
variable "newrelic_environment" {
  description = "Identificador do Environment de deploy usado em nomes e consultas NRQL."
  type        = string
  default     = "local"

  validation {
    condition     = can(regex("^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$", var.newrelic_environment))
    error_message = "newrelic_environment deve ser um rótulo simples."
  }
}
variable "newrelic_synthetic_url" {
  description = "URL pública aprovada para Synthetic; não pode conter credenciais, query ou fragment."
  type        = string
  default     = ""

  validation {
    condition = var.newrelic_synthetic_url == "" || (
      can(regex("^https?://[^?#]+$", var.newrelic_synthetic_url)) &&
      !strcontains(var.newrelic_synthetic_url, "@")
    )
    error_message = "Informe uma URL HTTP(S) sem credenciais, query string ou fragmento."
  }
}
variable "newrelic_synthetic_locations" {
  description = "Locations públicas habilitadas para o monitor Synthetic."
  type        = list(string)
  default     = []
}
variable "newrelic_backend_availability_alert_query" {
  description = "NRQL aprovada para disponibilidade; vazia mantém a condition ausente."
  type        = string
  default     = ""
}
variable "newrelic_backend_availability_dashboard_query" {
  description = "NRQL aprovada para widget de disponibilidade; vazia mantém o widget ausente."
  type        = string
  default     = ""
}
variable "newrelic_backend_cpu_utilization_alert_query" {
  description = "NRQL validada para utilização percentual de CPU; vazia mantém a condition ausente."
  type        = string
  default     = ""
}
variable "newrelic_backend_memory_utilization_alert_query" {
  description = "NRQL validada para utilização percentual de memória; vazia mantém a condition ausente."
  type        = string
  default     = ""
}
variable "newrelic_api_gateway_dashboard_queries" {
  description = "Widgets opcionais de API Gateway com NRQL previamente validada."
  type = list(object({
    title = string
    query = string
  }))
  default  = []
  nullable = false

  validation {
    condition = alltrue([for item in var.newrelic_api_gateway_dashboard_queries :
      trimspace(item.title) != "" && trimspace(item.query) != ""
    ])
    error_message = "Cada widget opcional de API Gateway exige título e consulta NRQL não vazios."
  }
}

provider "aws" {
  region              = var.aws_region
  allowed_account_ids = var.aws_allowed_account_ids
}

data "aws_eks_cluster" "autoflow" {
  count = var.enable_newrelic_kubernetes ? 1 : 0
  name  = var.eks_cluster_name
}

data "aws_eks_cluster_auth" "auth" {
  count = var.enable_newrelic_kubernetes ? 1 : 0
  name  = var.eks_cluster_name
}

provider "helm" {
  kubernetes = {
    host                   = var.enable_newrelic_kubernetes ? data.aws_eks_cluster.autoflow[0].endpoint : "https://127.0.0.1"
    cluster_ca_certificate = var.enable_newrelic_kubernetes ? base64decode(data.aws_eks_cluster.autoflow[0].certificate_authority[0].data) : null
    token                  = var.enable_newrelic_kubernetes ? data.aws_eks_cluster_auth.auth[0].token : null
  }
}

provider "newrelic" {
  api_key    = var.newrelic_api_key
  account_id = var.newrelic_account_id
  region     = var.newrelic_region
}
