from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from fastapi import FastAPI

from app.config import settings


logger = logging.getLogger(__name__)
REDACTED_OUTBOUND_URL = "about:blank"


@dataclass(slots=True)
class ObservabilityRuntime:
    enabled: bool
    tracer_provider: Any = None
    meter_provider: Any = None
    logger_provider: Any = None
    log_handler: Any = None
    is_shutdown: bool = False

    def shutdown(self) -> None:
        if not self.enabled or self.is_shutdown:
            return
        self.is_shutdown = True
        if self.log_handler is not None:
            from app.core.logger import detach_otel_log_handler

            detach_otel_log_handler(self.log_handler)
        if self.logger_provider is not None:
            try:
                self.logger_provider.shutdown()
            except Exception:
                logger.exception("OpenTelemetry logger provider shutdown failed")
        if self.meter_provider is not None:
            try:
                self.meter_provider.shutdown()
            except Exception:
                logger.exception("OpenTelemetry meter provider shutdown failed")
        if self.tracer_provider is not None:
            try:
                self.tracer_provider.shutdown()
            except Exception:
                logger.exception("OpenTelemetry tracer provider shutdown failed")


def _signal_endpoint(base_endpoint: str, signal: str) -> str:
    return f"{base_endpoint.rstrip('/')}/v1/{signal}"


def _safe_outbound_url(url: object) -> str:
    """Keep an outbound URL useful for tracing without query secrets or PII."""
    value = str(url)
    try:
        parsed = urlsplit(value)
    except ValueError:
        return REDACTED_OUTBOUND_URL
    if not parsed.scheme or not parsed.hostname:
        return REDACTED_OUTBOUND_URL
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    try:
        port = parsed.port
    except ValueError:
        return REDACTED_OUTBOUND_URL
    authority = host if port is None else f"{host}:{port}"
    return urlunsplit((parsed.scheme, authority, parsed.path, "", ""))


def _sanitize_httpx_span_url(span, request_info) -> None:
    """Override HTTPX URL attributes after its default attributes are set."""
    if span is None or not span.is_recording():
        return
    safe_url = _safe_outbound_url(request_info.url)
    # Set both names because OpenTelemetry can emit either one while HTTP
    # semantic conventions transition from the legacy to the stable schema.
    span.set_attribute("url.full", safe_url)
    span.set_attribute("http.url", safe_url)


async def _sanitize_async_httpx_span_url(span, request_info) -> None:
    _sanitize_httpx_span_url(span, request_info)


