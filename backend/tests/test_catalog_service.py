import unittest
from datetime import time

from app.schemas.shop import Shop
from app.services.catalog_service import CatalogService, CatalogShopNotFoundError


def make_shop(*, is_active: bool = True, is_accepting_orders: bool = True) -> Shop:
    return Shop(
        shop_id="shop-001",
        shop_name="测试店铺",
        is_active=is_active,
        is_accepting_orders=is_accepting_orders,
        business_hours=[
            {
                "day_of_week": 0,
                "open_time": time(9, 0),
                "close_time": time(22, 0),
            }
        ],
        minimum_order_amount=20,
        delivery_fee=5,
    )


class FakeShopRepository:
    def __init__(self, shop):
        self.shop = shop
        self.requested_shop_id = None

    async def list_active(self):
        return [self.shop] if self.shop else []

    async def find_by_shop_id(self, shop_id, session=None):
        self.requested_shop_id = shop_id
        return self.shop


class CatalogServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_an_active_shop_that_is_not_accepting_orders(self):
        repository = FakeShopRepository(
            make_shop(is_accepting_orders=False)
        )
        service = CatalogService(repository, object())

        shop = await service.get_shop("shop-001")

        self.assertEqual(repository.requested_shop_id, "shop-001")
        self.assertFalse(shop.is_accepting_orders)

    async def test_rejects_missing_or_inactive_shop(self):
        for shop in (None, make_shop(is_active=False)):
            service = CatalogService(FakeShopRepository(shop), object())
            with self.subTest(shop=shop):
                with self.assertRaises(CatalogShopNotFoundError):
                    await service.get_shop("shop-001")


if __name__ == "__main__":
    unittest.main()
