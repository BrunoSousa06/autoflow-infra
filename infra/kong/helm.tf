locals {
  chart_version = "3.4.1"
}

resource "helm_release" "kong" {
  name             = "kong"
  namespace        = "kong"
  create_namespace = true

  repository = "https://charts.konghq.com"
  chart      = "kong"
  version    = local.chart_version

  values = [file("${path.module}/values.yaml")]

  atomic          = true
  cleanup_on_fail = true
  skip_crds       = false
  wait            = true
  wait_for_jobs   = true
  timeout         = 900
  max_history     = 10
}

output "kong_release_name" {
  description = "Helm release name for the Kong OSS Gateway and KIC."
  value       = helm_release.kong.name
}

output "kong_namespace" {
  description = "Namespace containing Kong Gateway, KIC, and the KIC CRDs."
  value       = helm_release.kong.namespace
}
