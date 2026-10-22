resource "newrelic_alert_policy" "autoflow" {
  count = var.enable_newrelic_account_resources ? 1 : 0

  account_id          = var.newrelic_account_id
  name                = "AutoFlow ${var.newrelic_environment}"
  incident_preference = "PER_CONDITION"

  lifecycle {
    precondition {
      condition = alltrue([
        var.newrelic_account_id != null,
        var.newrelic_region != null,
        var.newrelic_api_key != null && var.newrelic_api_key != "",
        var.newrelic_environment != null && trimspace(var.newrelic_environment) != "",
      ])
      error_message = "Recursos de conta New Relic exigem account ID, região, API key e identificadores configurados no environment."
    }
  }
}

resource "newrelic_nrql_alert_condition" "order_processing_failure" {
  count = var.enable_newrelic_account_resources ? 1 : 0

  policy_id                    = newrelic_alert_policy.autoflow[0].id
  account_id                   = var.newrelic_account_id
  name                         = "AutoFlow: falha no processamento de OS"
  type                         = "static"
  enabled                      = true
  violation_time_limit_seconds = 3600
  aggregation_window           = 300
  aggregation_method           = "event_flow"
  aggregation_delay            = 120
  fill_option                  = "none"

  nrql {
    query = "SELECT count(*) FROM AutoFlowOrderProcessingFailure WHERE environment = '${var.newrelic_environment}'"
  }

  critical {
    operator              = "above"
    threshold             = 0
    threshold_duration    = 300
    threshold_occurrences = "AT_LEAST_ONCE"
  }
}

resource "newrelic_nrql_alert_condition" "integration_failure" {
  count = var.enable_newrelic_account_resources ? 1 : 0

  policy_id                    = newrelic_alert_policy.autoflow[0].id
  account_id                   = var.newrelic_account_id
  name                         = "AutoFlow: falha de integração"
  type                         = "static"
  enabled                      = true
  violation_time_limit_seconds = 3600
  aggregation_window           = 300
  aggregation_method           = "event_flow"
  aggregation_delay            = 120
  fill_option                  = "none"

  nrql {
    query = "SELECT count(*) FROM AutoFlowIntegrationFailure WHERE environment = '${var.newrelic_environment}'"
  }

  critical {
    operator              = "above"
    threshold             = 0
    threshold_duration    = 300
    threshold_occurrences = "AT_LEAST_ONCE"
  }
}

resource "newrelic_nrql_alert_condition" "api_error_rate" {
  count = var.enable_newrelic_account_resources ? 1 : 0

  policy_id                    = newrelic_alert_policy.autoflow[0].id
  account_id                   = var.newrelic_account_id
  name                         = "AutoFlow: taxa de erro API"
  type                         = "static"
  enabled                      = true
  violation_time_limit_seconds = 3600
  aggregation_window           = 300
  aggregation_method           = "event_flow"
  aggregation_delay            = 120
  fill_option                  = "none"

  nrql {
    # Buckets internos de cinco minutos incluem numerador e denominador.
    # FACET na agregação mais interna é exigido para agregação aninhada em
    # alertas NRQL; o WHERE externo suprime buckets com menos de 20 transações.
    query = <<-NRQL
      SELECT 100 * sum(errorCount) / sum(transactionCount)
      FROM (
        SELECT filter(count(*), WHERE error IS true) AS errorCount,
               count(*) AS transactionCount
        FROM Transaction
        WHERE appName = 'autoflow-backend' AND environment = '${var.newrelic_environment}'
        FACET appName
        TIMESERIES 5 minutes
      )
      WHERE transactionCount >= 20
    NRQL
  }

  warning {
    operator              = "above"
    threshold             = 5
    threshold_duration    = 300
    threshold_occurrences = "AT_LEAST_ONCE"
  }
}

