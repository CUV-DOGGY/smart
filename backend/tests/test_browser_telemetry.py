import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.core.exception_handlers import setup_exception_handlers
from app.core.middleware import RequestIdMiddleware
from app.dependencies.auth import get_current_user_id
from app.routers.telemetry_router import (
    get_telemetry_rate_limiter,
    router,
)
from app.services.telemetry_rate_limiter import TelemetryRateLimitExceeded


class FakeRateLimiter:
    def __init__(self, error=None):
        self.error = error
        self.user_ids = []

    async def check(self, user_id: str) -> None:
        self.user_ids.append(user_id)
        if self.error:
            raise self.error


class BrowserTelemetryEndpointTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.add_middleware(RequestIdMiddleware)
        setup_exception_handlers(self.app)
        self.app.include_router(router)
        self.rate_limiter = FakeRateLimiter()
        self.app.dependency_overrides[get_current_user_id] = lambda: "user-1"
        self.app.dependency_overrides[get_telemetry_rate_limiter] = (
            lambda: self.rate_limiter
        )
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()

    def _post(self, **kwargs):
        headers = {
            "Origin": "https://app.example.com",
            "Content-Type": "application/x-protobuf",
        }
        headers.update(kwargs.pop("headers", {}))
        return self.client.post(
            "/telemetry/v1/traces",
            content=b"otel-payload",
            headers=headers,
            **kwargs,
        )

    @patch("app.routers.telemetry_router._forward_traces", new_callable=AsyncMock)
    def test_authenticated_allowed_origin_is_forwarded(self, forward):
        with (
            patch.object(settings, "BROWSER_TELEMETRY_ENABLED", True),
            patch.object(
                settings,
                "BROWSER_TELEMETRY_ALLOWED_ORIGINS",
                ["https://app.example.com"],
            ),
        ):
            response = self._post()

        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.rate_limiter.user_ids, ["user-1"])
        forward.assert_awaited_once_with(
            b"otel-payload",
            content_type="application/x-protobuf",
            content_encoding="",
        )

    @patch("app.routers.telemetry_router._forward_traces", new_callable=AsyncMock)
    def test_missing_bearer_token_is_rejected(self, forward):
        del self.app.dependency_overrides[get_current_user_id]
        self.app.state.db = object()
        with (
            patch.object(settings, "BROWSER_TELEMETRY_ENABLED", True),
            patch.object(
                settings,
                "BROWSER_TELEMETRY_ALLOWED_ORIGINS",
                ["https://app.example.com"],
            ),
        ):
            response = self._post()

        self.assertEqual(response.status_code, 401)
        forward.assert_not_awaited()

    @patch("app.routers.telemetry_router._forward_traces", new_callable=AsyncMock)
    def test_untrusted_origin_is_rejected_before_forwarding(self, forward):
        with (
            patch.object(settings, "BROWSER_TELEMETRY_ENABLED", True),
            patch.object(
                settings,
                "BROWSER_TELEMETRY_ALLOWED_ORIGINS",
                ["https://trusted.example.com"],
            ),
        ):
            response = self._post()

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "TELEMETRY_ORIGIN_DENIED")
        forward.assert_not_awaited()

    @patch("app.routers.telemetry_router._forward_traces", new_callable=AsyncMock)
    def test_rate_limit_returns_retry_after(self, forward):
        self.rate_limiter.error = TelemetryRateLimitExceeded(60)
        with (
            patch.object(settings, "BROWSER_TELEMETRY_ENABLED", True),
            patch.object(
                settings,
                "BROWSER_TELEMETRY_ALLOWED_ORIGINS",
                ["https://app.example.com"],
            ),
        ):
            response = self._post()

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["Retry-After"], "60")
        forward.assert_not_awaited()

    @patch("app.routers.telemetry_router._forward_traces", new_callable=AsyncMock)
    def test_oversized_payload_is_rejected(self, forward):
        with (
            patch.object(settings, "BROWSER_TELEMETRY_ENABLED", True),
            patch.object(
                settings,
                "BROWSER_TELEMETRY_ALLOWED_ORIGINS",
                ["https://app.example.com"],
            ),
            patch.object(
                settings,
                "BROWSER_TELEMETRY_MAX_REQUEST_BODY_BYTES",
                4,
            ),
        ):
            response = self._post()

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["code"], "TELEMETRY_PAYLOAD_TOO_LARGE")
        forward.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
