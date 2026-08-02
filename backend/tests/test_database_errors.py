import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pymongo.errors import ServerSelectionTimeoutError

from app.core.database_errors import DatabaseUnavailableError
from app.core.exception_handlers import setup_exception_handlers
from app.repositories.order_repository import OrderRepository


class OrderRepositoryDatabaseErrorTests(unittest.IsolatedAsyncioTestCase):
    def make_repository(self):
        collection = MagicMock()
        db = MagicMock()
        db.__getitem__.return_value = collection
        return OrderRepository(db), collection

    async def test_idempotency_lookup_preserves_mongo_failure_as_cause(self):
        repository, collection = self.make_repository()
        mongo_error = ServerSelectionTimeoutError("server unavailable")
        collection.find_one = AsyncMock(side_effect=mongo_error)

        with self.assertRaises(DatabaseUnavailableError) as raised:
            await repository.find_by_idempotency_key(
                user_id="user-001",
                idempotency_key="checkout-test-001",
            )

        self.assertIs(raised.exception.__cause__, mongo_error)

    async def test_transaction_preserves_mongo_failure_as_cause(self):
        repository, collection = self.make_repository()
        mongo_error = ServerSelectionTimeoutError("server unavailable")
        collection.database.client.start_session = AsyncMock(
            side_effect=mongo_error
        )

        with self.assertRaises(DatabaseUnavailableError) as raised:
            await repository.run_in_transaction(AsyncMock())

        self.assertIs(raised.exception.__cause__, mongo_error)


class DatabaseUnavailableHandlerTests(unittest.TestCase):
    def make_app(self, exception):
        app = FastAPI()
        setup_exception_handlers(app)

        @app.get("/database-dependent")
        async def database_dependent():
            raise exception

        return app

    def test_project_error_returns_503_and_logs_traceback_once(self):
        app = self.make_app(
            DatabaseUnavailableError("database temporarily unavailable")
        )

        with patch(
            "app.core.exception_handlers.logger.exception"
        ) as log_exception:
            response = TestClient(app).get("/database-dependent")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {
                "detail": {
                    "code": "DATABASE_UNAVAILABLE",
                    "message": "数据库暂时不可用，请稍后重试",
                }
            },
        )
        self.assertEqual(response.headers["Retry-After"], "1")
        log_exception.assert_called_once()

    def test_raw_mongo_connection_failure_uses_same_503_fallback(self):
        app = self.make_app(
            ServerSelectionTimeoutError("server unavailable")
        )

        with patch(
            "app.core.exception_handlers.logger.exception"
        ) as log_exception:
            response = TestClient(app).get("/database-dependent")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["detail"]["code"],
            "DATABASE_UNAVAILABLE",
        )
        log_exception.assert_called_once()


if __name__ == "__main__":
    unittest.main()
