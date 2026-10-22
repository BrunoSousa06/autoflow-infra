variable "project_name" {
  default = "autoflow"
}

variable "region_default" {
  default = "us-east-1"
}

variable "cidr_vpc" {
  default = "10.0.0.0/16"
}

variable "role_arn" {
  default = "arn:aws:iam::264066152659:role/LabRole"
}
variable "instance_type" {
  default = "t3.medium"
}

variable "enable_newrelic_kubernetes" {
  description = "Habilita o release oficial nri-bundle depois que o EKS existente estiver pronto e aprovado."
  type        = bool
  default     = false
}

variable "enable_newrelic_account_resources" {
  description = "Habilita dashboards, alertas e Synthetic apenas após aprovação de conta, retenção e custo."
  type        = bool
  default     = false
}

variable "newrelic_account_id" {
  description = "Account ID não secreto da conta New Relic; pode ser fornecido por TF_VAR_newrelic_account_id."
  type        = number
  default     = null
  nullable    = true
}

variable "newrelic_api_key" {
  description = "New Relic user API key for Terraform provider; supply externally via TF_VAR_newrelic_api_key, never a tfvars file."
  type        = string
  default     = null
  sensitive   = true
  nullable    = true
}

variable "newrelic_region" {
  description = "Região New Relic aprovada (US ou EU); vazio usa configuração externa do provider."
  type        = string
  default     = null
  nullable    = true
}

variable "newrelic_namespace" {
  description = "Namespace do release e dos workloads AutoFlow; manifests existentes sem namespace caem em default."
  type        = string
  default     = "default"

  validation {
    condition     = can(regex("^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", var.newrelic_namespace))
    error_message = "newrelic_namespace precisa ser um nome de namespace Kubernetes válido."
  }
}

variable "newrelic_license_secret_name" {
  description = "Nome do Secret Kubernetes que será entregue pelo mecanismo externo aprovado; nenhum conteúdo é provisionado aqui."
  type        = string
  default     = "newrelic-license"
}

variable "newrelic_license_secret_key" {
  description = "Chave dentro do Secret Kubernetes externo contendo a license key New Relic."
  type        = string
  default     = "licenseKey"
}

variable "newrelic_environment" {
  description = "Environment tag usado em NRQL; confirmar com os owners antes de habilitar os recursos na conta."
  type        = string
  default     = "local"
}

variable "newrelic_synthetic_url" {
  description = "URL pública aprovada, sem autenticação, query string ou endpoint Actuator; vazio mantém Synthetic desligado."
  type        = string
  default     = ""

  validation {
    condition = var.newrelic_synthetic_url == "" || (
      can(regex("^https?://[^?#]+$", var.newrelic_synthetic_url)) &&
      !strcontains(var.newrelic_synthetic_url, "@")
    )
    error_message = "Informe somente uma URL HTTP(S) pública, sem credenciais, query string ou fragmento."
  }
}

variable "newrelic_synthetic_locations" {
  description = "Locations públicas habilitadas no plano New Relic para o monitor Synthetic."
  type        = list(string)
  default     = []
}

variable "newrelic_backend_availability_alert_query" {
  description = "NRQL validada em homologação que retorna valor > 0 somente quando o backend estiver indisponível; vazia mantém a condição ausente até confirmar evento/atributos Kubernetes."
  type        = string
  default     = ""
  nullable    = false
}

variable "newrelic_backend_availability_dashboard_query" {
  description = "NRQL de dashboard validada em homologação para disponibilidade do backend, incluindo filtros aprovados de ambiente/cluster/namespace; vazia mantém o widget ausente até confirmar o schema Kubernetes."
  type        = string
  default     = ""
  nullable    = false
}

variable "newrelic_backend_cpu_utilization_alert_query" {
  description = "NRQL validada em homologação que retorna utilização percentual de CPU do workload AutoFlow em relação ao limite confirmado; vazia mantém a condição ausente."
  type        = string
  default     = ""
  nullable    = false
}

variable "newrelic_backend_memory_utilization_alert_query" {
  description = "NRQL validada em homologação que retorna utilização percentual de memória do workload AutoFlow em relação ao limite confirmado; vazia mantém a condição ausente."
  type        = string
  default     = ""
  nullable    = false
}
