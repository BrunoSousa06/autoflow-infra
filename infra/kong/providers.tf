provider "aws" {
  region              = var.aws_region
  profile             = var.aws_profile
  allowed_account_ids = var.aws_allowed_account_ids
}

provider "helm" {
  kubernetes {
    host                   = data.aws_eks_cluster.autoflow.endpoint
    cluster_ca_certificate = base64decode(data.aws_eks_cluster.autoflow.certificate_authority[0].data)

    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args = concat(
        ["eks", "get-token", "--cluster-name", var.cluster_name, "--region", var.aws_region],
        var.aws_profile == null ? [] : ["--profile", var.aws_profile]
      )
    }
  }
}
