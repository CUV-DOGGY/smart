import os
import unittest
from unittest.mock import patch

from app.config.config import Settings


class ObservabilitySettingsTests(unittest.TestCase):
    def test_observability_is_disabled_by_default(self):
        self.assertIs(
            Settings.model_fields["OBSERVABILITY_ENABLED"].default,
            False,
        )
        self.assertIs(
            Settings.model_fields["BROWSER_TELEMETRY_ENABLED"].default,
            False,
        )

    def test_observability_can_be_enabled_from_the_environment(self):
        with patch.dict(
            os.environ,
            {"OBSERVABILITY_ENABLED": "true"},
            clear=False,
        ):
            configured = Settings(_env_file=None)

        self.assertTrue(configured.OBSERVABILITY_ENABLED)

    def test_trace_sample_ratio_must_be_between_zero_and_one(self):
        with self.assertRaises(ValueError):
            Settings(
                _env_file=None,
                OTEL_TRACE_SAMPLE_RATIO=1.01,
            )

    def test_metric_export_interval_has_a_safe_lower_bound(self):
        with self.assertRaises(ValueError):
            Settings(
                _env_file=None,
                OTEL_METRIC_EXPORT_INTERVAL=999,
            )


if __name__ == "__main__":
    unittest.main()
