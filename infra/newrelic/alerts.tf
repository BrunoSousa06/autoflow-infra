resource "newrelic_alert_policy" "autoflow" {
  count               = var.enable_newrelic_account_resources ? 1 : 0
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
      error_message = "Recursos de conta New Relic exigem account ID, região, API key e identificador de ambiente configurados."
    }
  }
}

resource "newrelic_nrql_alert_condition" "order_processing_failure" {
  count                        = var.enable_newrelic_account_resources ? 1 : 0
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
  count                        = var.enable_newrelic_account_resources ? 1 : 0
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

# O agent Java recebe NEW_RELIC_LABELS=environment:<ambiente>; tags APM são
# consultadas em NRQL pelo prefixo tags., não como atributo environment simples.
# Alertas NRQL não permitem condicionar este agregado ao count(*) >= 20 sem
# subconsulta; a regra de volume mínimo foi removida e baixo volume pode elevar
# a taxa observada. O mesmo limite se aplica ao percentil p95 abaixo.
resource "newrelic_nrql_alert_condition" "api_error_rate" {
  count                        = var.enable_newrelic_account_resources ? 1 : 0
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
    query = <<-NRQL
      SELECT percentage(count(*), WHERE error IS true)
      FROM Transaction
      WHERE appName = 'autoflow-backend' AND tags.environment = '${var.newrelic_environment}'
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
  count                        = var.enable_newrelic_account_resources ? 1 : 0
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
    query = <<-NRQL
      SELECT percentile(duration, 95)
      FROM Transaction
      WHERE appName = 'autoflow-backend' AND tags.environment = '${var.newrelic_environment}'
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
  count                        = var.enable_newrelic_account_resources && trimspace(var.newrelic_backend_availability_alert_query) != "" ? 1 : 0
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
  nrql { query = var.newrelic_backend_availability_alert_query }
  critical {
    operator              = "above"
    threshold             = 0
    threshold_duration    = 300
    threshold_occurrences = "AT_LEAST_ONCE"
  }
}

resource "newrelic_nrql_alert_condition" "backend_cpu_utilization" {
  count                        = var.enable_newrelic_account_resources && trimspace(var.newrelic_backend_cpu_utilization_alert_query) != "" ? 1 : 0
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
  nrql { query = var.newrelic_backend_cpu_utilization_alert_query }
  warning {
    operator              = "above"
    threshold             = 85
    threshold_duration    = 600
    threshold_occurrences = "ALL"
  }
}

resource "newrelic_nrql_alert_condition" "backend_memory_utilization" {
  count                        = var.enable_newrelic_account_resources && trimspace(var.newrelic_backend_memory_utilization_alert_query) != "" ? 1 : 0
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
  nrql { query = var.newrelic_backend_memory_utilization_alert_query }
  warning {
    operator              = "above"
    threshold             = 85
    threshold_duration    = 600
    threshold_occurrences = "ALL"
  }
}
