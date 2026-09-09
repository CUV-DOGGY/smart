from __future__ import annotations

from time import perf_counter
from typing import Any, Mapping, Sequence

from opentelemetry import metrics, trace
from opentelemetry.trace import Link, Span, Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import (
    TraceContextTextMapPropagator,
)


INSTRUMENTATION_NAME = "smartserve.agent"
ALLOWED_METRIC_ATTRIBUTE_KEYS = frozenset(
    {"outcome", "tool.name", "action", "model", "error.type"}
)


class AgentTelemetry:
    """Low-cardinality Agent metrics and tracing helpers.

    Identifiers such as request, user, conversation and command IDs belong on
    spans, never metric attributes. Keeping metric construction here makes that
    boundary explicit and testable.
    """

    def __init__(self, *, tracer=None, meter=None) -> None:
        self.tracer = tracer or trace.get_tracer(INSTRUMENTATION_NAME)
        self.meter = meter or metrics.get_meter(INSTRUMENTATION_NAME)
        self.agent_run_count = self.meter.create_counter(
            "smartserve.agent.run.count",
            unit="{run}",
            description="Completed SmartServe Agent runs",
        )
        self.agent_run_duration = self.meter.create_histogram(
            "smartserve.agent.run.duration",
            unit="s",
            description="SmartServe Agent run duration",
        )
        self.first_token_duration = self.meter.create_histogram(
            "smartserve.agent.first_token.duration",
            unit="s",
            description="Time from Agent run start to the first streamed token",
        )
        self.tool_call_count = self.meter.create_counter(
            "smartserve.agent.tool.call.count",
            unit="{call}",
            description="SmartServe Agent tool calls",
        )
        self.tool_call_duration = self.meter.create_histogram(
            "smartserve.agent.tool.call.duration",
            unit="s",
            description="SmartServe Agent tool call duration",
        )
        self.confirmation_count = self.meter.create_counter(
            "smartserve.agent.confirmation.count",
            unit="{confirmation}",
            description="SmartServe Agent confirmation lifecycle events",
        )
        self.write_command_count = self.meter.create_counter(
            "smartserve.write_command.count",
            unit="{command}",
            description="SmartServe write command execution attempts",
        )
        self.sse_connections = self.meter.create_up_down_counter(
            "smartserve.sse.connections",
            unit="{connection}",
            description="Active SmartServe Agent SSE streams",
        )
        self.llm_call_count = self.meter.create_counter(
            "smartserve.llm.call.count",
            unit="{call}",
            description="SmartServe LLM calls",
        )
        self.llm_call_duration = self.meter.create_histogram(
            "smartserve.llm.call.duration",
            unit="s",
            description="SmartServe LLM call duration",
        )
        self.llm_token_count = self.meter.create_counter(
            "smartserve.llm.token.count",
            unit="{token}",
            description="SmartServe LLM input and output tokens",
        )
        self.write_command_recovery_count = self.meter.create_counter(
            "smartserve.write_command.recovery.count",
            unit="{command}",
            description="SmartServe write command recovery attempts",
        )
        self.write_command_overdue = self.meter.create_gauge(
            "smartserve.write_command.overdue",
            unit="{command}",
            description="Write commands observed beyond their execution lease",
        )

    @staticmethod
    def now() -> float:
        return perf_counter()

    @staticmethod
    def elapsed(started_at: float) -> float:
        return max(0.0, perf_counter() - started_at)

    def start_span(
        self,
        name: str,
        *,
        attributes: Mapping[str, Any] | None = None,
        links: Sequence[Link] | None = None,
    ):
        return self.tracer.start_as_current_span(
            name,
            attributes=dict(attributes or {}),
            links=tuple(links or ()),
        )

    @staticmethod
    def record_exception(span: Span, exc: BaseException) -> None:
        if not span.is_recording():
            return
        error_type = type(exc).__name__
        span.record_exception(exc)
        span.set_attribute("error.type", error_type)
        span.set_status(Status(StatusCode.ERROR, error_type))

    @staticmethod
    def set_outcome(
        span: Span,
        outcome: str,
        *,
        error_type: str | None = None,
    ) -> None:
        if not span.is_recording():
            return
        span.set_attribute("agent.outcome", outcome)
        if error_type:
            span.set_attribute("error.type", error_type)

    def record_agent_run(
        self,
        duration: float,
        *,
        outcome: str,
        model: str,
        error_type: str | None = None,
    ) -> None:
        attributes = self._metric_attributes(
            outcome=outcome,
            model=model,
            error_type=error_type,
        )
        self.agent_run_count.add(1, attributes)
        self.agent_run_duration.record(duration, attributes)

    def record_first_token(self, duration: float, *, model: str) -> None:
        self.first_token_duration.record(
            duration,
            self._metric_attributes(model=model),
        )

    def record_tool_call(
        self,
        duration: float,
        *,
        tool_name: str,
        outcome: str,
        error_type: str | None = None,
    ) -> None:
        attributes = self._metric_attributes(
            outcome=outcome,
            tool_name=tool_name,
            error_type=error_type,
        )
        self.tool_call_count.add(1, attributes)
        self.tool_call_duration.record(duration, attributes)

    def record_confirmation(
        self,
        *,
        action: str,
        outcome: str,
        error_type: str | None = None,
    ) -> None:
        self.confirmation_count.add(
            1,
            self._metric_attributes(
                action=action,
                outcome=outcome,
                error_type=error_type,
            ),
        )

    def record_write_command(
        self,
        *,
        action: str,
        outcome: str,
        error_type: str | None = None,
    ) -> None:
        self.write_command_count.add(
            1,
            self._metric_attributes(
                action=action,
                outcome=outcome,
                error_type=error_type,
            ),
        )

    def change_sse_connections(self, amount: int, *, model: str) -> None:
        self.sse_connections.add(
            amount,
            self._metric_attributes(model=model),
        )

    def record_llm_call(
        self,
        duration: float,
        *,
        model: str,
        outcome: str,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        error_type: str | None = None,
    ) -> None:
        attributes = self._metric_attributes(
            model=model,
            outcome=outcome,
            error_type=error_type,
        )
        self.llm_call_count.add(1, attributes)
        self.llm_call_duration.record(duration, attributes)
        for action, value in (
            ("input", input_tokens),
            ("output", output_tokens),
        ):
            if (
                isinstance(value, int)
                and not isinstance(value, bool)
                and value >= 0
            ):
                self.llm_token_count.add(
                    value,
                    self._metric_attributes(model=model, action=action),
                )

    def record_write_command_recovery(
        self,
        *,
        action: str,
        outcome: str,
        error_type: str | None = None,
    ) -> None:
        self.write_command_recovery_count.add(
            1,
            self._metric_attributes(
                action=action,
                outcome=outcome,
                error_type=error_type,
            ),
        )

    def record_write_command_overdue(self, count: int) -> None:
        self.write_command_overdue.set(max(0, count))

    @staticmethod
    def _metric_attributes(
        *,
        outcome: str | None = None,
        tool_name: str | None = None,
        action: str | None = None,
        model: str | None = None,
        error_type: str | None = None,
    ) -> dict[str, str]:
        attributes = {
            "outcome": outcome,
            "tool.name": tool_name,
            "action": action,
            "model": model,
            "error.type": error_type,
        }
        return {
            key: value
            for key, value in attributes.items()
            if key in ALLOWED_METRIC_ATTRIBUTE_KEYS and value
        }


_trace_context_propagator = TraceContextTextMapPropagator()


def capture_trace_context() -> dict[str, str] | None:
    """Capture only W3C trace context; baggage is deliberately excluded."""
    carrier: dict[str, str] = {}
    _trace_context_propagator.inject(carrier)
    return carrier or None


def links_from_trace_context(
    carrier: object,
) -> tuple[Link, ...]:
    if not isinstance(carrier, dict):
        return ()
    sanitized = {
        key: value
        for key, value in carrier.items()
        if key in {"traceparent", "tracestate"}
        and isinstance(value, str)
        and len(value) <= 512
    }
    if "traceparent" not in sanitized:
        return ()
    extracted = _trace_context_propagator.extract(sanitized)
    linked_context = trace.get_current_span(extracted).get_span_context()
    if not linked_context.is_valid:
        return ()
    current_context = trace.get_current_span().get_span_context()
    if current_context.is_valid and current_context.trace_id == linked_context.trace_id:
        return ()
    return (Link(linked_context),)


telemetry = AgentTelemetry()
