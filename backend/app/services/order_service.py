import hashlib
import json
import math
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.constants.order_status import OrderStatus, can_transition
from app.ports.errors import OrderUniquenessConflictError
from app.ports.repositories import (
    AddressRepositoryPort,
    OrderRepositoryPort,
    ProductRepositoryPort,
    ShopRepositoryPort,
)
from app.schemas.delivery import (
    DeliveryAddressInput,
    OrderDeliveryAddressSnapshot,
    ResolvedDeliveryLocation,
)
from app.schemas.order import (
    OrderCancelResponse,
    OrderCreate,
    OrderCreateResponse,
    OrderCancellationConfirmationPreview,
    OrderConfirmationItem,
    OrderConfirmationPreview,
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


class OrderAddressNotFoundError(RuntimeError):
    """请求中的地址不存在、已删除或不属于当前用户。"""


class IdempotencyKeyConflictError(RuntimeError):
    """同一个幂等键被用于不同的创建订单请求。"""


class OrderNotFoundError(RuntimeError):
    """The order does not exist or is not accessible to the user."""


class OrderStateConflictError(RuntimeError):
    """The order exists, but its current state rejects the operation."""

    def __init__(
        self,
        message: str,
        *,
        current_status: OrderStatus | None = None,
    ) -> None:
        super().__init__(message)
        self.current_status = current_status


@dataclass(frozen=True)
class _PreparedOrder:
    """Validated and priced order data shared by preview and creation."""

    requested_quantities: dict[str, int]
    products_by_id: dict[str, Product]
    shop: Shop
    items: list[dict]
    delivery_snapshot: OrderDeliveryAddressSnapshot
    delivery_address_text: str
    goods_amount: float
    delivery_fee: float
    total_price: float


class OrderService:
    def __init__(
        self,
        repository: OrderRepositoryPort,
        product_repository: ProductRepositoryPort,
        shop_repository: ShopRepositoryPort,
        address_repository: AddressRepositoryPort,
        delivery_location_service: DeliveryLocationService,
        now_provider: Callable[[], datetime] | None = None,
    ):
        self.repository = repository
        self.product_repository = product_repository
        self.shop_repository = shop_repository
        self.address_repository = address_repository
        self.delivery_location_service = delivery_location_service
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    async def create_order(
        self,
        order: OrderCreate,
        user_id: str,
        *,
        idempotency_key: str,
        session=None,
    ):
        requested_quantities = self._requested_quantities(order)

        request_hash = self._build_idempotency_request_hash(
            order=order,
            requested_quantities=requested_quantities,
        )
        if session is None:
            existing_order = await self.repository.find_by_idempotency_key(
                user_id=user_id,
                idempotency_key=idempotency_key,
            )
        else:
            existing_order = await self.repository.find_by_idempotency_key(
                user_id=user_id,
                idempotency_key=idempotency_key,
                session=session,
            )
        if existing_order is not None:
            return self._response_from_idempotent_order(
                existing_order,
                request_hash=request_hash,
            )

        order_id = str(uuid.uuid4())
        create_time = self.now_provider()
        if create_time.tzinfo is None:
            raise RuntimeError("now_provider must return a timezone-aware datetime")

        async def create_in_transaction(session):
            prepared = await self._prepare_order(
                order,
                user_id,
                current_time=create_time,
                session=session,
            )

            for food_id, quantity in prepared.requested_quantities.items():
                reserved = await self.product_repository.reserve_stock(
                    product=prepared.products_by_id[food_id],
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
                "shop_id": prepared.shop.shop_id,
                "shop_name": prepared.shop.shop_name,
                "items": prepared.items,
                "order_status": OrderStatus.PENDING_PAYMENT.value,
                "create_time": create_time.astimezone(timezone.utc),
                "delivery_address": prepared.delivery_snapshot.model_dump(),
                "goods_amount": prepared.goods_amount,
                "delivery_fee": prepared.delivery_fee,
                "total_price": prepared.total_price,
                "idempotency_key": idempotency_key,
                "idempotency_request_hash": request_hash,
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
                goods_amount=prepared.goods_amount,
                delivery_fee=prepared.delivery_fee,
                total_price=prepared.total_price,
                delivery_distance_meters=(prepared.delivery_snapshot.distance_meters),
            )

        try:
            if session is None:
                return await self.repository.run_in_transaction(create_in_transaction)
            return await create_in_transaction(session)
        except OrderUniquenessConflictError as exc:
            if session is not None:
                # The outer write-command transaction must abort before any
                # duplicate-key recovery query. Continuing inside an aborted
                # MongoDB transaction could otherwise commit an invalid
                # command outcome.
                raise
            # 两个相同幂等键可能同时通过事务外的快速查询。数据库唯一
            # 索引决定唯一赢家；失败方读取赢家已经提交的订单并复用结果。
            if session is None:
                existing_order = await self.repository.find_by_idempotency_key(
                    user_id=user_id,
                    idempotency_key=idempotency_key,
                )
            else:
                existing_order = await self.repository.find_by_idempotency_key(
                    user_id=user_id,
                    idempotency_key=idempotency_key,
                    session=session,
                )
            if existing_order is None:
                raise RuntimeError(
                    "Order uniqueness conflict could not be resolved"
                ) from exc
            return self._response_from_idempotent_order(
                existing_order,
                request_hash=request_hash,
            )

    async def preview_order(
        self,
        order: OrderCreate,
        user_id: str,
    ) -> OrderConfirmationPreview:
        """Validate and price an order without reserving stock or writing data."""

        current_time = self.now_provider()
        if current_time.tzinfo is None:
            raise RuntimeError("now_provider must return a timezone-aware datetime")
        prepared = await self._prepare_order(
            order,
            user_id,
            current_time=current_time,
            session=None,
        )
        return OrderConfirmationPreview(
            shop_id=prepared.shop.shop_id,
            shop_name=prepared.shop.shop_name,
            address_id=prepared.delivery_snapshot.address_id,
            receiver_name=prepared.delivery_snapshot.receiver_name,
            receiver_phone=prepared.delivery_snapshot.receiver_phone,
            delivery_address=prepared.delivery_address_text,
            items=[
                OrderConfirmationItem(
                    food_id=item["food_id"],
                    food_name=item["food_name"],
                    quantity=item["quantity"],
                    unit_price=item["price"],
                    line_total=item["price"] * item["quantity"],
                )
                for item in prepared.items
            ],
            goods_amount=prepared.goods_amount,
            delivery_fee=prepared.delivery_fee,
            total_price=prepared.total_price,
        )

    async def preview_order_cancellation(
        self,
        order_id: str,
        user_id: str,
    ) -> OrderCancellationConfirmationPreview:
        """Build a cancellable order snapshot without changing its state."""

        order = await self.repository.query_order_by_id(order_id, user_id)
        if order is None:
            raise OrderNotFoundError("Order not found or not accessible")

        current_status = OrderStatus(order["order_status"])
        if not can_transition(current_status, OrderStatus.CANCELING):
            raise OrderStateConflictError(
                "Current order status cannot be canceled",
                current_status=current_status,
            )

        return OrderCancellationConfirmationPreview(
            order_id=order["order_id"],
            shop_id=order["shop_id"],
            shop_name=order.get("shop_name") or order["shop_id"],
            items=[
                OrderConfirmationItem(
                    food_id=item["food_id"],
                    food_name=item["food_name"],
                    quantity=item["quantity"],
                    unit_price=item["price"],
                    line_total=item["price"] * item["quantity"],
                )
                for item in order["items"]
            ],
            current_status=current_status,
            create_time=order["create_time"],
            total_price=order["total_price"],
        )

    async def _prepare_order(
        self,
        order: OrderCreate,
        user_id: str,
        *,
        current_time: datetime,
        session,
    ) -> _PreparedOrder:
        requested_quantities = self._requested_quantities(order)
        saved_address = await self.address_repository.find_by_id(
            user_id=user_id,
            address_id=order.address_id,
            session=session,
        )
        if saved_address is None:
            raise OrderAddressNotFoundError("Address not found")

        shop = await self.shop_repository.find_by_shop_id(
            order.shop_id,
            session=session,
        )
        self._validate_shop(shop, current_time)
        address_input = DeliveryAddressInput(
            province=saved_address.province,
            city=saved_address.city,
            district=saved_address.district,
            detail_address=saved_address.detail_address,
            longitude=saved_address.longitude,
            latitude=saved_address.latitude,
        )
        resolved_delivery_location = ResolvedDeliveryLocation(
            longitude=saved_address.longitude,
            latitude=saved_address.latitude,
            formatted_address=saved_address.formatted_address,
            province=saved_address.province,
            city=saved_address.city,
            district=saved_address.district,
            adcode=saved_address.adcode,
            location_source=saved_address.location_source,
            verification_status=saved_address.verification_status,
        )
        location_snapshot = self.delivery_location_service.build_snapshot(
            address=address_input,
            resolved=resolved_delivery_location,
            shop=shop,
        )
        delivery_snapshot = OrderDeliveryAddressSnapshot(
            **location_snapshot.model_dump(),
            address_id=saved_address.address_id,
            receiver_name=saved_address.receiver_name,
            receiver_phone=saved_address.receiver_phone,
            address_version=saved_address.version,
        )

        products = await self.product_repository.find_by_shop_and_food_ids(
            order.shop_id,
            list(requested_quantities),
            session=session,
        )
        products_by_id = {product.food_id: product for product in products}
        self._validate_products(
            requested_quantities=requested_quantities,
            products_by_id=products_by_id,
        )
        items = []
        for food_id, quantity in requested_quantities.items():
            product = products_by_id[food_id]
            items.append({
                "food_id": product.food_id,
                "food_name": product.food_name,
                "quantity": quantity,
                "price": product.price,
            })
        goods_amount = math.fsum(
            item["price"] * item["quantity"] for item in items
        )
        if goods_amount < shop.minimum_order_amount:
            raise MinimumOrderAmountError(
                "Order amount does not meet the shop minimum"
            )
        delivery_fee = shop.delivery_fee
        return _PreparedOrder(
            requested_quantities=requested_quantities,
            products_by_id=products_by_id,
            shop=shop,
            items=items,
            delivery_snapshot=delivery_snapshot,
            delivery_address_text=address_input.full_address(),
            goods_amount=goods_amount,
            delivery_fee=delivery_fee,
            total_price=math.fsum([goods_amount, delivery_fee]),
        )

    @staticmethod
    def _requested_quantities(order: OrderCreate) -> dict[str, int]:
        quantities: dict[str, int] = {}
        for item in order.items:
            quantities[item.food_id] = quantities.get(item.food_id, 0) + item.quantity
        return quantities

    @staticmethod
    def _build_idempotency_request_hash(
        *,
        order: OrderCreate,
        requested_quantities: dict[str, int],
    ) -> str:
        canonical_request = {
            "shop_id": order.shop_id,
            "address_id": order.address_id,
            "items": [
                {
                    "food_id": food_id,
                    "quantity": quantity,
                }
                for food_id, quantity in sorted(requested_quantities.items())
            ],
        }
        serialized = json.dumps(
            canonical_request,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @staticmethod
    def _response_from_idempotent_order(
        order_document: dict,
        *,
        request_hash: str,
    ) -> OrderCreateResponse:
        if order_document.get("idempotency_request_hash") != request_hash:
            raise IdempotencyKeyConflictError(
                "Idempotency key was already used for another order request"
            )

        delivery_address = order_document.get("delivery_address")
        if not isinstance(delivery_address, dict):
            raise RuntimeError(
                "Idempotent order is missing its delivery address snapshot"
            )

        return OrderCreateResponse(
            status="success",
            message="Order created successfully",
            order_id=order_document["order_id"],
            order_status=OrderStatus(order_document["order_status"]),
            goods_amount=order_document["goods_amount"],
            delivery_fee=order_document["delivery_fee"],
            total_price=order_document["total_price"],
            delivery_distance_meters=delivery_address["distance_meters"],
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
        if shop.timezone == "UTC":
            shop_timezone = timezone.utc
        else:
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
            period_date = local_time.date() - timedelta(days=days_since_period_start)
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
        missing_food_ids = sorted(set(requested_quantities) - set(products_by_id))
        if missing_food_ids:
            raise ProductNotFoundError(
                f"Products not found: {', '.join(missing_food_ids)}"
            )

        for food_id, quantity in requested_quantities.items():
            product = products_by_id[food_id]
            if not product.is_listed:
                raise ProductUnavailableError(f"Product {food_id} is not listed")
            if not product.is_available:
                raise ProductUnavailableError(f"Product {food_id} is not available")
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
            order=OrderQueryByIdData(**result),
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

    async def cancel_order(
        self,
        order_id: str,
        user_id: str,
        *,
        session=None,
    ) -> OrderCancelResponse:
        if session is None:
            result = await self.repository.query_order_status(order_id, user_id)
        else:
            result = await self.repository.query_order_status(
                order_id,
                user_id,
                session=session,
            )
        if result is None:
            raise OrderNotFoundError(
                "Order not found or not accessible"
            )
        current_status = OrderStatus(result["order_status"])
        if not can_transition(current_status, OrderStatus.CANCELING):
            raise OrderStateConflictError(
                "Current order status cannot be canceled",
                current_status=current_status,
            )
        if session is None:
            success = await self.repository.cancel_order(
                order_id,
                user_id,
                expected_status=current_status.value,
                target_status=OrderStatus.CANCELING.value,
            )
        else:
            success = await self.repository.cancel_order(
                order_id,
                user_id,
                expected_status=current_status.value,
                target_status=OrderStatus.CANCELING.value,
                session=session,
            )
        if not success:
            if session is None:
                latest_document = await self.repository.query_order_status(
                    order_id,
                    user_id,
                )
            else:
                latest_document = await self.repository.query_order_status(
                    order_id,
                    user_id,
                    session=session,
                )
            if latest_document is None:
                raise OrderNotFoundError(
                    "Order no longer exists or is not accessible"
                )

            latest_status = OrderStatus(
                latest_document["order_status"]
            )
            raise OrderStateConflictError(
                "Order status changed; cancellation was rejected",
                current_status=latest_status,
            )
        return OrderCancelResponse(
            status="success",
            message="Order cancellation request successful",
            order_status=OrderStatus.CANCELING,
        )

    async def list_orders_page(
        self,
        user_id: str,
        *,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[OrderHistoryItem], str | None]:
        documents, next_cursor = await self.repository.query_order_history_page(
            user_id,
            limit=limit,
            cursor=cursor,
        )
        return (
            [OrderHistoryItem.model_validate(document) for document in documents],
            next_cursor,
        )
