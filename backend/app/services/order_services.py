import math
import uuid
from datetime import datetime, timezone

from app.contants.order_status import OrderStatus, can_transition
from app.repositories.order_repository import OrderRepository
from app.repositories.product_repository import ProductRepository
from app.schemas.order import (
    OrderCancelResponse,
    OrderCreate,
    OrderCreateResponse,
    OrderHistoryItem,
    OrderHistoryQueryResponse,
    OrderQueryByIdData,
    OrderQueryByIdResponse,
    OrderStatusQueryResponse,
    Product,
)


class ProductNotFoundError(RuntimeError):
    """订单中的商品不存在。"""


class ProductShopMismatchError(RuntimeError):
    """订单中的商品不属于请求指定的店铺。"""


class ProductUnavailableError(RuntimeError):
    """订单中的商品未上架或当前不可售。"""


class InsufficientStockError(RuntimeError):
    """订单中的商品库存不足。"""


class OrderServices:
    def __init__(
        self,
        repository: OrderRepository,
        product_repository: ProductRepository,
    ):
        self.repository = repository
        self.product_repository = product_repository

    async def create_order(self, order: OrderCreate, user_id: str):
        requested_quantities: dict[str, int] = {}
        for item in order.items:
            requested_quantities[item.food_id] = (
                requested_quantities.get(item.food_id, 0) + item.quantity
            )

        products = await self.product_repository.find_by_food_ids(
            list(requested_quantities)
        )
        products_by_id = {product.food_id: product for product in products}
        self._validate_products(
            requested_quantities=requested_quantities,
            products_by_id=products_by_id,
            shop_id=order.shop_id,
        )

        order_items = []
        for food_id, quantity in requested_quantities.items():
            product = products_by_id[food_id]
            order_items.append({
                "food_id": product.food_id,
                "food_name": product.food_name,
                "quantity": quantity,
                "price": product.price,
            })
        order_data = {
            "order_id": str(uuid.uuid4()),
            "user_id": user_id,
            "shop_id": order.shop_id,
            "items": order_items,
            "order_status": OrderStatus.PENDING_PAYMENT.value,
            "create_time": datetime.now(timezone.utc),
            "delivery_address": order.delivery_address,
            "total_price": math.fsum(
                item["price"] * item["quantity"] for item in order_items
            ),
        }
        await self.repository.create_order(order_data)
        return OrderCreateResponse(
            status="success",
            message="Order created successfully",
            order_id=order_data["order_id"],
            order_status=order_data["order_status"],
        )

    @staticmethod
    def _validate_products(
        *,
        requested_quantities: dict[str, int],
        products_by_id: dict[str, Product],
        shop_id: str,
    ) -> None:
        missing_food_ids = sorted(
            set(requested_quantities) - set(products_by_id)
        )
        if missing_food_ids:
            raise ProductNotFoundError(
                f"Products not found: {', '.join(missing_food_ids)}"
            )

        for food_id, quantity in requested_quantities.items():
            product = products_by_id[food_id]
            if product.shop_id != shop_id:
                raise ProductShopMismatchError(
                    f"Product {food_id} does not belong to shop {shop_id}"
                )
            if not product.is_listed:
                raise ProductUnavailableError(
                    f"Product {food_id} is not listed"
                )
            if not product.is_available:
                raise ProductUnavailableError(
                    f"Product {food_id} is not available"
                )
            if quantity > product.stock:
                raise InsufficientStockError(
                    f"Insufficient stock for product {food_id}"
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
