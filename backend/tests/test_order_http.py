import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.contants.order_status import OrderStatus
from app.dependencies.auth import get_current_user_id
from app.routers.order_router import (
    get_order_service,
    router as order_router,
)
from app.services.order_services import OrderStateConflictError


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
        app.include_router(order_router)
        app.dependency_overrides[get_order_service] = lambda: self.service
        app.dependency_overrides[get_current_user_id] = lambda: "user-001"

        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()

    def test_cancel_conflict_returns_latest_status(self):
        response = self.client.post(
            "/orders/cancel_order",
            json={"order_id": "order-001"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json(),
            {
                "detail": {
                    "code": "ORDER_STATE_CONFLICT",
                    "message": (
                        "Order status changed; cancellation was rejected"
                    ),
                    "order_status": "delivering",
                }
            },
        )
        self.assertEqual(
            self.service.calls,
            [("order-001", "user-001")],
        )


if __name__ == "__main__":
    unittest.main()
