import asyncio
import threading
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from jwt.exceptions import InvalidTokenError
from pydantic import ValidationError

from app.config import settings
from app.core.auth_policy import normalize_username
from app.core.client_ip import get_client_ip
from app.core.middleware import AuthRequestBodyLimitMiddleware
from app.core.lifespan import lifespan
from app.core.security import (
    PASSWORD_HASH_MAX_CONCURRENCY,
    PasswordHashCapacityError,
    create_access_token,
    decode_access_token,
    get_dummy_password_hash,
    hash_password,
    initialize_password_security,
    password_hash,
    verify_password,
)
from app.schemas.auth import RegisterRequest
from app.schemas.conversation import ChatStreamRequest
from app.schemas.order import OrderCancelRequest, OrderCreate
from app.services.auth_service import AuthService, AuthenticationError
from app.services.auth_rate_limiter import AuthRateLimiter, RateLimitExceeded


class FakeAuthRepository:
    def __init__(self):
        self.users_by_username: dict[str, dict] = {}
        self.users_by_id: dict[str, dict] = {}

    async def create_user(self, user_data: dict) -> None:
        stored_user = user_data.copy()
        self.users_by_username[stored_user["username"]] = stored_user
        self.users_by_id[stored_user["user_id"]] = stored_user

    async def find_by_username(self, username: str) -> dict | None:
        return self.users_by_username.get(username)

    async def find_by_user_id(self, user_id: str) -> dict | None:
        return self.users_by_id.get(user_id)


class FakeRedis:
    def __init__(self):
        self.counts: dict[str, int] = {}

    async def eval(self, script: str, number_of_keys: int, key: str, window: int):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def delete(self, key: str):
        return self.counts.pop(key, None) is not None


class SecurityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await initialize_password_security()

    async def test_password_is_hashed_and_can_be_verified(self):
        plain_password = "correct-password"
        stored_hash = await hash_password(plain_password)

        self.assertNotEqual(stored_hash, plain_password)
        self.assertTrue(await verify_password(plain_password, stored_hash))
        self.assertFalse(await verify_password("wrong-password", stored_hash))

    async def test_password_hash_concurrency_is_five(self):
        self.assertEqual(PASSWORD_HASH_MAX_CONCURRENCY, 5)

        active_hashes = 0
        maximum_active_hashes = 0
        counter_lock = threading.Lock()

        def instrumented_hash(_: str) -> str:
            nonlocal active_hashes, maximum_active_hashes
            with counter_lock:
                active_hashes += 1
                maximum_active_hashes = max(
                    maximum_active_hashes,
                    active_hashes,
                )
            time.sleep(0.05)
            with counter_lock:
                active_hashes -= 1
            return "instrumented-hash"

        with patch.object(
            password_hash,
            "hash",
            side_effect=instrumented_hash,
        ):
            await asyncio.gather(
                *(hash_password(str(index)) for index in range(12))
            )

        self.assertEqual(maximum_active_hashes, 5)

    async def test_password_hash_wait_queue_times_out(self):
        semaphore = asyncio.Semaphore(PASSWORD_HASH_MAX_CONCURRENCY)
        for _ in range(PASSWORD_HASH_MAX_CONCURRENCY):
            await semaphore.acquire()

        try:
            with (
                patch("app.core.security._password_hash_semaphore", semaphore),
                patch.object(
                    settings,
                    "PASSWORD_HASH_WAIT_TIMEOUT_SECONDS",
                    0.01,
                ),
            ):
                with self.assertRaises(PasswordHashCapacityError):
                    await hash_password("will-not-enter-the-thread-pool")
        finally:
            for _ in range(PASSWORD_HASH_MAX_CONCURRENCY):
                semaphore.release()

    def test_access_token_round_trip(self):
        token = create_access_token("user-001")
        self.assertEqual(decode_access_token(token), "user-001")

    def test_tampered_access_token_is_rejected(self):
        token = create_access_token("user-001")
        replacement = "a" if token[-1] != "a" else "b"
        tampered_token = f"{token[:-1]}{replacement}"

        with self.assertRaises(InvalidTokenError):
            decode_access_token(tampered_token)


class AuthServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await initialize_password_security()
        self.repository = FakeAuthRepository()
        self.service = AuthService(self.repository)

    async def test_register_then_login(self):
        registered = await self.service.register(
            RegisterRequest(
                username="XiaoMing",
                password="correct-password",
            )
        )

        stored_user = self.repository.users_by_username["xiaoming"]
        self.assertEqual(registered.username, "xiaoming")
        self.assertNotEqual(
            stored_user["password_hash"],
            "correct-password",
        )

        token_response = await self.service.login(
            username="xiaoming",
            password="correct-password",
        )
        self.assertEqual(
            decode_access_token(token_response.access_token),
            registered.user_id,
        )

    async def test_wrong_password_is_rejected(self):
        await self.service.register(
            RegisterRequest(
                username="xiaoming",
                password="correct-password",
            )
        )

        with self.assertRaises(AuthenticationError):
            await self.service.login(
                username="xiaoming",
                password="wrong-password",
            )

    async def test_missing_username_still_verifies_dummy_argon2_hash(self):
        verifier = AsyncMock(return_value=False)

        with patch(
            "app.services.auth_service.verify_password",
            verifier,
        ):
            with self.assertRaises(AuthenticationError):
                await self.service.login(
                    username="missing-user",
                    password="wrong-password",
                )

        verifier.assert_awaited_once_with(
            "wrong-password",
            get_dummy_password_hash(),
        )

    async def test_oversized_login_password_uses_bounded_dummy_input(self):
        oversized_password = "x" * 10_000
        verifier = AsyncMock(return_value=False)

        with patch("app.services.auth_service.verify_password", verifier):
            with self.assertRaises(AuthenticationError):
                await self.service.login(
                    username="missing-user",
                    password=oversized_password,
                )

        submitted_password, submitted_hash = verifier.await_args.args
        self.assertLess(len(submitted_password), 128)
        self.assertEqual(submitted_hash, get_dummy_password_hash())


class AuthRateLimiterTests(unittest.IsolatedAsyncioTestCase):
    async def test_single_ip_limit_blocks_many_usernames(self):
        limiter = AuthRateLimiter(
            FakeRedis(),
            login_ip_limit=2,
            login_username_limit=10,
            login_window_seconds=300,
        )

        await limiter.check_login(client_ip="127.0.0.1", username="user-1")
        await limiter.check_login(client_ip="127.0.0.1", username="user-2")

        with self.assertRaises(RateLimitExceeded):
            await limiter.check_login(client_ip="127.0.0.1", username="user-3")

    async def test_single_username_limit_blocks_many_ips(self):
        limiter = AuthRateLimiter(
            FakeRedis(),
            login_ip_limit=10,
            login_username_limit=2,
            login_window_seconds=300,
        )

        await limiter.check_login(client_ip="127.0.0.1", username="xiaoming")
        await limiter.check_login(client_ip="127.0.0.2", username="XIAOMING")

        with self.assertRaises(RateLimitExceeded):
            await limiter.check_login(client_ip="127.0.0.3", username="xiaoming")

    async def test_global_limit_blocks_rotating_ip_and_username(self):
        limiter = AuthRateLimiter(
            FakeRedis(),
            login_global_limit=2,
            login_ip_limit=10,
            login_username_limit=10,
            login_window_seconds=300,
        )

        await limiter.check_login(client_ip="127.0.0.1", username="user-1")
        await limiter.check_login(client_ip="127.0.0.2", username="user-2")

        with self.assertRaises(RateLimitExceeded):
            await limiter.check_login(client_ip="127.0.0.3", username="user-3")

    async def test_registration_limits_single_username_across_ips(self):
        limiter = AuthRateLimiter(
            FakeRedis(),
            register_ip_limit=10,
            register_username_limit=2,
            register_window_seconds=300,
        )

        await limiter.check_registration(
            client_ip="127.0.0.1",
            username="XiaoMing",
        )
        await limiter.check_registration(
            client_ip="127.0.0.2",
            username="XIAOMING",
        )

        with self.assertRaises(RateLimitExceeded):
            await limiter.check_registration(
                client_ip="127.0.0.3",
                username="xiaoming",
            )

    async def test_rate_limit_keys_do_not_contain_raw_identity(self):
        redis = FakeRedis()
        limiter = AuthRateLimiter(redis, key_secret="s" * 32)

        await limiter.check_login(
            client_ip="203.0.113.10",
            username="SensitiveUser",
        )

        serialized_keys = " ".join(redis.counts)
        self.assertNotIn("203.0.113.10", serialized_keys)
        self.assertNotIn("sensitiveuser", serialized_keys)


