resource "helm_release" "newrelic_kubernetes" {
  count = var.enable_newrelic_kubernetes ? 1 : 0

  name             = "newrelic-kubernetes"
  repository       = "https://helm-charts.newrelic.com"
  chart            = "nri-bundle"
  version          = "8.0.32"
  namespace        = var.newrelic_namespace
  create_namespace = false
  atomic           = false
  wait             = true

  values = [
    file("${path.module}/values.yaml"),
    yamlencode({
      global = {
        cluster                = var.eks_cluster_name
        customSecretName       = var.newrelic_license_secret_name
        customSecretLicenseKey = var.newrelic_license_secret_key
      }
      "newrelic-logging" = {
        fluentBit = {
          config = {
            extraFilters = <<-FILTER
              [FILTER]
                  Name   grep
                  Match  kube.*
                  Regex  namespace_name ^${var.newrelic_namespace}$
            FILTER
          }
        }
      }
    })
  ]

  depends_on = [data.aws_eks_cluster.autoflow, data.aws_eks_cluster_auth.auth]
}
