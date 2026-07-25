import unittest
from datetime import datetime, time, timezone

from app.schemas.delivery import GeocodingResult
from app.schemas.order import OrderCreate
from app.schemas.product import Product
from app.schemas.shop import Shop
from app.services.delivery_location_service import DeliveryLocationService
from app.services.order_services import (
    InsufficientStockError,
    InventoryReservationError,
    MinimumOrderAmountError,
    OrderServices,
    ProductNotFoundError,
    ProductUnavailableError,
    ShopClosedError,
    ShopNotFoundError,
    ShopUnavailableError,
)


TEST_NOW = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)


class FakeAmapService:
    async def geocode(self, address):
        return GeocodingResult(
            longitude=116.001,
            latitude=39.0,
            formatted_address=address.full_address(),
            province=address.province,
            city=address.city,
            district=address.district,
            adcode="110105",
        )

    async def reverse_geocode(self, *, longitude: float, latitude: float):
        return GeocodingResult(
            longitude=longitude,
            latitude=latitude,
            formatted_address="Test formatted address",
            province="北京市",
            city="北京市",
            district="朝阳区",
            adcode="110105",
        )


class FakeOrderRepository:
    def __init__(self):
        self.created_order: dict | None = None
        self.transaction_count = 0

    async def run_in_transaction(self, callback):
        self.transaction_count += 1
        return await callback(object())

    async def create_order(self, order_data: dict, session=None):
        self.created_order = order_data
        return "mongo-id"


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
            if product.shop_id == shop_id
            and product.food_id in requested
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


def make_order(items: list[dict] | None = None) -> OrderCreate:
    return OrderCreate(
        shop_id="shop-001",
        items=items or [{"food_id": "food-001", "quantity": 2}],
        delivery_address={
            "province": "北京市",
            "city": "北京市",
            "district": "朝阳区",
            "detail_address": "Test address",
        },
    )


class OrderCreateServiceTests(unittest.IsolatedAsyncioTestCase):
    def make_service(
        self,
        products: list[Product],
        *,
        shop: Shop | None = None,
        failed_reservations: set[str] | None = None,
    ):
        order_repository = FakeOrderRepository()
        product_repository = FakeProductRepository(
            products,
            failed_reservations,
        )
        shop_repository = FakeShopRepository(
            make_shop() if shop is None else shop
        )
        service = OrderServices(
            order_repository,
            product_repository,
            shop_repository,
            DeliveryLocationService(FakeAmapService()),
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

        response = await service.create_order(make_order(), "user-001")

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
            order_repository.created_order["delivery_address"][
                "location_source"
            ],
            "geocoded",
        )

    async def test_rejects_missing_shop(self):
        service, order_repository, _, _ = self.make_service(
            [make_product()],
            shop=make_shop(shop_id="another-shop"),
        )

        with self.assertRaises(ShopNotFoundError):
            await service.create_order(make_order(), "user-001")

        self.assertIsNone(order_repository.created_order)

    async def test_rejects_inactive_shop(self):
        service, order_repository, _, _ = self.make_service(
            [make_product()],
            shop=make_shop(is_active=False),
        )

        with self.assertRaises(ShopUnavailableError):
            await service.create_order(make_order(), "user-001")

        self.assertIsNone(order_repository.created_order)

    async def test_rejects_shop_that_stopped_accepting_orders(self):
        service, order_repository, _, _ = self.make_service(
            [make_product()],
            shop=make_shop(is_accepting_orders=False),
        )

        with self.assertRaises(ShopUnavailableError):
            await service.create_order(make_order(), "user-001")

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
            await service.create_order(make_order(), "user-001")

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

        await service.create_order(make_order(), "user-001")

        self.assertIsNotNone(order_repository.created_order)

    async def test_rejects_product_not_found_in_requested_shop(self):
        service, order_repository, _, _ = self.make_service(
            [make_product(shop_id="shop-002")]
        )

        with self.assertRaises(ProductNotFoundError):
            await service.create_order(make_order(), "user-001")

        self.assertIsNone(order_repository.created_order)

    async def test_rejects_unlisted_product(self):
        service, order_repository, _, _ = self.make_service(
            [make_product(is_listed=False)]
        )

        with self.assertRaises(ProductUnavailableError):
            await service.create_order(make_order(), "user-001")

        self.assertIsNone(order_repository.created_order)

    async def test_rejects_unavailable_product(self):
        service, order_repository, _, _ = self.make_service(
            [make_product(is_available=False)]
        )

        with self.assertRaises(ProductUnavailableError):
            await service.create_order(make_order(), "user-001")

        self.assertIsNone(order_repository.created_order)

    async def test_rejects_total_duplicate_quantity_above_stock(self):
        service, order_repository, _, _ = self.make_service(
            [make_product(stock=5)]
        )
        order = make_order(
            [
                {"food_id": "food-001", "quantity": 3},
                {"food_id": "food-001", "quantity": 3},
            ]
        )

        with self.assertRaises(InsufficientStockError):
            await service.create_order(order, "user-001")

        self.assertIsNone(order_repository.created_order)

    async def test_rejects_order_below_minimum_amount(self):
        service, order_repository, product_repository, _ = self.make_service(
            [make_product(price=5.0)]
        )

        with self.assertRaises(MinimumOrderAmountError):
            await service.create_order(make_order(), "user-001")

        self.assertEqual(product_repository.reservations, [])
        self.assertIsNone(order_repository.created_order)

    async def test_rejects_concurrent_inventory_reservation_conflict(self):
        service, order_repository, _, _ = self.make_service(
            [make_product()],
            failed_reservations={"food-001"},
        )

        with self.assertRaises(InventoryReservationError):
            await service.create_order(make_order(), "user-001")

        self.assertIsNone(order_repository.created_order)


if __name__ == "__main__":
    unittest.main()
