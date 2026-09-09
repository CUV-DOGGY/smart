from __future__ import annotations

from contextvars import ContextVar, Token

from opentelemetry import trace


_request_id: ContextVar[str | None] = ContextVar(
    "observability_request_id",
    default=None,
)
_run_id: ContextVar[str | None] = ContextVar(
    "observability_run_id",
    default=None,
)


def bind_request_id(request_id: str) -> Token[str | None]:
    return _request_id.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    _request_id.reset(token)


def current_request_id() -> str | None:
    return _request_id.get()


def bind_run_id(run_id: str) -> Token[str | None]:
    return _run_id.set(run_id)


def reset_run_id(token: Token[str | None]) -> None:
    _run_id.reset(token)


def current_run_id() -> str | None:
    return _run_id.get()


def current_trace_id() -> str | None:
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return None
    return format(span_context.trace_id, "032x")


def current_span_id() -> str | None:
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return None
    return format(span_context.span_id, "016x")


def set_current_span_request_id(request_id: str) -> None:
    span = trace.get_current_span()
    if span.is_recording():
        span.set_attribute("app.request_id", request_id)


def set_current_span_run_id(run_id: str) -> None:
    span = trace.get_current_span()
    if span.is_recording():
        span.set_attribute("app.run_id", run_id)