class AuthInputPolicyTests(unittest.TestCase):
    def test_username_normalization_is_shared(self):
        self.assertEqual(normalize_username("  XiaoMing  "), "xiaoming")
        request = RegisterRequest(
            username="  XiaoMing  ",
            password="correct-password",
        )
        self.assertEqual(
            request.username,
            "xiaoming",
        )

    def test_username_cannot_become_too_short_after_trimming(self):
        with self.assertRaises(ValidationError):
            RegisterRequest(username="  a  ", password="correct-password")


class ClientIpTests(unittest.TestCase):
    @staticmethod
    def _request(peer_ip: str, forwarded_for: str | None = None) -> Request:
        headers = []
        if forwarded_for is not None:
            headers.append((b"x-forwarded-for", forwarded_for.encode("ascii")))
        return Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/auth/login",
                "headers": headers,
                "client": (peer_ip, 12345),
            }
        )

    def test_untrusted_peer_cannot_spoof_forwarded_ip(self):
        request = self._request("198.51.100.8", "203.0.113.9")
        self.assertEqual(get_client_ip(request, ["10.0.0.0/8"]), "198.51.100.8")

    def test_trusted_proxy_chain_returns_first_untrusted_ip(self):
        request = self._request("10.0.0.2", "203.0.113.9, 10.0.0.1")
        self.assertEqual(get_client_ip(request, ["10.0.0.0/8"]), "203.0.113.9")


class AuthBodyLimitTests(unittest.TestCase):
    def test_auth_request_body_is_rejected_before_parsing(self):
        app = FastAPI()
        app.add_middleware(AuthRequestBodyLimitMiddleware, max_body_bytes=32)

        @app.post("/auth/read-body")
        async def read_body(request: Request):
            return {"size": len(await request.body())}

        with TestClient(app) as client:
            response = client.post("/auth/read-body", content=b"x" * 33)

        self.assertEqual(response.status_code, 413)

    def test_chunked_auth_request_is_also_rejected(self):
        async def run_scenario() -> int:
            async def inner_app(scope, receive, send):
                raise AssertionError("oversized body reached the application")

            middleware = AuthRequestBodyLimitMiddleware(
                inner_app,
                max_body_bytes=32,
            )
            incoming = iter(
                [
                    {
                        "type": "http.request",
                        "body": b"x" * 20,
                        "more_body": True,
                    },
                    {
                        "type": "http.request",
                        "body": b"x" * 20,
                        "more_body": False,
                    },
                ]
            )
            sent_messages = []

            async def receive():
                return next(incoming)

            async def send(message):
                sent_messages.append(message)

            await middleware(
                {
                    "type": "http",
                    "method": "POST",
                    "path": "/auth/login",
                    "headers": [],
                },
                receive,
                send,
            )
            return sent_messages[0]["status"]

        self.assertEqual(asyncio.run(run_scenario()), 413)


class LifespanTests(unittest.IsolatedAsyncioTestCase):
    async def test_mongo_is_closed_when_startup_fails_after_connection(self):
        mongo_client = MagicMock()

        with (
            patch(
                "app.core.lifespan.startup_db",
                AsyncMock(return_value=(mongo_client, MagicMock())),
            ),
            patch(
                "app.repositories.auth_repository.AuthRepository.ensure_indexes",
                AsyncMock(side_effect=RuntimeError("index failure")),
            ),
        ):
            with self.assertRaises(RuntimeError):
                async with lifespan(FastAPI()):
                    pass

        mongo_client.close.assert_called_once_with()


class TrustedIdentitySchemaTests(unittest.TestCase):
    def test_clients_cannot_submit_user_id(self):
        self.assertNotIn("user_id", OrderCreate.model_fields)
        self.assertNotIn("user_id", OrderCancelRequest.model_fields)
        self.assertNotIn("user_id", ChatStreamRequest.model_fields)


if __name__ == "__main__":
    unittest.main()
