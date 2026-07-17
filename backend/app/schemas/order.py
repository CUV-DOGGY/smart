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
    user_id: str = Field(min_length=1)
    shop_id: str = Field(min_length=1)
    items: List[OrderItem]
    delivery_address: str = Field(min_length=1)


class OrderQueryByIdData(BaseModel):
    """订单"""
    order_id: str= Field(min_length=1)
    user_id: str = Field(min_length=1)
    shop_id: str = Field(min_length=1)
    items: List[OrderItem]
    order_status: OrderStatus
    delivery_address: str = Field(min_length=1)
    create_time: datetime 
    finish_time: datetime | None = None
    cancel_time: datetime | None = None
    total_price: float = Field(ge=0)

    
class OrderQueryByIdResponse(BaseModel):
    """查询订单响应"""
    status: str
    message: str
    order: OrderQueryByIdData|None = None