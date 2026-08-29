import os
import unittest

import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from pymongo import AsyncMongoClient

from app.config import settings
from app.integrations.llm import create_llm
from app.repositories.product_repository import ProductRepository
from app.repositories.shop_repository import ShopRepository
from app.services.catalog_service import CatalogService
from app.tools.service_tools import SPECS, ServiceToolRegistry


RUN_INTEGRATION = os.getenv("RUN_LLM_INTEGRATION") == "1"


@unittest.skipUnless(
    RUN_INTEGRATION,
    "set RUN_LLM_INTEGRATION=1 for the authorized read-only model check",
)
class LiveLlmIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_deepseek_requests_and_executes_one_read_only_service_tool(self):
        self.assertEqual(settings.MODEL_NAME, "deepseek-v4-flash")
        client = AsyncMongoClient(settings.MONGODB_URL)
        try:
            catalog = CatalogService(
                ShopRepository(client[settings.MONGODB_DB_NAME]),
                ProductRepository(client[settings.MONGODB_DB_NAME]),
            )
            registry = ServiceToolRegistry(
                catalog_service=catalog,
                address_service=object(),
                order_service=object(),
            )
            async with httpx.AsyncClient(trust_env=False) as http_client:
                model = create_llm(http_async_client=http_client).bind_tools(
                    [SPECS["list_shops"].openai_schema()],
                )
                response = await model.ainvoke([
                    SystemMessage(content="必须调用 list_shops，只允许执行只读查询。"),
                    HumanMessage(content="请列出当前可用店铺。"),
                ])
            self.assertEqual(len(response.tool_calls), 1)
            call = response.tool_calls[0]
            self.assertEqual(call["name"], "list_shops")
            result = await registry.execute(
                call["name"],
                call.get("args", {}),
                user_id="llm-read-only-check",
                action_id="read-only-no-side-effect",
            )
            self.assertTrue(result["ok"])
            self.assertIn("items", result)
        finally:
            await client.close()


if __name__ == "__main__":
    unittest.main()
