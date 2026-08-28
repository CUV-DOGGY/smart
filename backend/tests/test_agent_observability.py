import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

from app.observability import agent as agent_observability
from app.observability.agent import (
    ALLOWED_METRIC_ATTRIBUTE_KEYS,
    AgentTelemetry,
    capture_trace_context,
    links_from_trace_context,
)
from app.services.chat_service import AgentChatService


class RecordingInstrument:
    def __init__(self):
        self.calls = []

    def add(self, value, attributes=None):
        self.calls.append(("add", value, attributes or {}))

    def record(self, value, attributes=None):
        self.calls.append(("record", value, attributes or {}))

    def set(self, value, attributes=None):
        self.calls.append(("set", value, attributes or {}))


class RecordingMeter:
    def __init__(self):
        self.instruments = {}

    def _create(self, name, **_kwargs):
        instrument = RecordingInstrument()
        self.instruments[name] = instrument
        return instrument

    create_counter = _create
    create_histogram = _create
    create_up_down_counter = _create
    create_gauge = _create


class AgentMetricContractTests(unittest.TestCase):
    def test_all_agent_metrics_use_only_low_cardinality_attributes(self):
        meter = RecordingMeter()
        telemetry = AgentTelemetry(
            tracer=trace.get_tracer("agent-metric-test"),
            meter=meter,
        )

        telemetry.record_agent_run(
            1.2,
            outcome="completed",
            model="test-model",
        )
        telemetry.record_first_token(0.2, model="test-model")
        telemetry.record_tool_call(
            0.4,
            tool_name="list_orders",
            outcome="succeeded",
        )
        telemetry.record_confirmation(
            action="cancel_order",
            outcome="approve",
        )
        telemetry.record_write_command(
            action="cancel_order",
            outcome="succeeded",
        )
        telemetry.change_sse_connections(1, model="test-model")
        telemetry.change_sse_connections(-1, model="test-model")
        telemetry.record_llm_call(
            0.8,
            model="test-model",
            outcome="succeeded",
            input_tokens=12,
            output_tokens=4,
        )
        telemetry.record_write_command_recovery(
            action="cancel_order",
            outcome="succeeded",
        )
        telemetry.record_write_command_overdue(2)

        self.assertEqual(
            set(meter.instruments),
            {
                "smartserve.agent.run.count",
                "smartserve.agent.run.duration",
                "smartserve.agent.first_token.duration",
                "smartserve.agent.tool.call.count",
                "smartserve.agent.tool.call.duration",
                "smartserve.agent.confirmation.count",
                "smartserve.write_command.count",
                "smartserve.sse.connections",
                "smartserve.llm.call.count",
                "smartserve.llm.call.duration",
                "smartserve.llm.token.count",
                "smartserve.write_command.recovery.count",
                "smartserve.write_command.overdue",
            },
        )
        for instrument in meter.instruments.values():
            for _, _, attributes in instrument.calls:
                self.assertLessEqual(
                    set(attributes),
                    ALLOWED_METRIC_ATTRIBUTE_KEYS,
                )
                self.assertTrue(
                    {"request_id", "user_id", "conversation_id", "command_id"}
                    .isdisjoint(attributes)
                )


class TraceContextLinkTests(unittest.TestCase):
    def test_capture_uses_only_w3c_trace_context_and_can_create_a_link(self):
        provider = TracerProvider()
        tracer = provider.get_tracer("trace-link-test")
        with tracer.start_as_current_span("origin") as origin:
            origin_context = origin.get_span_context()
            carrier = capture_trace_context()

        self.assertIsNotNone(carrier)
        self.assertIn("traceparent", carrier)
        self.assertLessEqual(set(carrier), {"traceparent", "tracestate"})
        links = links_from_trace_context(carrier)
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].context.trace_id, origin_context.trace_id)

    def test_invalid_or_oversized_context_is_ignored(self):
        self.assertEqual(links_from_trace_context(None), ())
        self.assertEqual(links_from_trace_context({"traceparent": "invalid"}), ())
        self.assertEqual(
            links_from_trace_context({"traceparent": "x" * 513}),
            (),
        )


class AgentStreamMetricTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_records_one_first_token_and_balances_connections(self):
        meter = RecordingMeter()
        recording_telemetry = AgentTelemetry(
            tracer=trace.get_tracer("agent-stream-test"),
            meter=meter,
        )
        repository = MagicMock()
        repository.append_message = AsyncMock(return_value="message-001")
        service = AgentChatService(
            repository,
            MagicMock(),
            MagicMock(),
            MagicMock(),
            MagicMock(),
            MagicMock(),
            timeout_seconds=5,
        )

        async def source():
            yield {"type": "token", "delta": "你"}
            yield {"type": "token", "delta": "好"}

        with patch.object(
            agent_observability,
            "telemetry",
            recording_telemetry,
        ):
            events = [
                event
                async for event in service._persisted_stream(
                    source(),
                    user_id="user-001",
                    conversation_id="conversation-001",
                    is_disconnected=AsyncMock(return_value=False),
                )
            ]

        self.assertEqual(events[-1]["type"], "done")
        first_token_calls = meter.instruments[
            "smartserve.agent.first_token.duration"
        ].calls
        self.assertEqual(len(first_token_calls), 1)
        connection_calls = meter.instruments[
            "smartserve.sse.connections"
        ].calls
        self.assertEqual([call[1] for call in connection_calls], [1, -1])
        run_count_calls = meter.instruments[
            "smartserve.agent.run.count"
        ].calls
        self.assertEqual(len(run_count_calls), 1)
        self.assertEqual(run_count_calls[0][2]["outcome"], "completed")
        repository.append_message.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
