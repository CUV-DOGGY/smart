import unittest

from app.schemas.order import OrderCreate, Product
from app.services.order_services import (
    InsufficientStockError,
    OrderServices,
    ProductNotFoundError,
    ProductShopMismatchError,
    ProductUnavailableError,
)


class FakeOrderRepository:
    def __init__(self):
        self.created_order: dict | None = None

    async def create_order(self, order_data: dict):
        self.created_order = order_data
        return "mongo-id"


class FakeProductRepository:
    def __init__(self, products: list[Product]):
        self.products = products
        self.requested_food_ids: list[str] = []

    async def find_by_food_ids(self, food_ids: list[str]) -> list[Product]:
        self.requested_food_ids = food_ids
        requested = set(food_ids)
        return [
            product
            for product in self.products
            if product.food_id in requested
        ]


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


def make_order(items: list[dict] | None = None) -> OrderCreate:
    return OrderCreate(
        shop_id="shop-001",
        items=items or [{"food_id": "food-001", "quantity": 2}],
        delivery_address="Test address",
    )


class OrderCreateServiceTests(unittest.IsolatedAsyncioTestCase):
    def make_service(self, products: list[Product]):
        order_repository = FakeOrderRepository()
        product_repository = FakeProductRepository(products)
        service = OrderServices(order_repository, product_repository)
        return service, order_repository, product_repository

    async def test_uses_server_product_data_to_create_order(self):
        service, order_repository, product_repository = self.make_service(
            [make_product()]
        )

        response = await service.create_order(make_order(), "user-001")

        self.assertEqual(response.status, "success")
        self.assertEqual(product_repository.requested_food_ids, ["food-001"])
        self.assertIsNotNone(order_repository.created_order)
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
        self.assertEqual(order_repository.created_order["total_price"], 25.0)

    async def test_rejects_missing_product(self):
        service, order_repository, _ = self.make_service([])

        with self.assertRaises(ProductNotFoundError):
            await service.create_order(make_order(), "user-001")

        self.assertIsNone(order_repository.created_order)

    async def test_rejects_product_from_another_shop(self):
        service, order_repository, _ = self.make_service(
            [make_product(shop_id="shop-002")]
        )

        with self.assertRaises(ProductShopMismatchError):
            await service.create_order(make_order(), "user-001")

        self.assertIsNone(order_repository.created_order)

    async def test_rejects_unlisted_product(self):
        service, order_repository, _ = self.make_service(
            [make_product(is_listed=False)]
        )

        with self.assertRaises(ProductUnavailableError):
            await service.create_order(make_order(), "user-001")

        self.assertIsNone(order_repository.created_order)

    async def test_rejects_unavailable_product(self):
        service, order_repository, _ = self.make_service(
            [make_product(is_available=False)]
        )

        with self.assertRaises(ProductUnavailableError):
            await service.create_order(make_order(), "user-001")

        self.assertIsNone(order_repository.created_order)

    async def test_rejects_total_duplicate_quantity_above_stock(self):
        service, order_repository, _ = self.make_service(
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


if __name__ == "__main__":
    unittest.main()
