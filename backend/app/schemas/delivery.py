from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StructuredAddress(BaseModel):
    """可用于地理编码的结构化地址。"""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    province: str = Field(min_length=1, max_length=64)
    city: str = Field(min_length=1, max_length=64)
    district: str = Field(min_length=1, max_length=64)
    detail_address: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def normalize_detail_address(self):
        normalized_detail = self.detail_address
        for administrative_area in (
            self.province,
            self.city,
            self.district,
        ):
            normalized_detail = normalized_detail.lstrip(
                " \t,，、/\\-"
            )
            if normalized_detail.startswith(administrative_area):
                normalized_detail = normalized_detail[
                    len(administrative_area):
                ]

        normalized_detail = normalized_detail.lstrip(
            " \t,，、/\\-"
        )
        if not normalized_detail:
            raise ValueError(
                "detail_address must contain a street, building, or door number"
            )
        self.detail_address = normalized_detail
        return self

    def full_address(self) -> str:
        parts = [self.province]
        if self.city != self.province:
            parts.append(self.city)
        parts.extend([self.district, self.detail_address])
        return "".join(parts)


class DeliveryAddressInput(StructuredAddress):
    """创建订单时提交的地址；地图选点经纬度必须同时出现。"""

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

    @model_validator(mode="after")
    def validate_coordinate_pair(self):
        if (self.longitude is None) != (self.latitude is None):
            raise ValueError("longitude and latitude must be provided together")
        return self


class GeocodingResult(BaseModel):
    """高德地理编码或逆地理编码得到的位置。"""

    model_config = ConfigDict(extra="forbid")

    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    formatted_address: str | None = Field(default=None, max_length=500)
    province: str | None = Field(default=None, max_length=64)
    city: str | None = Field(default=None, max_length=64)
    district: str | None = Field(default=None, max_length=64)
    adcode: str | None = Field(default=None, max_length=16)


class ResolvedDeliveryLocation(GeocodingResult):
    """创建订单过程中解析完成、尚未绑定店铺半径的位置。"""

    location_source: Literal["geocoded", "map_pick"]
    verification_status: Literal["verified", "unverified"]


class DeliveryLocationSnapshot(ResolvedDeliveryLocation):
    """写入订单的配送位置和配送范围判断快照。"""

    detail_address: str = Field(min_length=1, max_length=300)
    distance_meters: int = Field(ge=0)
    delivery_radius_meters_snapshot: int = Field(gt=0)


class OrderDeliveryAddressSnapshot(DeliveryLocationSnapshot):
    """订单保存的用户地址及配送判断快照。"""

    address_id: str = Field(min_length=1, max_length=64)
    receiver_name: str = Field(min_length=1, max_length=50)
    receiver_phone: str = Field(pattern=r"^1[3-9]\d{9}$")
    address_version: int = Field(ge=1)


class ShopLocationUpdate(BaseModel):
    """店铺地址编码服务返回、供未来店铺管理功能保存的数据。"""

    model_config = ConfigDict(extra="forbid")

    address: StructuredAddress
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    adcode: str | None = Field(default=None, max_length=16)
    formatted_address: str | None = Field(default=None, max_length=500)
    location_updated_at: datetime
