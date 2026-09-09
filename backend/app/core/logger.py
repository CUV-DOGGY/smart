from __future__ import annotations

import json
import logging
import re
import traceback
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.observability.context import (
    current_request_id,
    current_run_id,
    current_span_id,
    current_trace_id,
)


CONSOLE_HANDLER_KIND = "smartserve-json-console"
OTLP_HANDLER_KIND = "smartserve-otlp"
HANDLER_KIND_ATTRIBUTE = "_smartserve_handler_kind"


class SensitiveQueryParameterFilter(logging.Filter):
    """Redact credentials and common customer PII from every log handler."""

    _query_parameter_pattern = re.compile(
        r"([?&](?:"
        r"key|sig|token|access_token|api_key|secret|password|authorization|"
        r"address|city|phone|mobile"
        r")=)[^&\s\"']+",
        flags=re.IGNORECASE,
    )
    _key_value_pattern = re.compile(
        r"((?:\"|')?(?:"
        r"api[_-]?key|access[_-]?token|token|password|secret|authorization"
        r")(?:\"|')?\s*[:=]\s*(?:\"|')?)([^,}\s\"'&]+)",
        flags=re.IGNORECASE,
    )
    _quoted_key_value_pattern = re.compile(
        r"((?:\"|')?(?:"
        r"api[_-]?key|access[_-]?token|token|password|secret|authorization"
        r")(?:\"|')?\s*[:=]\s*)(?P<quote>[\"'])(.*?)(?P=quote)",
        flags=re.IGNORECASE,
    )
    _authorization_header_pattern = re.compile(
        r"(\bAuthorization\s*[:=]\s*)"
        r"(?:(?:Bearer|Basic)\s+)?[^\s,}\"]+",
        flags=re.IGNORECASE,
    )
    _bearer_pattern = re.compile(
        r"(\bBearer\s+)[A-Za-z0-9._~+/=-]+",
        flags=re.IGNORECASE,
    )
    _jwt_pattern = re.compile(
        r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"
    )
    _credential_url_pattern = re.compile(
        r"\b((?:mongodb(?:\+srv)?|redis|rediss)://)[^@/\s]+@",
        flags=re.IGNORECASE,
    )
    _mobile_phone_pattern = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")

    @classmethod
    def sanitize(cls, value: object) -> str:
        text = str(value)
        text = cls._credential_url_pattern.sub(r"\1***:***@", text)
        text = cls._query_parameter_pattern.sub(r"\1***", text)
        text = cls._authorization_header_pattern.sub(r"\1***", text)
        text = cls._bearer_pattern.sub(r"\1***", text)
        text = cls._jwt_pattern.sub("***", text)
        text = cls._quoted_key_value_pattern.sub(
            lambda match: (
                f"{match.group(1)}{match.group('quote')}***"
                f"{match.group('quote')}"
            ),
            text,
        )
        text = cls._key_value_pattern.sub(r"\1***", text)
        return cls._mobile_phone_pattern.sub("1**********", text)

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        record.msg = self.sanitize(message)
        record.args = ()
        self._sanitize_exception(record)
        self._enrich_context(record)
        return True

    @classmethod
    def _sanitize_exception(cls, record: logging.LogRecord) -> None:
        if record.exc_info and "exception.stacktrace" not in record.__dict__:
            exception_type, exception, _ = record.exc_info
            record.__dict__["exception.type"] = (
                exception_type.__name__ if exception_type else "Exception"
            )
            record.__dict__["exception.message"] = cls.sanitize(exception)
            record.__dict__["exception.stacktrace"] = cls.sanitize(
                "".join(traceback.format_exception(*record.exc_info))
            )
            # Prevent downstream handlers from re-exporting the raw exception.
            record.exc_info = None
            record.exc_text = None
        elif record.exc_text:
            record.exc_text = cls.sanitize(record.exc_text)

    @staticmethod
    def _enrich_context(record: logging.LogRecord) -> None:
        trace_id = current_trace_id()
        span_id = current_span_id()
        request_id = current_request_id()
        run_id = current_run_id()
        if trace_id:
            record.trace_id = trace_id
        if span_id:
            record.span_id = span_id
        if request_id:
            record.request_id = request_id
            record.__dict__["app.request_id"] = request_id
        if run_id:
            record.run_id = run_id
            record.__dict__["app.run_id"] = run_id
        record.__dict__["service.name"] = settings.OTEL_SERVICE_NAME
        record.__dict__["deployment.environment.name"] = (
            settings.OTEL_ENVIRONMENT
        )


