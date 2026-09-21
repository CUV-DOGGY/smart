from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from pydantic import Field, field_validator

from app.plugins.context import PluginContext
from app.plugins.tools import PluginToolArguments
from app.plugins.business_hours.config import BusinessHoursConfig
from app.plugins.business_hours.schedule import BusinessHoursSchedule


class BusinessHoursQuery(PluginToolArguments):
    at: datetime | None = Field(
        default=None,
        description=(
            "要查询的具体时间，使用带时区偏移的 ISO 8601 格式；"
            "不传时查询当前时间"
        ),
    )

    @field_validator("at")
    @classmethod
    def validate_at(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("at must include a timezone offset")
        return value


class BusinessHoursPlugin:
    name = "business_hours"
    tool_name = "get_customer_service_hours"

    def __init__(
        self,
        config: BusinessHoursConfig,
        *,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._context: PluginContext | None = None
        self._schedule = BusinessHoursSchedule(config)
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    async def start(self, context: PluginContext) -> None:
        context.tools.register(
            name=self.tool_name,
            description="查询人工客服在当前或指定时间是否营业，以及营业时间。",
            handler=self.get_customer_service_hours,
            arguments_model=BusinessHoursQuery,
        )

        self._context = context

        context.logger.info(
            "插件已启动 plugin=%s tool=%s",
            self.name,
            self.tool_name,
        )

    async def stop(self) -> None:
        if self._context is None:
            return

        self._context.tools.unregister(self.tool_name)

        self._context.logger.info(
            "插件已停止 plugin=%s tool=%s",
            self.name,
            self.tool_name,
        )

        self._context = None

    async def get_customer_service_hours(
        self,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        query = BusinessHoursQuery.model_validate(arguments)
        moment = query.at or self._now_provider()
        return self._schedule.evaluate(moment).as_dict()
