from enum import Enum

from pydantic import BaseModel, ConfigDict, Field
from typing import List, Literal
from datetime import datetime
from app.constants.order_status import OrderStatus
from app.schemas.delivery import (
    DeliveryLocationSnapshot,
    OrderDeliveryAddressSnapshot,
)


class OrderCreateItem(BaseModel):
    """客户端提交的订单商品，只表达购买意图。"""

    model_config = ConfigDict(extra="forbid")

    food_id: str = Field(min_length=1, max_length=64)
    quantity: int = Field(ge=1)


class OrderItem(BaseModel):
    """订单项"""
    food_id: str
    food_name: str
    quantity: int = Field(ge=1)
    price: float = Field(ge=0)

class OrderCreateResponse(BaseModel):
    """创建订单响应"""
    status: str
    message: str
    order_id: str
    order_status: OrderStatus
    goods_amount: float = Field(ge=0, allow_inf_nan=False)
    delivery_fee: float = Field(ge=0, allow_inf_nan=False)
    total_price: float = Field(ge=0, allow_inf_nan=False)
    delivery_distance_meters: int = Field(ge=0)

class OrderCreate(BaseModel):
    """创建订单"""

    model_config = ConfigDict(extra="forbid")

    shop_id: str = Field(min_length=1, max_length=64)
    address_id: str = Field(min_length=1, max_length=64)
    items: List[OrderCreateItem] = Field(min_length=1, max_length=50)


class OrderConfirmationItem(BaseModel):
    """Safe product snapshot shown before an agent-created order is approved."""

    food_id: str
    food_name: str
    quantity: int = Field(ge=1)
    unit_price: float = Field(ge=0, allow_inf_nan=False)
    line_total: float = Field(ge=0, allow_inf_nan=False)


class OrderConfirmationPreview(BaseModel):
    """Read-only, server-priced presentation model for an order confirmation."""

    kind: Literal["order"] = "order"
    shop_id: str
    shop_name: str
    address_id: str
    receiver_name: str
    receiver_phone: str
    delivery_address: str
    items: List[OrderConfirmationItem]
    goods_amount: float = Field(ge=0, allow_inf_nan=False)
    delivery_fee: float = Field(ge=0, allow_inf_nan=False)
    total_price: float = Field(ge=0, allow_inf_nan=False)
    currency: Literal["CNY"] = "CNY"


class OrderCancellationConfirmationPreview(BaseModel):
    """Read-only order snapshot shown before a cancellation is approved."""

    kind: Literal["order_cancellation"] = "order_cancellation"
    order_id: str
    shop_id: str
    shop_name: str
    items: List[OrderConfirmationItem]
    current_status: OrderStatus
    create_time: datetime
    total_price: float = Field(ge=0, allow_inf_nan=False)
    currency: Literal["CNY"] = "CNY"


class OrderQueryByIdData(BaseModel):
    """订单"""
    order_id: str= Field(min_length=1)
    user_id: str = Field(min_length=1)
    shop_id: str = Field(min_length=1)
    items: List[OrderItem]
    order_status: OrderStatus
    delivery_address: (
        OrderDeliveryAddressSnapshot
        | DeliveryLocationSnapshot
        | str
    )
    create_time: datetime 
    finish_time: datetime | None = None
    cancel_time: datetime | None = None
    total_price: float = Field(ge=0)

    
class OrderQueryByIdResponse(BaseModel):
    """查询订单响应"""
    status: str
    message: str
    order: OrderQueryByIdData|None = None
 
 
class OrderStatusQueryResponse(BaseModel):
    """查询订单状态响应"""
    status: str
    message: str
    order_status: OrderStatus|None = None

class OrderHistoryItem(BaseModel):
    """订单历史项"""
    order_id: str = Field(min_length=1)
    shop_id: str = Field(min_length=1)
    items: List[OrderItem]
    order_status: str
    create_time: datetime
    total_price: float = Field(ge=0)

class OrderHistoryQueryResponse(BaseModel):
    """查询历史订单响应"""
    status: str
    message: str
    orders: List[OrderHistoryItem]


class OrderCancelRequest(BaseModel):
    """取消订单请求"""
    order_id: str = Field(min_length=1, description="订单ID")


class OrderCancelResponse(BaseModel):
    """取消订单响应"""
    status: str
    message: str
    order_status: OrderStatus | None = None


class OrderCreateResult(BaseModel):
    order_id: str
    order_status: OrderStatus
    goods_amount: float = Field(ge=0, allow_inf_nan=False)
    delivery_fee: float = Field(ge=0, allow_inf_nan=False)
    total_price: float = Field(ge=0, allow_inf_nan=False)
    delivery_distance_meters: int = Field(ge=0)


class OrderHistoryPage(BaseModel):
    items: List[OrderHistoryItem]
    next_cursor: str | None = None


class OrderCancelResult(BaseModel):
    order_id: str
    order_status: OrderStatus


class OrderAttemptStatus(str, Enum):
    NOT_FOUND = "not_found"
    RECEIVED = "received"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    EXPIRED = "expired"


class OrderAttemptResult(BaseModel):
    status: OrderAttemptStatus
    order: OrderQueryByIdData | None = None
    failure_code: str | None = None
    expires_at: datetime | None = None
