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
    host                   = data.aws_eks_cluster.autoflow.endpoint
    cluster_ca_certificate = base64decode(data.aws_eks_cluster.autoflow.certificate_authority[0].data)
    token                  = data.aws_eks_cluster_auth.auth.token
  }
}

provider "newrelic" {
  api_key    = var.newrelic_api_key
  account_id = var.newrelic_account_id
  region     = var.newrelic_region
}

