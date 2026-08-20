import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.health_router import router


class HealthRouterTests(unittest.TestCase):
    def make_app(self) -> FastAPI:
        app = FastAPI()
        app.include_router(router)
        app.state.db = AsyncMock()
        app.state.db.command = AsyncMock(return_value={"ok": 1})
        app.state.redis = AsyncMock()
        app.state.redis.ping = AsyncMock(return_value=True)
        return app

    def test_liveness_does_not_require_dependencies(self):
        app = FastAPI()
        app.include_router(router)

        response = TestClient(app).get("/health/live")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_readiness_reports_all_dependencies(self):
        response = TestClient(self.make_app()).get("/health/ready")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": "ready",
                "components": {
                    "mongodb": "ok",
                    "redis": "ok",
                },
            },
        )

    def test_readiness_reports_mongodb_failure_without_internal_detail(self):
        app = self.make_app()
        app.state.db.command = AsyncMock(
            side_effect=RuntimeError("mongodb://secret-host")
        )

        with patch("app.routers.health_router.logger.warning"):
            response = TestClient(app).get("/health/ready")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["components"]["mongodb"], "unavailable")
        self.assertNotIn("secret-host", response.text)

    def test_readiness_reports_redis_failure_without_internal_detail(self):
        app = self.make_app()
        app.state.redis.ping = AsyncMock(
            side_effect=RuntimeError("redis://secret-host")
        )

        with patch("app.routers.health_router.logger.warning"):
            response = TestClient(app).get("/health/ready")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["components"]["redis"], "unavailable")
        self.assertNotIn("secret-host", response.text)


if __name__ == "__main__":
    unittest.main()
