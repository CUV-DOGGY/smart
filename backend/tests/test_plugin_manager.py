import logging
import unittest

from app.core.lifespan import shutdown_plugins, startup_plugins
from app.plugins import (
    PluginContext,
    PluginManager,
    PluginToolRegistry,
)


class RecordingPlugin:
    def __init__(self, name: str, events: list[str]) -> None:
        self.name = name
        self.events = events

    async def start(self, context: PluginContext) -> None:
        self.events.append(f"start:{self.name}")

    async def stop(self) -> None:
        self.events.append(f"stop:{self.name}")


class PluginManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_starts_in_order_and_stops_in_reverse_order(self) -> None:
        events: list[str] = []
        manager = PluginManager(
            [
                RecordingPlugin("first", events),
                RecordingPlugin("second", events),
            ]
        )
        context = PluginContext(
            logger=logging.getLogger("test.plugins"),
            tools=PluginToolRegistry(),
        )

        await manager.start(context)
        await manager.stop()

        self.assertEqual(
            events,
            [
                "start:first",
                "start:second",
                "stop:second",
                "stop:first",
            ],
        )

    async def test_application_helpers_start_and_stop_business_hours_plugin(
        self,
    ) -> None:
        with self.assertLogs(
            "app.core.lifespan",
            level="INFO",
        ) as captured:
            manager, tools = await startup_plugins()

            self.assertTrue(tools.has("get_customer_service_hours"))

            await shutdown_plugins(manager)

            self.assertFalse(tools.has("get_customer_service_hours"))

        output = "\n".join(captured.output)

        self.assertIn(
            "插件已启动 plugin=business_hours",
            output,
        )
        self.assertIn(
            "插件已停止 plugin=business_hours",
            output,
        )

    async def test_business_hours_tool_can_be_executed_by_name(
        self,
    ) -> None:
        manager, tools = await startup_plugins()

        try:
            result = await tools.execute(
                "get_customer_service_hours",
                {},
            )
        finally:
            await shutdown_plugins(manager)

        self.assertEqual(
            {
                key: result[key]
                for key in ("timezone", "weekdays", "open_time", "close_time")
            },
            {
                "timezone": "Asia/Shanghai",
                "weekdays": "周一至周五",
                "open_time": "09:00",
                "close_time": "18:00",
            },
        )
        self.assertIsInstance(result["is_open"], bool)
        self.assertIn("evaluated_at", result)


if __name__ == "__main__":
    unittest.main()
