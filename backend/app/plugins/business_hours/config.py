from datetime import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class BusinessHoursConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    timezone: str = "Asia/Shanghai"
    business_days: tuple[int, ...] = (0, 1, 2, 3, 4)
    open_time: time = time(9, 0)
    close_time: time = time(18, 0)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        return value

    @field_validator("business_days")
    @classmethod
    def validate_business_days(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        normalized = tuple(dict.fromkeys(values))
        if not normalized or any(value < 0 or value > 6 for value in normalized):
            raise ValueError("business_days must contain weekday numbers from 0 to 6")
        return normalized

    @model_validator(mode="after")
    def validate_time_range(self) -> "BusinessHoursConfig":
        if self.open_time.tzinfo is not None or self.close_time.tzinfo is not None:
            raise ValueError("business hours must use local times without timezone offsets")
        if self.open_time >= self.close_time:
            raise ValueError("open_time must be earlier than close_time")
        return self
