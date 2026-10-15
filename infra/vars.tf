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
