variable "project_name" {
  default = "autoflow"
}

variable "region_default" {
  default = "us-east-1"
}

variable "aws_profile" {
  description = "Perfil AWS opcional fornecido pela configuração local do processo."
  type        = string
  default     = null
}

variable "aws_allowed_account_ids" {
  description = "Contas AWS permitidas para este provider; fornecidas externamente por ambiente."
  type        = list(string)

  validation {
    condition     = length(var.aws_allowed_account_ids) > 0 && alltrue([for id in var.aws_allowed_account_ids : can(regex("^[0-9]{12}$", id))])
    error_message = "aws_allowed_account_ids deve conter pelo menos um ID de conta AWS válido, fornecido externamente."
  }
}

variable "cidr_vpc" {
  default = "10.0.0.0/16"
}

variable "role_arn" {
  description = "ARN da role compartilhada legado, informado por configuração externa quando necessária."
  type        = string
  default     = null
}

variable "cluster_role_arn" {
  description = "Optional EKS control-plane role override. Defaults to role_arn for backward compatibility."
  type        = string
  default     = null
}

variable "node_role_arn" {
  description = "Optional managed node group role override. Defaults to role_arn for backward compatibility."
  type        = string
  default     = null
}

variable "operator_access_role_arn" {
  description = "Optional IAM role granted EKS cluster access. Defaults to role_arn for backward compatibility."
  type        = string
  default     = null
}

variable "instance_type" {
  description = "Tipo das instâncias do node group; pode ser ajustado por ambiente."
  type        = string
  default     = "t3.medium"
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

variable "node_min_size" {
  description = "Quantidade mínima de nós do managed node group."
  type        = number
  default     = 2
}

variable "node_desired_size" {
  description = "Quantidade desejada de nós do managed node group."
  type        = number
  default     = 2
}

variable "node_max_size" {
  description = "Quantidade máxima de nós do managed node group."
  type        = number
  default     = 3
}

variable "cluster_endpoint_private_access" {
  description = "Habilita o acesso privado à API do EKS pela VPC."
  type        = bool
  default     = true
}

variable "cluster_endpoint_public_access" {
  description = "Habilita o acesso público à API do EKS, sujeito à allowlist de CIDRs."
  type        = bool
  default     = true

  validation {
    condition     = !var.cluster_endpoint_public_access || length(var.cluster_endpoint_public_access_cidrs) > 0
    error_message = "Com o endpoint público habilitado, informe pelo menos um CIDR IPv4 autorizado."
  }
}

variable "cluster_endpoint_public_access_cidrs" {
  description = "CIDRs IPv4 permanentes iniciais do endpoint EKS; leases temporários do runner são gerenciados pela pipeline."
  type        = list(string)
  default     = ["189.6.8.245/32"]

  validation {
    condition     = alltrue([for cidr in var.cluster_endpoint_public_access_cidrs : can(cidrnetmask(cidr)) && cidr != "0.0.0.0/0"])
    error_message = "Os CIDRs devem ser IPv4 válidos e não podem incluir 0.0.0.0/0."
  }
}

variable "create_nat_gateway" {
  description = "Controla a criação de NAT Gateway e da rota de saída das subnets privadas."
  type        = bool
  default     = true
}

variable "create_operator_access_entry" {
  description = "Controla a criação de uma entrada IAM adicional para acesso ao EKS."
  type        = bool
  default     = true
}
