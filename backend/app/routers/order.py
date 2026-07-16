from fastapi import APIRouter
from app.schemas.chat import ChatRequest, ChatResponse

router = APIRouter(prefix="/orders/{order_id}", tags=["外卖订单"])
