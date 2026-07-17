from app.repositories.order_repository import OrderRepository
from app.schemas.order import OrderCreate, OrderCreateResponse, OrderQueryByIdResponse, OrderQueryByIdData
from app.contants.order_status import OrderStatus
import uuid
from datetime import datetime

class OrderServices:
    def __init__(self, repository: OrderRepository):
        self.repository = repository

    async def create_order(self, order: OrderCreate):
        order_data = {
            "order_id": str(uuid.uuid4()),
            "user_id": order.user_id,
            "shop_id": order.shop_id,
            "items": [item.model_dump() for item in order.items],
            "order_status": OrderStatus.PENDING_PAYMENT.value,
            "create_time": datetime.now(),
            "delivery_address": order.delivery_address,
            "total_price": sum(item.price * item.quantity for item in order.items),
        }
        result = await self.repository.create_order(order_data)
        return OrderCreateResponse(
            status="success",
            message="Order created successfully",
            order_id=order_data["order_id"],
            order_status=order_data["order_status"],
        )

    async def query_order_by_id(self, order_id: str, user_id: str):
        result = await self.repository.query_order_by_id(order_id, user_id)
        if result is None:
            return OrderQueryByIdResponse(
                status="error",
                message="Order not found",
                order=None,
            )
        return OrderQueryByIdResponse(
            status="success",
            message="Order queried successfully",
            order=OrderQueryByIdData(**result)        
            )