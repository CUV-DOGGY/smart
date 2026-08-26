import unittest
from datetime import datetime, time, timezone

from app.schemas.address import UserAddress
from app.schemas.order import OrderCreate
from app.schemas.product import Product
from app.schemas.shop import Shop
from app.ports.errors import OrderUniquenessConflictError
from app.services.delivery_location_service import DeliveryLocationService
from app.services.order_service import (
    IdempotencyKeyConflictError,
    InsufficientStockError,
    InventoryReservationError,
    MinimumOrderAmountError,
    OrderAddressNotFoundError,
    OrderNotFoundError,
    OrderStateConflictError,
    OrderService,
    ProductNotFoundError,
    ProductUnavailableError,
    ShopClosedError,
    ShopNotFoundError,
    ShopUnavailableError,
)
from app.constants.order_status import OrderStatus

TEST_NOW = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
TEST_IDEMPOTENCY_KEY = "checkout-test-001"


class FakeOrderRepository:
    def __init__(self):
        self.created_order: dict | None = None
        self.transaction_count = 0
        self.hide_existing_once = False
        self.raise_uniqueness_conflict = False

    async def run_in_transaction(self, callback):
        self.transaction_count += 1
        return await callback(object())

    async def create_order(self, order_data: dict, session=None):
        if self.raise_uniqueness_conflict:
            raise OrderUniquenessConflictError(
                "simulated concurrent idempotency conflict"
            )
        self.created_order = order_data
        return "mongo-id"

    async def find_by_idempotency_key(
        self,
        *,
        user_id: str,
        idempotency_key: str,
    ) -> dict | None:
        if self.hide_existing_once:
            self.hide_existing_once = False
            return None
        if (
            self.created_order is None
            or self.created_order["user_id"] != user_id
            or self.created_order["idempotency_key"] != idempotency_key
        ):
            return None
        return self.created_order


class FakeProductRepository:
    def __init__(
        self,
        products: list[Product],
        failed_reservations: set[str] | None = None,
    ):
        self.products = products
        self.failed_reservations = failed_reservations or set()
        self.query: tuple[str, list[str]] | None = None
        self.reservations: list[tuple[str, int]] = []

    async def find_by_shop_and_food_ids(
        self,
        shop_id: str,
        food_ids: list[str],
        session=None,
    ) -> list[Product]:
        self.query = (shop_id, food_ids)
        requested = set(food_ids)
        return [
            product
            for product in self.products
            if product.shop_id == shop_id and product.food_id in requested
        ]

    async def reserve_stock(
        self,
        *,
        product: Product,
        quantity: int,
        session,
    ) -> bool:
        if product.food_id in self.failed_reservations:
            return False
        self.reservations.append((product.food_id, quantity))
        return True


class FakeShopRepository:
    def __init__(self, shop: Shop | None):
        self.shop = shop
        self.requested_shop_id: str | None = None

    async def find_by_shop_id(self, shop_id: str, session=None) -> Shop | None:
        self.requested_shop_id = shop_id
        if self.shop is None or self.shop.shop_id != shop_id:
            return None
        return self.shop


class FakeAddressRepository:
    def __init__(self, address: UserAddress | None):
        self.address = address
        self.query: tuple[str, str] | None = None

    async def find_by_id(
        self,
        *,
        user_id: str,
        address_id: str,
        session=None,
    ) -> UserAddress | None:
        self.query = (user_id, address_id)
        if (
            self.address is None
            or self.address.user_id != user_id
            or self.address.address_id != address_id
            or self.address.is_deleted
        ):
            return None
        return self.address


def make_product(**overrides) -> Product:
    product_data = {
        "food_id": "food-001",
        "shop_id": "shop-001",
        "food_name": "Test food",
        "price": 12.5,
        "stock": 10,
        "is_listed": True,
        "is_available": True,
    }
    product_data.update(overrides)
    return Product(**product_data)