resource "newrelic_nrql_alert_condition" "api_latency_p95" {
  count = var.enable_newrelic_account_resources ? 1 : 0

  policy_id                    = newrelic_alert_policy.autoflow[0].id
  account_id                   = var.newrelic_account_id
  name                         = "AutoFlow: latência p95 API"
  type                         = "static"
  enabled                      = true
  violation_time_limit_seconds = 3600
  aggregation_window           = 300
  aggregation_method           = "event_flow"
  aggregation_delay            = 120
  fill_option                  = "none"

  nrql {
    # Aplica o mesmo volume mínimo usado no alerta de taxa de erro.
    query = <<-NRQL
      SELECT max(p95Duration)
      FROM (
        SELECT percentile(duration, 95) AS p95Duration,
               count(*) AS transactionCount
        FROM Transaction
        WHERE appName = 'autoflow-backend' AND environment = '${var.newrelic_environment}'
        FACET appName
        TIMESERIES 5 minutes
      )
      WHERE transactionCount >= 20
    NRQL
  }

  warning {
    operator              = "above"
    threshold             = 2
    threshold_duration    = 300
    threshold_occurrences = "AT_LEAST_ONCE"
  }
}

resource "newrelic_nrql_alert_condition" "backend_unavailable" {
  count = var.enable_newrelic_account_resources && trimspace(var.newrelic_backend_availability_alert_query) != "" ? 1 : 0

  policy_id                    = newrelic_alert_policy.autoflow[0].id
  account_id                   = var.newrelic_account_id
  name                         = "AutoFlow: backend indisponível"
  type                         = "static"
  enabled                      = true
  violation_time_limit_seconds = 3600
  aggregation_window           = 300
  aggregation_method           = "event_flow"
  aggregation_delay            = 120
  fill_option                  = "none"

  nrql {
    # Preencher somente após P08 confirmar o evento e os atributos Kubernetes
    # reais no New Relic. A consulta deve retornar > 0 somente enquanto o
    # workload aprovado estiver indisponível.
    query = var.newrelic_backend_availability_alert_query
  }

  critical {
    operator              = "above"
    threshold             = 0
    threshold_duration    = 300
    threshold_occurrences = "AT_LEAST_ONCE"
  }
}

resource "newrelic_nrql_alert_condition" "backend_cpu_utilization" {
  count = var.enable_newrelic_account_resources && trimspace(var.newrelic_backend_cpu_utilization_alert_query) != "" ? 1 : 0

  policy_id                    = newrelic_alert_policy.autoflow[0].id
  account_id                   = var.newrelic_account_id
  name                         = "AutoFlow: utilização de CPU"
  type                         = "static"
  enabled                      = true
  violation_time_limit_seconds = 3600
  aggregation_window           = 300
  aggregation_method           = "event_flow"
  aggregation_delay            = 120
  fill_option                  = "none"

  nrql {
    # A consulta deve retornar percentual de utilização sobre limite real validado.
    query = var.newrelic_backend_cpu_utilization_alert_query
  }

  warning {
    operator              = "above"
    threshold             = 85
    threshold_duration    = 600
    threshold_occurrences = "ALL"
  }
}

resource "newrelic_nrql_alert_condition" "backend_memory_utilization" {
  count = var.enable_newrelic_account_resources && trimspace(var.newrelic_backend_memory_utilization_alert_query) != "" ? 1 : 0

  policy_id                    = newrelic_alert_policy.autoflow[0].id
  account_id                   = var.newrelic_account_id
  name                         = "AutoFlow: utilização de memória"
  type                         = "static"
  enabled                      = true
  violation_time_limit_seconds = 3600
  aggregation_window           = 300
  aggregation_method           = "event_flow"
  aggregation_delay            = 120
  fill_option                  = "none"

  nrql {
    # A consulta deve retornar percentual de utilização sobre limite real validado.
    query = var.newrelic_backend_memory_utilization_alert_query
  }

  warning {
    operator              = "above"
    threshold             = 85
    threshold_duration    = 600
    threshold_occurrences = "ALL"
  }
}
