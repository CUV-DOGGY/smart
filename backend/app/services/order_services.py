import math
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.contants.order_status import OrderStatus, can_transition
from app.repositories.order_repository import OrderRepository
from app.repositories.product_repository import ProductRepository
from app.repositories.shop_repository import ShopRepository
from app.schemas.order import (
    OrderCancelResponse,
    OrderCreate,
    OrderCreateResponse,
    OrderHistoryItem,
    OrderHistoryQueryResponse,
    OrderQueryByIdData,
    OrderQueryByIdResponse,
    OrderStatusQueryResponse,
)
from app.schemas.product import Product
from app.schemas.shop import Shop
from app.services.delivery_location_service import DeliveryLocationService


class ShopNotFoundError(RuntimeError):
    """请求中的店铺不存在。"""


class ShopUnavailableError(RuntimeError):
    """店铺已停用或当前停止接单。"""


class ShopClosedError(RuntimeError):
    """当前时间不在店铺营业时间内。"""


class ProductNotFoundError(RuntimeError):
    """订单中的商品不存在。"""


class ProductUnavailableError(RuntimeError):
    """订单中的商品未上架或当前不可售。"""


class InsufficientStockError(RuntimeError):
    """订单中的商品库存不足。"""


class MinimumOrderAmountError(RuntimeError):
    """商品金额未达到店铺最低起送金额。"""


class InventoryReservationError(RuntimeError):
    """商品状态或库存发生并发变化，库存预占失败。"""


class OrderServices:
    def __init__(
        self,
        repository: OrderRepository,
        product_repository: ProductRepository,
        shop_repository: ShopRepository,
        delivery_location_service: DeliveryLocationService,
        now_provider: Callable[[], datetime] | None = None,
    ):
        self.repository = repository
        self.product_repository = product_repository
        self.shop_repository = shop_repository
        self.delivery_location_service = delivery_location_service
        self.now_provider = now_provider or (
            lambda: datetime.now(timezone.utc)
        )

    async def create_order(self, order: OrderCreate, user_id: str):
        requested_quantities: dict[str, int] = {}
        for item in order.items:
            requested_quantities[item.food_id] = (
                requested_quantities.get(item.food_id, 0) + item.quantity
            )

        order_id = str(uuid.uuid4())
        create_time = self.now_provider()
        if create_time.tzinfo is None:
            raise RuntimeError("now_provider must return a timezone-aware datetime")

        preliminary_shop = await self.shop_repository.find_by_shop_id(
            order.shop_id
        )
        self._validate_shop(preliminary_shop, create_time)
        self.delivery_location_service.validate_shop_configuration(
            preliminary_shop
        )
        resolved_delivery_location = (
            await self.delivery_location_service.resolve(
                order.delivery_address
            )
        )
        self.delivery_location_service.build_snapshot(
            address=order.delivery_address,
            resolved=resolved_delivery_location,
            shop=preliminary_shop,
        )

        async def create_in_transaction(session):
            shop = await self.shop_repository.find_by_shop_id(
                order.shop_id,
                session=session,
            )
            self._validate_shop(shop, create_time)
            delivery_snapshot = (
                self.delivery_location_service.build_snapshot(
                    address=order.delivery_address,
                    resolved=resolved_delivery_location,
                    shop=shop,
                )
            )

            products = (
                await self.product_repository.find_by_shop_and_food_ids(
                    order.shop_id,
                    list(requested_quantities),
                    session=session,
                )
            )
            products_by_id = {
                product.food_id: product for product in products
            }
            self._validate_products(
                requested_quantities=requested_quantities,
                products_by_id=products_by_id,
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

            goods_amount = math.fsum(
                item["price"] * item["quantity"] for item in order_items
            )
            if goods_amount < shop.minimum_order_amount:
                raise MinimumOrderAmountError(
                    "Order amount does not meet the shop minimum"
                )

            delivery_fee = shop.delivery_fee
            total_price = math.fsum([goods_amount, delivery_fee])

            for food_id, quantity in requested_quantities.items():
                reserved = await self.product_repository.reserve_stock(
                    product=products_by_id[food_id],
                    quantity=quantity,
                    session=session,
                )
                if not reserved:
                    raise InventoryReservationError(
                        f"Failed to reserve stock for product {food_id}"
                    )

            order_data = {
                "order_id": order_id,
                "user_id": user_id,
                "shop_id": shop.shop_id,
                "shop_name": shop.shop_name,
                "items": order_items,
                "order_status": OrderStatus.PENDING_PAYMENT.value,
                "create_time": create_time.astimezone(timezone.utc),
                "delivery_address": delivery_snapshot.model_dump(),
                "goods_amount": goods_amount,
                "delivery_fee": delivery_fee,
                "total_price": total_price,
            }
            await self.repository.create_order(
                order_data,
                session=session,
            )
            return OrderCreateResponse(
                status="success",
                message="Order created successfully",
                order_id=order_id,
                order_status=OrderStatus.PENDING_PAYMENT,
                goods_amount=goods_amount,
                delivery_fee=delivery_fee,
                total_price=total_price,
                delivery_distance_meters=(
                    delivery_snapshot.distance_meters
                ),
            )

        return await self.repository.run_in_transaction(
            create_in_transaction
        )

    @classmethod
    def _validate_shop(
        cls,
        shop: Shop | None,
        current_time: datetime,
    ) -> None:
        if shop is None:
            raise ShopNotFoundError("Shop not found")
        if not shop.is_active or not shop.is_accepting_orders:
            raise ShopUnavailableError("Shop is not accepting orders")
        if not cls._is_within_business_hours(shop, current_time):
            raise ShopClosedError("Shop is outside business hours")

    @staticmethod
    def _is_within_business_hours(
        shop: Shop,
        current_time: datetime,
    ) -> bool:
        try:
            shop_timezone = ZoneInfo(shop.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ShopUnavailableError(
                "Shop timezone configuration is invalid"
            ) from exc

        local_time = current_time.astimezone(shop_timezone)
        for business_period in shop.business_hours:
            days_since_period_start = (
                local_time.weekday() - business_period.day_of_week
            ) % 7
            period_date = local_time.date() - timedelta(
                days=days_since_period_start
            )
            period_start = datetime.combine(
                period_date,
                business_period.open_time,
                tzinfo=shop_timezone,
            )
            period_end_date = period_date
            if business_period.close_time <= business_period.open_time:
                period_end_date += timedelta(days=1)
            period_end = datetime.combine(
                period_end_date,
                business_period.close_time,
                tzinfo=shop_timezone,
            )
            if period_start <= local_time < period_end:
                return True
        return False

    @staticmethod
    def _validate_products(
        *,
        requested_quantities: dict[str, int],
        products_by_id: dict[str, Product],
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
