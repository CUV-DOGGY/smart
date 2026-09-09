import unittest
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.constants.order_status import OrderStatus
from app.core.exception_handlers import setup_exception_handlers
from app.dependencies.auth import get_current_user_id
from app.routers.order_router import (
    get_order_service,
    router as order_router,
)
from app.schemas.order import (
    OrderAttemptResult,
    OrderAttemptStatus,
    OrderQueryByIdData,
)
from app.services.order_service import OrderStateConflictError


class ConflictOrderService:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.idempotency_calls: list[tuple[str, str]] = []
        self.recovered_order: OrderQueryByIdData | None = OrderQueryByIdData(
            order_id="order-001",
            user_id="user-001",
            shop_id="shop-001",
            items=[
                {
                    "food_id": "food-001",
                    "food_name": "Test food",
                    "quantity": 1,
                    "price": 12.5,
                }
            ],
            order_status=OrderStatus.PENDING_PAYMENT,
            delivery_address="Test address",
            create_time=datetime(2026, 8, 28, tzinfo=timezone.utc),
            total_price=12.5,
        )

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

    async def query_order_attempt(
        self,
        idempotency_key: str,
        user_id: str,
    ) -> OrderAttemptResult:
        self.idempotency_calls.append((idempotency_key, user_id))
        return OrderAttemptResult(
            status=(
                OrderAttemptStatus.SUCCEEDED
                if self.recovered_order
                else OrderAttemptStatus.NOT_FOUND
            ),
            order=self.recovered_order,
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

    def test_recovers_order_by_idempotency_key_for_current_user(self):
        response = self.client.get(
            "/orders/by-idempotency-key",
            headers={"Idempotency-Key": "web-checkout-001"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "succeeded")
        self.assertEqual(response.json()["order"]["order_id"], "order-001")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(
            self.service.idempotency_calls,
            [("web-checkout-001", "user-001")],
        )

    def test_missing_idempotency_result_is_explicit(self):
        self.service.recovered_order = None

        response = self.client.get(
            "/orders/by-idempotency-key",
            headers={"Idempotency-Key": "web-checkout-001"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "not_found")
        self.assertIsNone(response.json()["order"])


if __name__ == "__main__":
    unittest.main()