def setup_observability(app: FastAPI) -> ObservabilityRuntime:
    existing = getattr(app.state, "observability", None)
    if existing is not None:
        return existing

    if not settings.OBSERVABILITY_ENABLED:
        runtime = ObservabilityRuntime(enabled=False)
        app.state.observability = runtime
        return runtime

    from opentelemetry import metrics, trace
    from opentelemetry._logs import set_logger_provider
    from opentelemetry.exporter.otlp.proto.http._log_exporter import (
        OTLPLogExporter,
    )
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
        OTLPMetricExporter,
    )
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
        OTLPSpanExporter,
    )
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.logging import LoggingInstrumentor
    from opentelemetry.instrumentation.pymongo import PymongoInstrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.view import (
        ExplicitBucketHistogramAggregation,
        View,
    )
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk._logs import LoggerProvider
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

    resource = Resource.create(
        {
            "service.name": settings.OTEL_SERVICE_NAME,
            "service.version": "0.1.0",
            "deployment.environment.name": settings.OTEL_ENVIRONMENT,
        }
    )
    tracer_provider = TracerProvider(
        resource=resource,
        sampler=ParentBased(
            TraceIdRatioBased(settings.OTEL_TRACE_SAMPLE_RATIO)
        ),
    )
    tracer_provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint=_signal_endpoint(
                    settings.OTEL_EXPORTER_OTLP_ENDPOINT,
                    "traces",
                )
            )
        )
    )

    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(
            endpoint=_signal_endpoint(
                settings.OTEL_EXPORTER_OTLP_ENDPOINT,
                "metrics",
            )
        ),
        export_interval_millis=settings.OTEL_METRIC_EXPORT_INTERVAL,
    )
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[metric_reader],
        views=[
            View(
                instrument_name="smartserve.agent.run.duration",
                aggregation=ExplicitBucketHistogramAggregation(
                    boundaries=[
                        0.1,
                        0.25,
                        0.5,
                        1,
                        2,
                        5,
                        10,
                        15,
                        30,
                        45,
                        60,
                        90,
                        120,
                    ]
                ),
            ),
            View(
                instrument_name="smartserve.agent.first_token.duration",
                aggregation=ExplicitBucketHistogramAggregation(
                    boundaries=[
                        0.05,
                        0.1,
                        0.25,
                        0.5,
                        1,
                        2,
                        3,
                        5,
                        10,
                        15,
                        30,
                    ]
                ),
            ),
            View(
                instrument_name="smartserve.agent.tool.call.duration",
                aggregation=ExplicitBucketHistogramAggregation(
                    boundaries=[
                        0.01,
                        0.025,
                        0.05,
                        0.1,
                        0.25,
                        0.5,
                        1,
                        2,
                        5,
                        10,
                        30,
                    ]
                ),
            ),
            View(
                instrument_name="smartserve.llm.call.duration",
                aggregation=ExplicitBucketHistogramAggregation(
                    boundaries=[
                        0.1,
                        0.25,
                        0.5,
                        1,
                        2,
                        5,
                        10,
                        15,
                        30,
                        45,
                        60,
                        90,
                    ]
                ),
            ),
            View(
                instrument_name="smartserve.amap.call.duration",
                aggregation=ExplicitBucketHistogramAggregation(
                    boundaries=[
                        0.01,
                        0.025,
                        0.05,
                        0.1,
                        0.25,
                        0.5,
                        1,
                        2,
                        3,
                        5,
                        10,
                    ]
                ),
            ),
        ],
    )
    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(
            OTLPLogExporter(
                endpoint=_signal_endpoint(
                    settings.OTEL_EXPORTER_OTLP_ENDPOINT,
                    "logs",
                )
            )
        )
    )

    trace.set_tracer_provider(tracer_provider)
    metrics.set_meter_provider(meter_provider)
    set_logger_provider(logger_provider)

    # Instrument clients before lifespan creates their instances. Header/body
    # capture is intentionally left disabled; Mongo statements stay disabled.
    HTTPXClientInstrumentor().instrument(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        request_hook=_sanitize_httpx_span_url,
        async_request_hook=_sanitize_async_httpx_span_url,
    )
    PymongoInstrumentor().instrument(
        tracer_provider=tracer_provider,
        capture_statement=False,
    )
    RedisInstrumentor().instrument(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
    )
    LoggingInstrumentor().instrument(
        tracer_provider=tracer_provider,
        set_logging_format=False,
    )
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        excluded_urls=r"/health/live$",
        exclude_spans=["receive", "send"],
    )
    from app.core.logger import attach_otel_log_handler

    log_handler = attach_otel_log_handler(logger_provider)

    runtime = ObservabilityRuntime(
        enabled=True,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        logger_provider=logger_provider,
        log_handler=log_handler,
    )
    app.state.observability = runtime
    logger.info(
        "OpenTelemetry enabled service=%s environment=%s endpoint=%s",
        settings.OTEL_SERVICE_NAME,
        settings.OTEL_ENVIRONMENT,
        settings.OTEL_EXPORTER_OTLP_ENDPOINT,
    )
    return runtime


def shutdown_observability(app: FastAPI) -> None:
    runtime = getattr(app.state, "observability", None)
    if runtime is not None:
        runtime.shutdown()
