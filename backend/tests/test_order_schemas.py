import unittest

from pydantic import ValidationError

from app.schemas.order import OrderCreate


class OrderCreateSchemaTests(unittest.TestCase):
    def test_accepts_single_shop_items_without_client_prices(self):
        order = OrderCreate(
            shop_id="shop-001",
            address_id="address-001",
            items=[
                {"food_id": "food-001", "quantity": 2},
                {"food_id": "food-002", "quantity": 1},
            ],
        )

        self.assertEqual(order.shop_id, "shop-001")
        self.assertEqual(len(order.items), 2)

    def test_rejects_client_controlled_item_price_and_name(self):
        with self.assertRaises(ValidationError):
            OrderCreate(
                shop_id="shop-001",
                address_id="address-001",
                items=[
                    {
                        "food_id": "food-001",
                        "food_name": "伪造商品名",
                        "quantity": 1,
                        "price": 0,
                    }
                ],
            )

    def test_rejects_empty_items(self):
        with self.assertRaises(ValidationError):
            OrderCreate(
                shop_id="shop-001",
                address_id="address-001",
                items=[],
            )

    def test_quantity_has_no_fixed_upper_limit(self):
        order = OrderCreate(
            shop_id="shop-001",
            address_id="address-001",
            items=[{"food_id": "food-001", "quantity": 1000}],
        )

        self.assertEqual(order.items[0].quantity, 1000)

    def test_rejects_raw_delivery_address(self):
        with self.assertRaises(ValidationError):
            OrderCreate(
                shop_id="shop-001",
                address_id="address-001",
                items=[{"food_id": "food-001", "quantity": 1}],
                delivery_address={
                    "province": "北京市",
                    "city": "北京市",
                    "district": "朝阳区",
                    "detail_address": "测试路1号",
                },
            )


if __name__ == "__main__":
    unittest.main()
