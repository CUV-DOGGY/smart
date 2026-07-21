from app.repositories.order_repository import OrderRepository
from app.schemas.order import (
    OrderCreate, OrderCreateResponse, OrderQueryByIdResponse, OrderQueryByIdData,
    OrderStatusQueryResponse, OrderHistoryQueryResponse, OrderHistoryItem, OrderCancelResponse
)
from app.contants.order_status import OrderStatus, can_transition
import uuid
from datetime import datetime, timezone

class OrderServices:
    def __init__(self, repository: OrderRepository):
        self.repository = repository

    async def create_order(self, order: OrderCreate, user_id: str):
        order_data = {
            "order_id": str(uuid.uuid4()),
            "user_id": user_id,
            "shop_id": order.shop_id,
            "items": [item.model_dump() for item in order.items],
            "order_status": OrderStatus.PENDING_PAYMENT.value,
            "create_time": datetime.now(timezone.utc),
            "delivery_address": order.delivery_address,
            "total_price": sum(item.price * item.quantity for item in order.items),
        }
        await self.repository.create_order(order_data)
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

    async def query_order_status(self, order_id: str, user_id: str):
        result = await self.repository.query_order_status(order_id, user_id)
        if result is None:
            return OrderStatusQueryResponse(
                status="error",
                message="Order not found",
                order_status=None,
            )
        return OrderStatusQueryResponse(
            status="success",
            message="Order status queried successfully",
            order_status=OrderStatus(result["order_status"]),
        )

    async def query_order_history(self, user_id: str):
        result = await self.repository.query_order_history(user_id)
        return OrderHistoryQueryResponse(
            status="success",
            message="Order history queried successfully",
            orders=[OrderHistoryItem(**order) for order in result],
        )

    async def cancel_order(self, order_id: str, user_id: str):
        result = await self.repository.query_order_status(order_id, user_id)
        if result is None:
            return OrderCancelResponse(
                status="error",
                message="Order not found",
                order_status=None
            )
        current_status = OrderStatus(result["order_status"])
        if not can_transition(current_status, OrderStatus.CANCELING):
            return OrderCancelResponse(
                status="error",
                message="Current order status cannot be canceled",
                order_status=current_status
            )
        success = await self.repository.cancel_order(order_id, user_id, OrderStatus.CANCELING.value)
        if not success:
            return OrderCancelResponse(
                status="error",
                message="Failed to cancel order",
                order_status=current_status
            )
        return OrderCancelResponse(
            status="success",
            message="Order cancellation request successful",
            order_status=OrderStatus.CANCELING,
        )
