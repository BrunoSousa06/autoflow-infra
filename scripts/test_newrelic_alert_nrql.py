import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALERTS = (ROOT / "infra" / "newrelic" / "alerts.tf").read_text(encoding="utf-8")


def alert_block(name: str) -> str:
    match = re.search(
        rf'^resource "newrelic_nrql_alert_condition" "{re.escape(name)}" \{{(.*?)(?=^resource |\Z)',
        ALERTS,
        re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise AssertionError(f"Bloco do alerta {name!r} não encontrado")
    return match.group(1)


class NewRelicAlertNrqlTests(unittest.TestCase):
    def test_api_error_rate_uses_compatible_percentage_query(self):
        block = alert_block("api_error_rate")
        self.assertIn("percentage(count(*), WHERE error IS true)", block)
        self.assertIn("FROM Transaction", block)
        self.assertIn("appName = 'autoflow-backend'", block)
        self.assertIn("tags.environment = '${var.newrelic_environment}'", block)
        self.assertNotIn("TIMESERIES", block.upper())
        self.assertNotRegex(block, r"(?i)FROM\s*\(")
        self.assertRegex(block, r"threshold\s*=\s*5\b")
        self.assertRegex(block, r"aggregation_window\s*=\s*300\b")
        self.assertRegex(block, r'aggregation_method\s*=\s*"event_flow"')
        self.assertRegex(block, r"aggregation_delay\s*=\s*120\b")
        self.assertRegex(block, r"threshold_duration\s*=\s*300\b")
        self.assertRegex(block, r'threshold_occurrences\s*=\s*"AT_LEAST_ONCE"')

    def test_api_latency_p95_uses_compatible_percentile_query(self):
        block = alert_block("api_latency_p95")
        self.assertIn("percentile(duration, 95)", block)
        self.assertIn("FROM Transaction", block)
        self.assertIn("appName = 'autoflow-backend'", block)
        self.assertIn("tags.environment = '${var.newrelic_environment}'", block)
        self.assertNotIn("TIMESERIES", block.upper())
        self.assertNotRegex(block, r"(?i)FROM\s*\(")
        self.assertRegex(block, r"threshold\s*=\s*2\b")
        self.assertRegex(block, r"aggregation_window\s*=\s*300\b")
        self.assertRegex(block, r'aggregation_method\s*=\s*"event_flow"')
        self.assertRegex(block, r"aggregation_delay\s*=\s*120\b")
        self.assertRegex(block, r"threshold_duration\s*=\s*300\b")
        self.assertRegex(block, r'threshold_occurrences\s*=\s*"AT_LEAST_ONCE"')

    def test_minimum_volume_limitation_is_documented(self):
        self.assertIn("count(*) >= 20", ALERTS)
        self.assertIn("subconsulta", ALERTS)
        self.assertIn("regra de volume mínimo foi removida", ALERTS)


if __name__ == "__main__":
    unittest.main()
