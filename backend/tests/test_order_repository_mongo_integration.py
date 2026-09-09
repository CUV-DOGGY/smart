import os
import unittest
from uuid import uuid4

from pymongo import AsyncMongoClient

from app.constants.order_status import OrderStatus
from app.repositories.order_repository import OrderRepository

RUN_MONGO_INTEGRATION = os.getenv("RUN_MONGO_INTEGRATION") == "1"
TEST_MONGODB_URL = os.getenv(
    "TEST_MONGODB_URL",
    "mongodb://localhost:27017",
)
TEST_MONGODB_DB_NAME = os.getenv(
    "TEST_MONGODB_DB_NAME",
    "smart_customer_service_integration_test",
)


@unittest.skipUnless(
    RUN_MONGO_INTEGRATION,
    "set RUN_MONGO_INTEGRATION=1 to run real MongoDB tests",
)
class MongoOrderRepositoryIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        if not TEST_MONGODB_DB_NAME.endswith("_test"):
            self.fail("integration database name must end with '_test'")

        self.client = AsyncMongoClient(
            TEST_MONGODB_URL,
            serverSelectionTimeoutMS=2_000,
        )
        await self.client.admin.command("ping")

        self.db = self.client[TEST_MONGODB_DB_NAME]
        self.orders = self.db["orders"]
        self.repository = OrderRepository(self.db)
        self.order_id = f"integration-order-{uuid4().hex}"
        self.user_id = "integration-user-001"

        await self.orders.insert_one(
            {
                "order_id": self.order_id,
                "user_id": self.user_id,
                "order_status": OrderStatus.PREPARING.value,
            }
        )

    async def asyncTearDown(self):
        await self.orders.delete_one(
            {
                "order_id": self.order_id,
                "user_id": self.user_id,
            }
        )
        await self.client.close()

    async def test_stale_cancel_does_not_overwrite_delivery(self):
        observed_document = await self.orders.find_one(
            {
                "order_id": self.order_id,
                "user_id": self.user_id,
            }
        )
        self.assertEqual(
            observed_document["order_status"],
            OrderStatus.PREPARING.value,
        )

        merchant_update = await self.orders.update_one(
            {
                "order_id": self.order_id,
                "user_id": self.user_id,
                "order_status": OrderStatus.PREPARING.value,
            },
            {
                "$set": {
                    "order_status": OrderStatus.DELIVERING.value,
                }
            },
        )
        self.assertEqual(merchant_update.matched_count, 1)
        self.assertEqual(merchant_update.modified_count, 1)

        cancel_succeeded = await self.repository.cancel_order(
            self.order_id,
            self.user_id,
            expected_status=observed_document["order_status"],
            target_status=OrderStatus.CANCELING.value,
        )

        final_document = await self.orders.find_one(
            {
                "order_id": self.order_id,
                "user_id": self.user_id,
            }
        )

        self.assertFalse(cancel_succeeded)
        self.assertEqual(
            final_document["order_status"],
            OrderStatus.DELIVERING.value,
        )

    async def test_transaction_uses_pymongo_async_session(self):
        async def read_order(session):
            return await self.orders.find_one(
                {
                    "order_id": self.order_id,
                    "user_id": self.user_id,
                },
                session=session,
            )

        document = await self.repository.run_in_transaction(read_order)

        self.assertIsNotNone(document)
        self.assertEqual(document["order_id"], self.order_id)


if __name__ == "__main__":
    unittest.main()
