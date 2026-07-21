from pydantic import BaseModel, Field
from typing import List
from datetime import datetime
from app.contants.order_status import OrderStatus


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