def make_shop(**overrides) -> Shop:
    shop_data = {
        "shop_id": "shop-001",
        "shop_name": "Test shop",
        "is_active": True,
        "is_accepting_orders": True,
        "timezone": "UTC",
        "business_hours": [
            {
                "day_of_week": TEST_NOW.weekday(),
                "open_time": time(9, 0),
                "close_time": time(22, 0),
            }
        ],
        "minimum_order_amount": 20.0,
        "delivery_fee": 5.0,
        "longitude": 116.0,
        "latitude": 39.0,
        "delivery_radius_meters": 5000,
    }
    shop_data.update(overrides)
    return Shop(**shop_data)


def make_address(**overrides) -> UserAddress:
    address_data = {
        "address_id": "address-001",
        "user_id": "user-001",
        "receiver_name": "Test User",
        "receiver_phone": "13800138000",
        "province": "北京市",
        "city": "北京市",
        "district": "朝阳区",
        "detail_address": "Test address",
        "longitude": 116.001,
        "latitude": 39.0,
        "formatted_address": "Test formatted address",
        "adcode": "110105",
        "location_source": "geocoded",
        "verification_status": "verified",
        "is_default": True,
        "version": 2,
        "is_deleted": False,
        "create_time": TEST_NOW,
        "update_time": TEST_NOW,
    }
    address_data.update(overrides)
    return UserAddress(**address_data)


def make_order(items: list[dict] | None = None) -> OrderCreate:
    return OrderCreate(
        shop_id="shop-001",
        address_id="address-001",
        items=items or [{"food_id": "food-001", "quantity": 2}],
    )


