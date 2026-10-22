terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "= 3.3.0"
    }
    newrelic = {
      source  = "newrelic/newrelic"
      version = "= 3.100.5"
    }
  }
}


provider "aws" {
  region              = var.region_default
  profile             = var.aws_profile
  allowed_account_ids = var.aws_allowed_account_ids
}

provider "helm" {
  kubernetes = {
    host = var.enable_newrelic_kubernetes ? data.aws_eks_cluster.autoflow[0].endpoint : "https://127.0.0.1"
    cluster_ca_certificate = var.enable_newrelic_kubernetes ? base64decode(
      data.aws_eks_cluster.autoflow[0].certificate_authority[0].data
    ) : null
    token = var.enable_newrelic_kubernetes ? data.aws_eks_cluster_auth.auth[0].token : null
  }
}

provider "newrelic" {
  api_key    = var.newrelic_api_key
  account_id = var.newrelic_account_id
  region     = var.newrelic_region
}

