import asyncio
import json
import logging
import sys
import unittest

from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import (
    InMemoryLogRecordExporter,
    SimpleLogRecordProcessor,
)
from opentelemetry.sdk.trace import TracerProvider

from app.config import settings
from app.core.logger import (
    CONSOLE_HANDLER_KIND,
    HANDLER_KIND_ATTRIBUTE,
    JsonLogFormatter,
    SensitiveQueryParameterFilter,
    attach_otel_log_handler,
    detach_otel_log_handler,
    setup_logging,
)
from app.core.middleware import RequestIdMiddleware
from app.observability.context import (
    bind_request_id,
    bind_run_id,
    current_request_id,
    reset_request_id,
    reset_run_id,
)


def make_record(message, *, exc_info=None):
    return logging.LogRecord(
        name="smartserve.test",
        level=logging.ERROR if exc_info else logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=exc_info,
    )


class StructuredLoggingTests(unittest.TestCase):
    def test_json_log_contains_trace_and_request_context_on_one_line(self):
        provider = TracerProvider()
        tracer = provider.get_tracer("structured-log-test")
        request_token = bind_request_id("request-123")
        run_token = bind_run_id("run-123")
        try:
            with tracer.start_as_current_span("request") as span:
                span_context = span.get_span_context()
                record = make_record("line one\nline two")
                SensitiveQueryParameterFilter().filter(record)
                rendered = JsonLogFormatter().format(record)
        finally:
            reset_run_id(run_token)
            reset_request_id(request_token)

        payload = json.loads(rendered)
        self.assertNotIn("\n", rendered)
        self.assertEqual(payload["service.name"], settings.OTEL_SERVICE_NAME)
        self.assertEqual(payload["environment"], settings.OTEL_ENVIRONMENT)
        self.assertEqual(payload["request_id"], "request-123")
        self.assertEqual(payload["run_id"], "run-123")
        self.assertEqual(
            payload["trace_id"],
            format(span_context.trace_id, "032x"),
        )
        self.assertEqual(
            payload["span_id"],
            format(span_context.span_id, "016x"),
        )

    def test_credentials_pii_and_exception_stack_are_redacted(self):
        try:
            raise RuntimeError(
                "password=super-secret phone=13800138000"
            )
        except RuntimeError:
            exc_info = sys.exc_info()
        record = make_record(
            "Authorization: Bearer bearer-secret "
            "mongodb://user:db-secret@localhost/db "
            "https://example.test/path?address=private-address&key=api-secret",
            exc_info=exc_info,
        )

        SensitiveQueryParameterFilter().filter(record)
        rendered = JsonLogFormatter().format(record)

        self.assertIsNone(record.exc_info)
        for secret in (
            "bearer-secret",
            "db-secret",
            "private-address",
            "api-secret",
            "super-secret",
            "13800138000",
        ):
            self.assertNotIn(secret, rendered)
        payload = json.loads(rendered)
        self.assertEqual(payload["exception.type"], "RuntimeError")
        self.assertIn("password=***", payload["exception.message"])
        self.assertIn("1**********", payload["exception.message"])

    def test_setup_logging_is_idempotent_for_uvicorn_reload(self):
        first = setup_logging()
        second = setup_logging()

        self.assertIs(first, second)
        console_handlers = [
            handler
            for handler in first.handlers
            if getattr(handler, HANDLER_KIND_ATTRIBUTE, None)
            == CONSOLE_HANDLER_KIND
        ]
        self.assertEqual(len(console_handlers), 1)
        for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            named_logger = logging.getLogger(logger_name)
            self.assertEqual(named_logger.handlers, [])
            self.assertTrue(named_logger.propagate)

    def test_otel_handler_exports_json_and_context_attributes(self):
        provider = LoggerProvider()
        exporter = InMemoryLogRecordExporter()
        provider.add_log_record_processor(SimpleLogRecordProcessor(exporter))
        handler = attach_otel_log_handler(provider)
        try:
            self.assertIs(handler, attach_otel_log_handler(provider))
            request_token = bind_request_id("request-otel")
            run_token = bind_run_id("run-otel")
            tracer_provider = TracerProvider()
            tracer = tracer_provider.get_tracer("otel-log-test")
            try:
                with tracer.start_as_current_span("request") as span:
                    span_context = span.get_span_context()
                    handler.handle(make_record("exported message"))
            finally:
                reset_run_id(run_token)
                reset_request_id(request_token)

            finished = exporter.get_finished_logs()
            self.assertEqual(len(finished), 1)
            log_record = finished[0].log_record
            payload = json.loads(log_record.body)
            self.assertEqual(payload["request_id"], "request-otel")
            self.assertEqual(payload["run_id"], "run-otel")
            self.assertEqual(log_record.trace_id, span_context.trace_id)
            self.assertEqual(log_record.span_id, span_context.span_id)
            self.assertEqual(
                log_record.attributes["app.request_id"],
                "request-otel",
            )
            self.assertEqual(log_record.attributes["app.run_id"], "run-otel")
        finally:
            detach_otel_log_handler(handler)
            provider.shutdown()


class RequestIdContextIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_overlapping_requests_keep_separate_context_and_reset(self):
        first_entered = asyncio.Event()
        release_first = asyncio.Event()
        observed = {}

        async def downstream(scope, receive, send):
            path = scope["path"]
            before = current_request_id()
            if path == "/first":
                first_entered.set()
                await release_first.wait()
            else:
                await first_entered.wait()
                release_first.set()
            after = current_request_id()
            observed[path] = (before, after)
            await send({"type": "http.response.start", "status": 204})
            await send({"type": "http.response.body", "body": b""})

        middleware = RequestIdMiddleware(downstream)

        async def call(path, request_id):
            sent = []

            async def receive():
                return {"type": "http.request", "body": b""}

            async def send(message):
                sent.append(message)

            await middleware(
                {
                    "type": "http",
                    "path": path,
                    "headers": [
                        (b"x-request-id", request_id.encode("ascii"))
                    ],
                },
                receive,
                send,
            )
            return current_request_id(), sent

        first, second = await asyncio.gather(
            call("/first", "request-first"),
            call("/second", "request-second"),
        )

        self.assertEqual(
            observed,
            {
                "/first": ("request-first", "request-first"),
                "/second": ("request-second", "request-second"),
            },
        )
        self.assertIsNone(first[0])
        self.assertIsNone(second[0])
        self.assertIsNone(current_request_id())


if __name__ == "__main__":
    unittest.main()
