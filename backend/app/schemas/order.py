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


class OrderCreateResponse(BaseModel):
    """创建订单响应"""
    status: str
    message: str
    order_id: str
    order_status: OrderStatus


class OrderCreate(BaseModel):
    """创建订单"""
    user_id: str
    shop_id: str
    items: List[OrderItem]
    delivery_address: str = Field(min_length=1)