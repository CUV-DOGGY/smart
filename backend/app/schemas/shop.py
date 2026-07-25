from datetime import datetime, time

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.delivery import StructuredAddress


class ShopBusinessHours(BaseModel):
    """店铺每周的一个营业时间段，星期一为 0，星期日为 6。"""

    model_config = ConfigDict(extra="forbid")

    day_of_week: int = Field(ge=0, le=6)
    open_time: time
    close_time: time


class Shop(BaseModel):
    """店铺集合中的可信店铺数据。"""

    model_config = ConfigDict(extra="forbid")

    shop_id: str = Field(min_length=1, max_length=64)
    shop_name: str = Field(min_length=1, max_length=200)
    is_active: bool
    is_accepting_orders: bool
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=64)
    business_hours: list[ShopBusinessHours] = Field(min_length=1)
    minimum_order_amount: float = Field(ge=0, allow_inf_nan=False)
    delivery_fee: float = Field(ge=0, allow_inf_nan=False)
    address: StructuredAddress | None = None
    longitude: float | None = Field(
        default=None,
        ge=-180,
        le=180,
        allow_inf_nan=False,
    )
    latitude: float | None = Field(
        default=None,
        ge=-90,
        le=90,
        allow_inf_nan=False,
    )
    adcode: str | None = Field(default=None, max_length=16)
    formatted_address: str | None = Field(default=None, max_length=500)
    delivery_radius_meters: int | None = Field(default=None, gt=0)
    location_updated_at: datetime | None = None

    @model_validator(mode="after")
    def validate_coordinate_pair(self):
        if (self.longitude is None) != (self.latitude is None):
            raise ValueError(
                "shop longitude and latitude must be provided together"
            )
        return self
