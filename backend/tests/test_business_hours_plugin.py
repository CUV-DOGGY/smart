from datetime import datetime, time, timezone
import logging
import unittest

from pydantic import ValidationError

from app.plugins import (
    PluginContext,
    PluginToolRegistry,
    ToolArgumentsValidationError,
)
from app.plugins.business_hours import BusinessHoursConfig, BusinessHoursPlugin


class BusinessHoursPluginTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.config = BusinessHoursConfig(
            timezone="Asia/Shanghai",
            business_days=(0, 1, 2, 3, 4),
            open_time=time(9, 0),
            close_time=time(18, 0),
        )

    async def start_plugin(self, now: datetime):
        tools = PluginToolRegistry()
        plugin = BusinessHoursPlugin(self.config, now_provider=lambda: now)
        await plugin.start(
            PluginContext(
                logger=logging.getLogger("test.business_hours"),
                tools=tools,
            )
        )
        self.addAsyncCleanup(plugin.stop)
        return tools

    async def test_reports_open_during_configured_hours(self) -> None:
        tools = await self.start_plugin(
            datetime(2026, 9, 21, 2, 30, tzinfo=timezone.utc)
        )

        result = await tools.execute("get_customer_service_hours", {})

        self.assertTrue(result["is_open"])
        self.assertEqual(result["evaluated_at"], "2026-09-21T10:30+08:00")
        self.assertEqual(result["message"], "当前处于人工客服工作时间")

    async def test_reports_closed_on_weekend_and_at_close_boundary(self) -> None:
        tools = await self.start_plugin(
            datetime(2026, 9, 19, 2, 30, tzinfo=timezone.utc)
        )
        weekend = await tools.execute("get_customer_service_hours", {})
        boundary = await tools.execute(
            "get_customer_service_hours",
            {"at": "2026-09-21T18:00:00+08:00"},
        )

        self.assertFalse(weekend["is_open"])
        self.assertFalse(boundary["is_open"])

    async def test_explicit_time_is_validated_and_used(self) -> None:
        tools = await self.start_plugin(
            datetime(2026, 9, 19, 2, 30, tzinfo=timezone.utc)
        )
        normalized, missing = tools.validate(
            "get_customer_service_hours",
            {"at": "2026-09-21T14:30:00+08:00"},
        )
        result = await tools.execute("get_customer_service_hours", normalized)

        self.assertEqual(missing, [])
        self.assertTrue(result["is_open"])
        self.assertEqual(result["evaluated_at"], "2026-09-21T14:30+08:00")

        with self.assertRaises(ToolArgumentsValidationError):
            tools.validate(
                "get_customer_service_hours",
                {"at": "2026-09-21T14:30:00"},
            )

    async def test_tool_schema_describes_optional_time(self) -> None:
        tools = await self.start_plugin(datetime.now(timezone.utc))
        parameters = tools.definitions()[0]["function"]["parameters"]

        self.assertIn("at", parameters["properties"])
        self.assertNotIn("at", parameters.get("required", []))
        variants = parameters["properties"]["at"]["anyOf"]
        self.assertIn({"format": "date-time", "type": "string"}, variants)

    def test_rejects_invalid_configuration(self) -> None:
        with self.assertRaises(ValidationError):
            BusinessHoursConfig(timezone="Invalid/Timezone")
        with self.assertRaises(ValidationError):
            BusinessHoursConfig(open_time=time(18), close_time=time(9))
        with self.assertRaises(ValidationError):
            BusinessHoursConfig(business_days=(7,))
