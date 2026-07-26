from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.delivery import DeliveryAddressInput


CHINA_MOBILE_PHONE_PATTERN = r"^1[3-9]\d{9}$"


class UserAddressCreate(DeliveryAddressInput):
    """新增收货地址请求。"""

    receiver_name: str = Field(min_length=1, max_length=50)
    receiver_phone: str = Field(
        pattern=CHINA_MOBILE_PHONE_PATTERN
    )


class UserAddressUpdate(UserAddressCreate):
    """完整修改收货地址请求。"""


class UserAddress(BaseModel):
    """user_addresses 集合中的完整地址文档。"""

    model_config = ConfigDict(extra="forbid")

    address_id: str = Field(min_length=1, max_length=64)
    user_id: str = Field(min_length=1, max_length=64)
    receiver_name: str = Field(min_length=1, max_length=50)
    receiver_phone: str = Field(
        pattern=CHINA_MOBILE_PHONE_PATTERN
    )
    province: str = Field(min_length=1, max_length=64)
    city: str = Field(min_length=1, max_length=64)
    district: str = Field(min_length=1, max_length=64)
    detail_address: str = Field(min_length=1, max_length=300)
    longitude: float = Field(
        ge=-180,
        le=180,
        allow_inf_nan=False,
    )
    latitude: float = Field(
        ge=-90,
        le=90,
        allow_inf_nan=False,
    )
    formatted_address: str | None = Field(default=None, max_length=500)
    adcode: str | None = Field(default=None, max_length=16)
    location_source: Literal["geocoded", "map_pick"]
    verification_status: Literal["verified", "unverified"]
    is_default: bool
    version: int = Field(ge=1)
    is_deleted: bool
    create_time: datetime
    update_time: datetime


class UserAddressData(BaseModel):
    """返回给当前用户的地址数据。"""

    model_config = ConfigDict(extra="forbid")

    address_id: str
    receiver_name: str
    receiver_phone: str
    province: str
    city: str
    district: str
    detail_address: str
    longitude: float
    latitude: float
    formatted_address: str | None = None
    adcode: str | None = None
    location_source: Literal["geocoded", "map_pick"]
    verification_status: Literal["verified", "unverified"]
    is_default: bool
    version: int
    create_time: datetime
    update_time: datetime

    @classmethod
    def from_document(cls, address: UserAddress):
        return cls.model_validate(
            address.model_dump(include=set(cls.model_fields))
        )


class UserAddressResponse(BaseModel):
    status: str
    message: str
    address: UserAddressData


class UserAddressListResponse(BaseModel):
    status: str
    message: str
    addresses: list[UserAddressData]


class UserAddressActionResponse(BaseModel):
    status: str
    message: str
