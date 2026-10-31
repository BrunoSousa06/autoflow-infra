terraform {
  required_version = ">= 1.6.0"

  backend "s3" {}

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
