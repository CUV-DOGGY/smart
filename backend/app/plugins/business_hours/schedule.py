from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from app.plugins.business_hours.config import BusinessHoursConfig


WEEKDAY_NAMES = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def format_business_days(days: tuple[int, ...]) -> str:
    ordered = tuple(sorted(days))
    if ordered == tuple(range(ordered[0], ordered[-1] + 1)) and len(ordered) > 1:
        return f"{WEEKDAY_NAMES[ordered[0]]}至{WEEKDAY_NAMES[ordered[-1]]}"
    return "、".join(WEEKDAY_NAMES[day] for day in ordered)


@dataclass(frozen=True)
class BusinessHoursStatus:
    config: BusinessHoursConfig
    evaluated_at: datetime
    is_open: bool

    def as_dict(self) -> dict[str, object]:
        business_days = tuple(sorted(self.config.business_days))
        message = (
            "当前处于人工客服工作时间"
            if self.is_open
            else "当前不在人工客服工作时间"
        )
        return {
            "ok": True,
            "timezone": self.config.timezone,
            "business_days": [WEEKDAY_NAMES[day] for day in business_days],
            "weekdays": format_business_days(business_days),
            "open_time": self.config.open_time.strftime("%H:%M"),
            "close_time": self.config.close_time.strftime("%H:%M"),
            "evaluated_at": self.evaluated_at.isoformat(timespec="minutes"),
            "is_open": self.is_open,
            "message": message,
        }


class BusinessHoursSchedule:
    def __init__(self, config: BusinessHoursConfig) -> None:
        self.config = config
        self._timezone = ZoneInfo(config.timezone)

    def evaluate(self, moment: datetime) -> BusinessHoursStatus:
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError("moment must include a timezone offset")
        local_moment = moment.astimezone(self._timezone)
        is_open = (
            local_moment.weekday() in self.config.business_days
            and self.config.open_time <= local_moment.time() < self.config.close_time
        )
        return BusinessHoursStatus(
            config=self.config,
            evaluated_at=local_moment,
            is_open=is_open,
        )
