variable "aws_region" {
  description = "AWS region containing the EKS cluster."
  type        = string
  default     = "us-east-1"
}

variable "aws_profile" {
  description = "Perfil AWS opcional usado pelo provider e pelo exec do Helm."
  type        = string
  default     = null
}

variable "aws_allowed_account_ids" {
  description = "Contas AWS permitidas para o provider do root Kong."
  type        = list(string)

  validation {
    condition     = length(var.aws_allowed_account_ids) > 0 && alltrue([for id in var.aws_allowed_account_ids : can(regex("^[0-9]{12}$", id))])
    error_message = "aws_allowed_account_ids deve conter pelo menos um ID de conta AWS válido, fornecido externamente."
  }
}

variable "cluster_name" {
  description = "Existing EKS cluster to which the Kong Helm release is installed."
  type        = string
  default     = "eks-autoflow"
}
