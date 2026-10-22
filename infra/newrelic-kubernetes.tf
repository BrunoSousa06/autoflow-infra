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
    file("${path.module}/newrelic-values.yaml"),
    yamlencode({
      global = {
        cluster                = aws_eks_cluster.autoflow.name
        customSecretName       = var.newrelic_license_secret_name
        customSecretLicenseKey = var.newrelic_license_secret_key
      }
  })]

  depends_on = [
    aws_eks_cluster.autoflow,
    aws_eks_node_group.node_group,
  ]
}
