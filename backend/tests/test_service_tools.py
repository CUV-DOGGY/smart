import unittest

from app.schemas.order import OrderConfirmationPreview
from app.tools.service_tools import ServiceToolRegistry


class PreviewOrderService:
    def __init__(self):
        self.calls = []

    async def preview_order(self, order, user_id):
        self.calls.append((order, user_id))
        return OrderConfirmationPreview(
            shop_id="shop-001",
            shop_name="测试店铺",
            address_id="address-001",
            receiver_name="测试用户",
            receiver_phone="13800138000",
            delivery_address="北京市朝阳区测试路1号",
            items=[{
                "food_id": "food-001",
                "food_name": "测试商品",
                "quantity": 2,
                "unit_price": 12.5,
                "line_total": 25.0,
            }],
            goods_amount=25.0,
            delivery_fee=5.0,
            total_price=30.0,
        )


class ServiceToolConfirmationTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_order_confirmation_is_safe_and_structured(self):
        order_service = PreviewOrderService()
        registry = ServiceToolRegistry(
            catalog_service=object(),
            address_service=object(),
            order_service=order_service,
        )

        result = await registry.prepare_confirmation(
            "create_order",
            {
                "shop_id": "shop-001",
                "address_id": "address-001",
                "items": [{"food_id": "food-001", "quantity": 2}],
            },
            user_id="user-001",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["presentation"]["kind"], "order")
        self.assertEqual(result["presentation"]["receiver_phone"], "138****8000")
        self.assertNotIn("user_id", result["presentation"])
        self.assertEqual(result["presentation"]["total_price"], 30.0)
        self.assertEqual(order_service.calls[0][1], "user-001")


if __name__ == "__main__":
    unittest.main()
