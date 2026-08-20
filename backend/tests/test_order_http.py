import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.constants.order_status import OrderStatus
from app.core.exception_handlers import setup_exception_handlers
from app.dependencies.auth import get_current_user_id
from app.routers.order_router import (
    get_order_service,
    router as order_router,
)
from app.services.order_service import OrderStateConflictError


class ConflictOrderService:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    async def cancel_order(
        self,
        order_id: str,
        user_id: str,
    ):
        self.calls.append((order_id, user_id))
        raise OrderStateConflictError(
            "Order status changed; cancellation was rejected",
            current_status=OrderStatus.DELIVERING,
        )


class OrderCancelHttpTests(unittest.TestCase):
    def setUp(self):
        self.service = ConflictOrderService()

        app = FastAPI()
        setup_exception_handlers(app)
        app.include_router(order_router)
        app.dependency_overrides[get_order_service] = lambda: self.service
        app.dependency_overrides[get_current_user_id] = lambda: "user-001"

        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()

    def test_cancel_conflict_returns_latest_status(self):
        response = self.client.post(
            "/orders/order-001/cancel",
        )

        self.assertEqual(response.status_code, 409)
        body = response.json()
        self.assertEqual(body["code"], "ORDER_STATE_CONFLICT")
        self.assertEqual(body["message"], "当前订单状态无法取消")
        self.assertEqual(body["field_errors"], [])
        self.assertTrue(body["request_id"])
        self.assertEqual(
            self.service.calls,
            [("order-001", "user-001")],
        )


if __name__ == "__main__":
    unittest.main()