class JsonLogFormatter(logging.Formatter):
    """Render one physical JSON line suitable for console and Loki parsing."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created,
                tz=timezone.utc,
            ).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "severity": record.levelname,
            "logger": record.name,
            "message": SensitiveQueryParameterFilter.sanitize(
                record.getMessage()
            ),
            "service.name": record.__dict__.get(
                "service.name",
                settings.OTEL_SERVICE_NAME,
            ),
            "environment": record.__dict__.get(
                "deployment.environment.name",
                settings.OTEL_ENVIRONMENT,
            ),
            "trace_id": getattr(record, "trace_id", None),
            "span_id": getattr(record, "span_id", None),
            "request_id": getattr(record, "request_id", None),
            "run_id": getattr(record, "run_id", None),
            "code.filepath": record.pathname,
            "code.function": record.funcName,
            "code.lineno": record.lineno,
        }
        for key in (
            "exception.type",
            "exception.message",
            "exception.stacktrace",
        ):
            if key in record.__dict__:
                payload[key] = SensitiveQueryParameterFilter.sanitize(
                    record.__dict__[key]
                )
        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )


class ExcludeTelemetryInternalLogsFilter(logging.Filter):
    """Avoid recursively exporting telemetry pipeline failures as OTLP logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not record.name.startswith("opentelemetry.")


def _find_handler(kind: str) -> logging.Handler | None:
    root_logger = logging.getLogger()
    return next(
        (
            handler
            for handler in root_logger.handlers
            if getattr(handler, HANDLER_KIND_ATTRIBUTE, None) == kind
        ),
        None,
    )


def _configure_handler(
    handler: logging.Handler,
    *,
    kind: str,
) -> logging.Handler:
    setattr(handler, HANDLER_KIND_ATTRIBUTE, kind)
    handler.setLevel(logging.INFO)
    handler.setFormatter(JsonLogFormatter())
    if not any(
        isinstance(item, SensitiveQueryParameterFilter)
        for item in handler.filters
    ):
        handler.addFilter(SensitiveQueryParameterFilter())
    return handler


def setup_logging() -> logging.Logger:
    """Configure application and Uvicorn logging without duplicate handlers."""
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    console_handler = _find_handler(CONSOLE_HANDLER_KIND)
    if console_handler is None:
        console_handler = logging.StreamHandler()
        root_logger.addHandler(console_handler)
    _configure_handler(console_handler, kind=CONSOLE_HANDLER_KIND)

    # Uvicorn installs its own handlers before importing the application. Route
    # them through the same root JSON handler so reloads do not duplicate lines.
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(logger_name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
    return root_logger


def attach_otel_log_handler(logger_provider) -> logging.Handler:
    from opentelemetry.instrumentation.logging.handler import LoggingHandler

    existing = _find_handler(OTLP_HANDLER_KIND)
    if existing is not None:
        return existing
    handler = LoggingHandler(
        level=logging.INFO,
        logger_provider=logger_provider,
    )
    _configure_handler(handler, kind=OTLP_HANDLER_KIND)
    handler.addFilter(ExcludeTelemetryInternalLogsFilter())
    logging.getLogger().addHandler(handler)
    return handler


def detach_otel_log_handler(handler: logging.Handler | None) -> None:
    if handler is None:
        return
    logging.getLogger().removeHandler(handler)
    handler.close()


Logger = setup_logging()
Handler = _find_handler(CONSOLE_HANDLER_KIND)
Formatter = Handler.formatter if Handler is not None else JsonLogFormatter()