class OrderCreateServiceTests(unittest.IsolatedAsyncioTestCase):
    def make_service(
        self,
        products: list[Product],
        *,
        shop: Shop | None = None,
        address: UserAddress | None = None,
        no_address: bool = False,
        failed_reservations: set[str] | None = None,
    ):
        order_repository = FakeOrderRepository()
        product_repository = FakeProductRepository(
            products,
            failed_reservations,
        )
        shop_repository = FakeShopRepository(make_shop() if shop is None else shop)
        address_repository = FakeAddressRepository(
            None if no_address else (make_address() if address is None else address)
        )
        service = OrderService(
            order_repository,
            product_repository,
            shop_repository,
            address_repository,
            DeliveryLocationService(),
            now_provider=lambda: TEST_NOW,
        )
        return (
            service,
            order_repository,
            product_repository,
            shop_repository,
        )

    async def test_creates_priced_order_and_reserves_stock_in_transaction(self):
        service, order_repository, product_repository, shop_repository = (
            self.make_service([make_product()])
        )

        response = await service.create_order(
            make_order(),
            "user-001",
            idempotency_key=TEST_IDEMPOTENCY_KEY,
        )

        self.assertEqual(response.status, "success")
        self.assertEqual(response.goods_amount, 25.0)
        self.assertEqual(response.delivery_fee, 5.0)
        self.assertEqual(response.total_price, 30.0)
        self.assertGreater(response.delivery_distance_meters, 0)
        self.assertEqual(order_repository.transaction_count, 1)
        self.assertEqual(shop_repository.requested_shop_id, "shop-001")
        self.assertEqual(
            product_repository.query,
            ("shop-001", ["food-001"]),
        )
        self.assertEqual(
            product_repository.reservations,
            [("food-001", 2)],
        )
        self.assertEqual(
            order_repository.created_order["items"],
            [
                {
                    "food_id": "food-001",
                    "food_name": "Test food",
                    "quantity": 2,
                    "price": 12.5,
                }
            ],
        )
        self.assertEqual(
            order_repository.created_order["goods_amount"],
            25.0,
        )
        self.assertEqual(
            order_repository.created_order["delivery_fee"],
            5.0,
        )
        self.assertEqual(
            order_repository.created_order["total_price"],
            30.0,
        )
        self.assertEqual(
            order_repository.created_order["delivery_address"]["location_source"],
            "geocoded",
        )
        self.assertEqual(
            order_repository.created_order["delivery_address"]["address_id"],
            "address-001",
        )
        self.assertEqual(
            order_repository.created_order["delivery_address"]["address_version"],
            2,
        )
        self.assertEqual(
            order_repository.created_order["delivery_address"]["receiver_phone"],
            "13800138000",
        )
        self.assertEqual(
            order_repository.created_order["idempotency_key"],
            TEST_IDEMPOTENCY_KEY,
        )
        self.assertEqual(
            len(order_repository.created_order["idempotency_request_hash"]),
            64,
        )

    async def test_same_idempotency_key_returns_existing_order(self):
        service, order_repository, product_repository, _ = self.make_service(
            [make_product()]
        )

        first_response = await service.create_order(
            make_order(),
            "user-001",
            idempotency_key=TEST_IDEMPOTENCY_KEY,
        )
        second_response = await service.create_order(
            make_order(),
            "user-001",
            idempotency_key=TEST_IDEMPOTENCY_KEY,
        )

        self.assertEqual(second_response, first_response)
        self.assertEqual(order_repository.transaction_count, 1)
        self.assertEqual(
            product_repository.reservations,
            [("food-001", 2)],
        )

    async def test_same_key_rejects_a_different_order_request(self):
        service, order_repository, product_repository, _ = self.make_service(
            [make_product()]
        )
        await service.create_order(
            make_order(),
            "user-001",
            idempotency_key=TEST_IDEMPOTENCY_KEY,
        )

        with self.assertRaises(IdempotencyKeyConflictError):
            await service.create_order(
                make_order([{"food_id": "food-001", "quantity": 3}]),
                "user-001",
                idempotency_key=TEST_IDEMPOTENCY_KEY,
            )

        self.assertEqual(order_repository.transaction_count, 1)
        self.assertEqual(
            product_repository.reservations,
            [("food-001", 2)],
        )

    async def test_concurrent_key_conflict_returns_the_winning_order(self):
        service, order_repository, _, _ = self.make_service([make_product()])
        first_response = await service.create_order(
            make_order(),
            "user-001",
            idempotency_key=TEST_IDEMPOTENCY_KEY,
        )

        order_repository.hide_existing_once = True
        order_repository.raise_uniqueness_conflict = True
        second_response = await service.create_order(
            make_order(),
            "user-001",
            idempotency_key=TEST_IDEMPOTENCY_KEY,
        )

        self.assertEqual(second_response, first_response)
        self.assertEqual(order_repository.transaction_count, 2)

    async def test_rejects_missing_or_unowned_address(self):
        service, order_repository, _, _ = self.make_service(
            [make_product()],
            no_address=True,
        )

        with self.assertRaises(OrderAddressNotFoundError):
            await service.create_order(
                make_order(),
                "user-001",
                idempotency_key=TEST_IDEMPOTENCY_KEY,
            )

        self.assertIsNone(order_repository.created_order)

    async def test_rejects_missing_shop(self):
        service, order_repository, _, _ = self.make_service(
            [make_product()],
            shop=make_shop(shop_id="another-shop"),
        )

        with self.assertRaises(ShopNotFoundError):
            await service.create_order(
                make_order(),
                "user-001",
                idempotency_key=TEST_IDEMPOTENCY_KEY,
            )

        self.assertIsNone(order_repository.created_order)

    async def test_rejects_inactive_shop(self):
        service, order_repository, _, _ = self.make_service(
            [make_product()],
            shop=make_shop(is_active=False),
        )

        with self.assertRaises(ShopUnavailableError):
            await service.create_order(
                make_order(),
                "user-001",
                idempotency_key=TEST_IDEMPOTENCY_KEY,
            )

        self.assertIsNone(order_repository.created_order)

    async def test_rejects_shop_that_stopped_accepting_orders(self):
        service, order_repository, _, _ = self.make_service(
            [make_product()],
            shop=make_shop(is_accepting_orders=False),
        )

        with self.assertRaises(ShopUnavailableError):
            await service.create_order(
                make_order(),
                "user-001",
                idempotency_key=TEST_IDEMPOTENCY_KEY,
            )

        self.assertIsNone(order_repository.created_order)

    async def test_rejects_shop_outside_business_hours(self):
        service, order_repository, _, _ = self.make_service(
            [make_product()],
            shop=make_shop(
                business_hours=[
                    {
                        "day_of_week": TEST_NOW.weekday(),
                        "open_time": time(1, 0),
                        "close_time": time(2, 0),
                    }
                ]
            ),
        )

        with self.assertRaises(ShopClosedError):
            await service.create_order(
                make_order(),
                "user-001",
                idempotency_key=TEST_IDEMPOTENCY_KEY,
            )

        self.assertIsNone(order_repository.created_order)

    async def test_accepts_overnight_business_hours(self):
        service, order_repository, _, _ = self.make_service(
            [make_product()],
            shop=make_shop(
                business_hours=[
                    {
                        "day_of_week": (TEST_NOW.weekday() - 1) % 7,
                        "open_time": time(22, 0),
                        "close_time": time(13, 0),
                    }
                ]
            ),
        )

        await service.create_order(
            make_order(),
            "user-001",
            idempotency_key=TEST_IDEMPOTENCY_KEY,
        )

        self.assertIsNotNone(order_repository.created_order)

    async def test_rejects_product_not_found_in_requested_shop(self):
        service, order_repository, _, _ = self.make_service(
            [make_product(shop_id="shop-002")]
        )

        with self.assertRaises(ProductNotFoundError):
            await service.create_order(
                make_order(),
                "user-001",
                idempotency_key=TEST_IDEMPOTENCY_KEY,
            )

        self.assertIsNone(order_repository.created_order)

    async def test_rejects_unlisted_product(self):
        service, order_repository, _, _ = self.make_service(
            [make_product(is_listed=False)]
        )

        with self.assertRaises(ProductUnavailableError):
            await service.create_order(
                make_order(),
                "user-001",
                idempotency_key=TEST_IDEMPOTENCY_KEY,
            )

        self.assertIsNone(order_repository.created_order)

    async def test_rejects_unavailable_product(self):
        service, order_repository, _, _ = self.make_service(
            [make_product(is_available=False)]
        )

        with self.assertRaises(ProductUnavailableError):
            await service.create_order(
                make_order(),
                "user-001",
                idempotency_key=TEST_IDEMPOTENCY_KEY,
            )

        self.assertIsNone(order_repository.created_order)

    async def test_rejects_total_duplicate_quantity_above_stock(self):
        service, order_repository, _, _ = self.make_service([make_product(stock=5)])
        order = make_order(
            [
                {"food_id": "food-001", "quantity": 3},
                {"food_id": "food-001", "quantity": 3},
            ]
        )

        with self.assertRaises(InsufficientStockError):
            await service.create_order(
                order,
                "user-001",
                idempotency_key=TEST_IDEMPOTENCY_KEY,
            )

        self.assertIsNone(order_repository.created_order)

    async def test_rejects_order_below_minimum_amount(self):
        service, order_repository, product_repository, _ = self.make_service(
            [make_product(price=5.0)]
        )

        with self.assertRaises(MinimumOrderAmountError):
            await service.create_order(
                make_order(),
                "user-001",
                idempotency_key=TEST_IDEMPOTENCY_KEY,
            )

        self.assertEqual(product_repository.reservations, [])
        self.assertIsNone(order_repository.created_order)

    async def test_rejects_concurrent_inventory_reservation_conflict(self):
        service, order_repository, _, _ = self.make_service(
            [make_product()],
            failed_reservations={"food-001"},
        )

        with self.assertRaises(InventoryReservationError):
            await service.create_order(
                make_order(),
                "user-001",
                idempotency_key=TEST_IDEMPOTENCY_KEY,
            )

        self.assertIsNone(order_repository.created_order)

    async def test_cancel_does_not_overwrite_concurrent_delivery(self):
        class ConcurrentCancelRepository:
            def __init__(self):
                self.order_status = OrderStatus.PREPARING.value

            async def query_order_status(
                self,
                order_id: str,
                user_id: str,
            ):
                observed_status = self.order_status

                # 模拟查询完成后，商家先把订单改成配送中
                self.order_status = OrderStatus.DELIVERING.value

                # Service拿到的仍是查询时的旧状态
                return {"order_status": observed_status}

            async def cancel_order(
                self,
                order_id: str,
                user_id: str,
                expected_status: str,
                target_status: str,
            ):
                if self.order_status != expected_status:
                    return False

                self.order_status = target_status
                return True

        service, _, _, _ = self.make_service([make_product()])
        repository = ConcurrentCancelRepository()
        service.repository = repository

        with self.assertRaises(OrderStateConflictError) as raised:
            await service.cancel_order(
                "order-001",
                "user-001",
            )

        self.assertEqual(
            repository.order_status,
            OrderStatus.DELIVERING.value,
        )
        self.assertEqual(
            raised.exception.current_status,
            OrderStatus.DELIVERING,
        )

    async def test_preview_reuses_pricing_without_reserving_or_writing(self):
        service, order_repository, product_repository, _ = self.make_service(
            [make_product()]
        )

        preview = await service.preview_order(make_order(), "user-001")

        self.assertEqual(preview.kind, "order")
        self.assertEqual(preview.shop_name, "Test shop")
        self.assertEqual(preview.receiver_name, "Test User")
        self.assertEqual(preview.delivery_address, "北京市朝阳区Test address")
        self.assertEqual(preview.items[0].food_name, "Test food")
        self.assertEqual(preview.items[0].unit_price, 12.5)
        self.assertEqual(preview.items[0].line_total, 25.0)
        self.assertEqual(preview.total_price, 30.0)
        self.assertEqual(product_repository.reservations, [])
        self.assertEqual(order_repository.transaction_count, 0)
        self.assertIsNone(order_repository.created_order)

    async def test_cancel_preview_returns_cancellable_order_without_writing(self):
        class CancellationPreviewRepository:
            def __init__(self):
                self.queries = []

            async def query_order_by_id(self, order_id: str, user_id: str):
                self.queries.append((order_id, user_id))
                return {
                    "order_id": order_id,
                    "user_id": user_id,
                    "shop_id": "shop-001",
                    "shop_name": "Test shop",
                    "items": [{
                        "food_id": "food-001",
                        "food_name": "Test food",
                        "quantity": 2,
                        "price": 12.5,
                    }],
                    "order_status": OrderStatus.PREPARING.value,
                    "create_time": TEST_NOW,
                    "total_price": 30.0,
                }

        service, _, _, _ = self.make_service([make_product()])
        repository = CancellationPreviewRepository()
        service.repository = repository

        preview = await service.preview_order_cancellation(
            "order-001",
            "user-001",
        )

        self.assertEqual(preview.kind, "order_cancellation")
        self.assertEqual(preview.order_id, "order-001")
        self.assertEqual(preview.current_status, OrderStatus.PREPARING)
        self.assertEqual(preview.items[0].line_total, 25.0)
        self.assertEqual(preview.total_price, 30.0)
        self.assertEqual(repository.queries, [("order-001", "user-001")])

    async def test_cancel_preview_rejects_non_cancellable_order(self):
        class DeliveringOrderRepository:
            async def query_order_by_id(self, order_id: str, user_id: str):
                return {
                    "order_id": order_id,
                    "user_id": user_id,
                    "shop_id": "shop-001",
                    "shop_name": "Test shop",
                    "items": [{
                        "food_id": "food-001",
                        "food_name": "Test food",
                        "quantity": 2,
                        "price": 12.5,
                    }],
                    "order_status": OrderStatus.DELIVERING.value,
                    "create_time": TEST_NOW,
                    "total_price": 30.0,
                }

        service, _, _, _ = self.make_service([make_product()])
        service.repository = DeliveringOrderRepository()

        with self.assertRaises(OrderStateConflictError) as raised:
            await service.preview_order_cancellation(
                "order-001",
                "user-001",
            )

        self.assertEqual(
            raised.exception.current_status,
            OrderStatus.DELIVERING,
        )

    async def test_cancel_failed_returns_latest_delivering_status(self):
        class MockOrderRepository:
            def __init__(self):
                self.mock_db = {
                    "order-001": {
                        "user_id": "user-001",
                        "order_status": OrderStatus.PREPARING.value,
                    }
                }

            async def query_order_status(
                self,
                order_id: str,
                user_id: str,
            ):
                queried_status = self.mock_db[order_id]["order_status"]
                self.mock_db[order_id]["order_status"] = OrderStatus.DELIVERING.value

                return {"order_status": queried_status}

            async def cancel_order(
                self,
                order_id: str,
                user_id: str,
                expected_status: str,
                target_status: str,
            ):
                actual_status = self.mock_db[order_id]["order_status"]
                if actual_status != expected_status:
                    return False

                self.mock_db[order_id]["order_status"] = target_status
                return True

        service, _, _, _ = self.make_service([make_product()])
        repository = MockOrderRepository()
        service.repository = repository

        with self.assertRaises(OrderStateConflictError) as raised:
            await service.cancel_order(
                "order-001",
                "user-001",
            )

        self.assertEqual(
            repository.mock_db["order-001"]["order_status"],
            OrderStatus.DELIVERING.value,
        )
        self.assertEqual(
            str(raised.exception),
            "Order status changed; cancellation was rejected",
        )
        self.assertEqual(
            raised.exception.current_status,
            OrderStatus.DELIVERING,
        )

    async def test_cancel_succeeds_when_status_is_unchanged(self):
        class StableCancelRepository:
            def __init__(self):
                self.order_status = OrderStatus.PREPARING.value

            async def query_order_status(
                self,
                order_id: str,
                user_id: str,
            ):
                return {"order_status": self.order_status}

            async def cancel_order(
                self,
                order_id: str,
                user_id: str,
                expected_status: str,
                target_status: str,
            ):
                if self.order_status != expected_status:
                    return False

                self.order_status = target_status
                return True

        service, _, _, _ = self.make_service([make_product()])
        repository = StableCancelRepository()
        service.repository = repository

        response = await service.cancel_order(
            "order-001",
            "user-001",
        )

        self.assertEqual(
            repository.order_status,
            OrderStatus.CANCELING.value,
        )
        self.assertEqual(response.status, "success")
        self.assertEqual(
            response.order_status,
            OrderStatus.CANCELING,
        )

    async def test_cancel_raises_not_found_when_order_disappears_after_conflict(
        self,
    ):
        class DisappearingOrderRepository:
            def __init__(self):
                self.query_count = 0
                self.cancel_count = 0
                self.cancel_arguments = None

            async def query_order_status(
                self,
                order_id: str,
                user_id: str,
            ):
                self.query_count += 1

                if self.query_count == 1:
                    return {"order_status": OrderStatus.PREPARING.value}

                return None

            async def cancel_order(
                self,
                order_id: str,
                user_id: str,
                expected_status: str,
                target_status: str,
            ):
                self.cancel_count += 1
                self.cancel_arguments = (
                    order_id,
                    user_id,
                    expected_status,
                    target_status,
                )
                return False

        service, _, _, _ = self.make_service([make_product()])
        repository = DisappearingOrderRepository()
        service.repository = repository

        with self.assertRaises(OrderNotFoundError) as raised:
            await service.cancel_order(
                "order-001",
                "user-001",
            )

        self.assertEqual(repository.query_count, 2)
        self.assertEqual(repository.cancel_count, 1)
        self.assertEqual(
            repository.cancel_arguments,
            (
                "order-001",
                "user-001",
                OrderStatus.PREPARING.value,
                OrderStatus.CANCELING.value,
            ),
        )
        self.assertEqual(
            str(raised.exception),
            "Order no longer exists or is not accessible",
        )


if __name__ == "__main__":
    unittest.main()
