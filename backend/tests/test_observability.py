import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI

from app.observability.context import (
    bind_request_id,
    bind_run_id,
    current_request_id,
    current_run_id,
    reset_request_id,
    reset_run_id,
)
from app.observability.setup import (
    _sanitize_async_httpx_span_url,
    _safe_outbound_url,
    _sanitize_httpx_span_url,
    _signal_endpoint,
    setup_observability,
    shutdown_observability,
)
from app.observability.metrics import ApplicationTelemetry


class RecordingInstrument:
    def __init__(self):
        self.calls = []

    def add(self, value, attributes=None):
        self.calls.append((value, attributes or {}))

    def record(self, value, attributes=None):
        self.calls.append((value, attributes or {}))

    def set(self, value, attributes=None):
        self.calls.append((value, attributes or {}))


class RecordingMeter:
    def __init__(self):
        self.instruments = {}

    def create(self, name, **_kwargs):
        instrument = RecordingInstrument()
        self.instruments[name] = instrument
        return instrument

    create_counter = create
    create_histogram = create
    create_gauge = create


class ObservabilitySetupTests(unittest.TestCase):
    def test_signal_endpoint_normalizes_trailing_slash(self):
        self.assertEqual(
            _signal_endpoint("http://127.0.0.1:4318/", "traces"),
            "http://127.0.0.1:4318/v1/traces",
        )

    def test_disabled_setup_is_idempotent_and_does_not_create_providers(self):
        app = FastAPI()
        with patch(
            "app.observability.setup.settings.OBSERVABILITY_ENABLED",
            False,
        ):
            first = setup_observability(app)
            second = setup_observability(app)

        self.assertIs(first, second)
        self.assertFalse(first.enabled)
        self.assertIsNone(first.tracer_provider)
        self.assertIsNone(first.meter_provider)
        shutdown_observability(app)

    def test_outbound_url_drops_query_parameters_and_fragment(self):
        safe_url = _safe_outbound_url(
            "https://restapi.amap.com/v3/geocode/geo"
            "?address=private-address&city=private-city&key=secret#fragment"
        )

        self.assertEqual(
            safe_url,
            "https://restapi.amap.com/v3/geocode/geo",
        )
        self.assertNotIn("private-address", safe_url)
        self.assertNotIn("secret", safe_url)

    def test_outbound_url_drops_embedded_credentials(self):
        safe_url = _safe_outbound_url(
            "https://private-user:private-password@example.com:8443/path"
        )

        self.assertEqual(safe_url, "https://example.com:8443/path")
        self.assertNotIn("private-user", safe_url)
        self.assertNotIn("private-password", safe_url)

    def test_httpx_hook_overrides_both_url_attribute_names(self):
        class RecordingSpan:
            def __init__(self):
                self.attributes = {}

            @staticmethod
            def is_recording():
                return True

            def set_attribute(self, name, value):
                self.attributes[name] = value

        span = RecordingSpan()
        request_info = SimpleNamespace(
            url=(
                "https://restapi.amap.com/v3/geocode/geo"
                "?address=private-address&key=secret"
            )
        )

        _sanitize_httpx_span_url(span, request_info)

        expected = "https://restapi.amap.com/v3/geocode/geo"
        self.assertEqual(span.attributes["url.full"], expected)
        self.assertEqual(span.attributes["http.url"], expected)

    def test_async_httpx_hook_uses_the_same_url_sanitization(self):
        class RecordingSpan:
            def __init__(self):
                self.attributes = {}

            @staticmethod
            def is_recording():
                return True

            def set_attribute(self, name, value):
                self.attributes[name] = value

        span = RecordingSpan()
        request_info = SimpleNamespace(
            url=(
                "https://restapi.amap.com/v3/geocode/geo"
                "?address=private-address&key=secret"
            )
        )

        asyncio.run(_sanitize_async_httpx_span_url(span, request_info))

        expected = "https://restapi.amap.com/v3/geocode/geo"
        self.assertEqual(span.attributes["url.full"], expected)
        self.assertEqual(span.attributes["http.url"], expected)


class ObservabilityContextTests(unittest.TestCase):
    def test_request_id_binding_is_reset(self):
        self.assertIsNone(current_request_id())
        token = bind_request_id("request-123")
        try:
            self.assertEqual(current_request_id(), "request-123")
        finally:
            reset_request_id(token)
        self.assertIsNone(current_request_id())

    def test_run_id_binding_is_reset(self):
        self.assertIsNone(current_run_id())
        token = bind_run_id("run-123")
        try:
            self.assertEqual(current_run_id(), "run-123")
        finally:
            reset_run_id(token)
        self.assertIsNone(current_run_id())


class ApplicationMetricTests(unittest.TestCase):
    def test_dependency_metrics_have_bounded_attributes(self):
        meter = RecordingMeter()
        telemetry = ApplicationTelemetry(meter=meter)

        telemetry.record_amap_call(
            0.2,
            operation="geocode",
            outcome="failed",
            error_type="TimeoutError",
        )
        telemetry.record_readiness("mongodb", ready=True, duration=0.01)
        telemetry.record_readiness("redis", ready=False, duration=0.02)

        attributes = meter.instruments[
            "smartserve.amap.call.count"
        ].calls[0][1]
        self.assertEqual(
            attributes,
            {
                "action": "geocode",
                "outcome": "failed",
                "error.type": "TimeoutError",
            },
        )
        self.assertEqual(
            meter.instruments["smartserve.readiness.mongodb"].calls[0][0],
            1,
        )
        self.assertEqual(
            meter.instruments["smartserve.readiness.redis"].calls[0][0],
            0,
        )


if __name__ == "__main__":
    unittest.main()
