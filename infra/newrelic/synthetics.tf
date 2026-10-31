locals {
  newrelic_synthetic_monitor_name = "AutoFlow ${var.newrelic_environment} public uptime"
}

resource "newrelic_synthetics_monitor" "autoflow_uptime" {
  count = var.enable_newrelic_account_resources && var.newrelic_synthetic_url != "" && length(var.newrelic_synthetic_locations) > 0 ? 1 : 0

  name             = local.newrelic_synthetic_monitor_name
  type             = "SIMPLE"
  period           = "EVERY_5_MINUTES"
  status           = "ENABLED"
  uri              = var.newrelic_synthetic_url
  locations_public = var.newrelic_synthetic_locations
  verify_ssl       = true
}

resource "newrelic_nrql_alert_condition" "synthetic_failure" {
  count = var.enable_newrelic_account_resources && var.newrelic_synthetic_url != "" && length(var.newrelic_synthetic_locations) > 0 ? 1 : 0

  policy_id                    = newrelic_alert_policy.autoflow[0].id
  account_id                   = var.newrelic_account_id
  name                         = "AutoFlow: indisponibilidade Synthetic"
  type                         = "static"
  enabled                      = true
  violation_time_limit_seconds = 3600
  aggregation_window           = 300
  aggregation_method           = "event_flow"
  aggregation_delay            = 300
  fill_option                  = "none"

  nrql {
    query = "SELECT filter(count(*), WHERE result = 'FAILED') FROM SyntheticCheck WHERE monitorName = '${local.newrelic_synthetic_monitor_name}'"
  }

  critical {
    operator              = "above"
    threshold             = 0
    threshold_duration    = 600
    threshold_occurrences = "ALL"
  }

  depends_on = [newrelic_synthetics_monitor.autoflow_uptime]
}
