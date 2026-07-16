from pydantic import BaseModel, Field
from typing import List
from datetime import datetime
from app.contants.order_status import OrderStatus, can_transition


class OrderItem(BaseModel):
    """订单项"""
    food_id: str
    food_name: str
    quantity: int = Field(ge=1)
    price: float = Field(ge=0)


class Order(BaseModel):
    """订单"""
    user_id: str
    shop_id: str
    order_id: str = Field(min_length=1)
    items: List[OrderItem]
    order_status: OrderStatus = Field(default=OrderStatus.PENDING_PAYMENT)
    delivery_address: str = Field(min_length=1)
    create_time: datetime = Field(default_factory=datetime.now)
    finish_time: datetime | None = None
    total_price: float = Field(ge=0)