import unittest

from jwt.exceptions import InvalidTokenError

from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.schemas.auth import RegisterRequest
from app.schemas.chat import ChatRequest
from app.schemas.order import OrderCancelRequest, OrderCreate
from app.services.auth_service import AuthService, AuthenticationError


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


class SecurityTests(unittest.TestCase):
    def test_password_is_hashed_and_can_be_verified(self):
        plain_password = "correct-password"
        stored_hash = hash_password(plain_password)

        self.assertNotEqual(stored_hash, plain_password)
        self.assertTrue(verify_password(plain_password, stored_hash))
        self.assertFalse(verify_password("wrong-password", stored_hash))

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


class TrustedIdentitySchemaTests(unittest.TestCase):
    def test_clients_cannot_submit_user_id(self):
        self.assertNotIn("user_id", OrderCreate.model_fields)
        self.assertNotIn("user_id", OrderCancelRequest.model_fields)
        self.assertNotIn("user_id", ChatRequest.model_fields)


if __name__ == "__main__":
    unittest.main()
