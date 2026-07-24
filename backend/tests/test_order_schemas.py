import unittest

from pydantic import ValidationError

from app.schemas.order import OrderCreate


class OrderCreateSchemaTests(unittest.TestCase):
    def test_accepts_single_shop_items_without_client_prices(self):
        order = OrderCreate(
            shop_id="shop-001",
            items=[
                {"food_id": "food-001", "quantity": 2},
                {"food_id": "food-002", "quantity": 1},
            ],
            delivery_address="北京市朝阳区",
        )

        self.assertEqual(order.shop_id, "shop-001")
        self.assertEqual(len(order.items), 2)

    def test_rejects_client_controlled_item_price_and_name(self):
        with self.assertRaises(ValidationError):
            OrderCreate(
                shop_id="shop-001",
                items=[
                    {
                        "food_id": "food-001",
                        "food_name": "伪造商品名",
                        "quantity": 1,
                        "price": 0,
                    }
                ],
                delivery_address="北京市朝阳区",
            )

    def test_rejects_empty_items(self):
        with self.assertRaises(ValidationError):
            OrderCreate(
                shop_id="shop-001",
                items=[],
                delivery_address="北京市朝阳区",
            )

    def test_quantity_has_no_fixed_upper_limit(self):
        order = OrderCreate(
            shop_id="shop-001",
            items=[{"food_id": "food-001", "quantity": 1000}],
            delivery_address="北京市朝阳区",
        )

        self.assertEqual(order.items[0].quantity, 1000)


if __name__ == "__main__":
    unittest.main()
