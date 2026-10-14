terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }

  }
}


provider "aws" {
  region              = var.region_default
  profile             = var.aws_profile
  allowed_account_ids = var.aws_allowed_account_ids
}

