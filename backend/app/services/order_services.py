from app.repositories.order_repository import OrderRepository
from app.schemas.order import Order
from app.contants.order_status import OrderStatus
import uuid


class OrderServices:
    def __init__(self, repository: OrderRepository):
        self.repository = repository

    async def create_order(self, order: Order):
        order_data = {
            "order_id": str(uuid.uuid4()),
            "user_id": order.user_id,
            "shop_id": order.shop_id,
            "items": [item.model_dump() for item in order.items],
            "order_status": OrderStatus.PENDING_PAYMENT.value,
            "create_time": order.create_time,
            "delivery_address": order.delivery_address,
            "total_price": order.total_price,
        }
        result = await self.repository.create_order(order_data)
        if result:
            return {
                "status": "success",
                "message": "Order created successfully",
                "data": order_data,
            }
        else:
            return {
                "status": "error",
                "message": "Failed to create order",
            }