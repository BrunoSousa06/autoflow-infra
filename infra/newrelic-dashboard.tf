resource "newrelic_one_dashboard" "autoflow" {
  count = var.enable_newrelic_account_resources ? 1 : 0

  name        = "AutoFlow Observability"
  permissions = "private"

  page {
    name = "AutoFlow ${var.newrelic_environment}"

    widget_line {
      title  = "Ordens de serviço criadas por dia"
      row    = 1
      column = 1
      width  = 6
      height = 3

      nrql_query {
        query = "SELECT count(*) FROM AutoFlowOrderCreated WHERE environment = '${var.newrelic_environment}' SINCE 30 days ago TIMESERIES 1 day"
      }
    }

    widget_line {
      title  = "Duração média por fase (segundos)"
      row    = 1
      column = 7
      width  = 6
      height = 3

      nrql_query {
        query = "SELECT average(durationSeconds) FROM AutoFlowOrderStageCompleted WHERE environment = '${var.newrelic_environment}' FACET stage SINCE 30 days ago TIMESERIES"
      }
    }

    widget_line {
      title  = "Amostras por fase concluída"
      row    = 4
      column = 1
      width  = 6
      height = 3

      nrql_query {
        query = "SELECT count(*) FROM AutoFlowOrderStageCompleted WHERE environment = '${var.newrelic_environment}' FACET stage SINCE 30 days ago"
      }
    }

    widget_line {
      title  = "Latência de API (p50/p95/p99, segundos)"
      row    = 4
      column = 7
      width  = 6
      height = 3

      nrql_query {
        query = "SELECT percentile(duration, 50, 95, 99) FROM Transaction WHERE appName = 'autoflow-backend' AND environment = '${var.newrelic_environment}' SINCE 24 hours ago TIMESERIES"
      }
    }

    widget_line {
      title  = "CPU cores por container"
      row    = 7
      column = 1
      width  = 6
      height = 3

      nrql_query {
        query = "SELECT average(cpuCoresUtilization) FROM K8sContainerSample WHERE clusterName = '${aws_eks_cluster.autoflow.name}' AND namespaceName = '${var.newrelic_namespace}' FACET podName SINCE 1 hour ago TIMESERIES"
      }
    }

    widget_line {
      title  = "Memória working set (MiB) por container"
      row    = 7
      column = 7
      width  = 6
      height = 3

      nrql_query {
        query = "SELECT max(memoryWorkingSetBytes) / 1024 / 1024 FROM K8sContainerSample WHERE clusterName = '${aws_eks_cluster.autoflow.name}' AND namespaceName = '${var.newrelic_namespace}' FACET podName SINCE 1 hour ago TIMESERIES"
      }
    }

    widget_line {
      title  = "Falhas inesperadas no processamento de OS"
      row    = 10
      column = 1
      width  = 6
      height = 3

      nrql_query {
        query = "SELECT count(*) FROM AutoFlowOrderProcessingFailure WHERE environment = '${var.newrelic_environment}' FACET operation, failureCode SINCE 24 hours ago TIMESERIES 5 minutes"
      }
    }

    widget_line {
      title  = "Taxa de erro APM"
      row    = 10
      column = 7
      width  = 6
      height = 3

      nrql_query {
        query = "SELECT percentage(count(*), WHERE error IS true) FROM Transaction WHERE appName = 'autoflow-backend' AND environment = '${var.newrelic_environment}' SINCE 24 hours ago TIMESERIES"
      }
    }

    widget_line {
      title  = "Falhas de integração"
      row    = 13
      column = 1
      width  = 6
      height = 3

      nrql_query {
        query = "SELECT count(*) FROM AutoFlowIntegrationFailure WHERE environment = '${var.newrelic_environment}' FACET integration, operation SINCE 7 days ago TIMESERIES 1 hour"
      }
    }

    widget_table {
      title  = "Logs correlacionáveis por request/trace"
      row    = 16
      column = 1
      width  = 12
      height = 4

      nrql_query {
        query = "SELECT timestamp, level, message, request.id, trace.id, span.id FROM Log WHERE service.name = 'autoflow-backend' AND deployment.environment = '${var.newrelic_environment}' SINCE 30 minutes ago LIMIT 100"
      }
    }

    dynamic "widget_line" {
      for_each = trimspace(var.newrelic_backend_availability_dashboard_query) == "" ? [] : [var.newrelic_backend_availability_dashboard_query]

      content {
        title  = "Disponibilidade do backend (NRQL confirmada em homologação)"
        row    = 20
        column = 1
        width  = 12
        height = 3

        nrql_query {
          query = widget_line.value
        }
      }
    }
  }
}
