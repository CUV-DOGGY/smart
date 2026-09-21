import json
import os
import unittest

import httpx
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import settings
from app.core.lifespan import shutdown_plugins, startup_plugins
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
    async def test_deepseek_calls_business_hours_plugin_end_to_end(self):
        plugin_manager, plugin_tools = await startup_plugins()
        try:
            async with httpx.AsyncClient(trust_env=False) as http_client:
                model = create_llm(http_async_client=http_client)
                tool_model = model.bind_tools(
                    plugin_tools.definitions(),
                    tool_choice="get_customer_service_hours",
                )
                messages = [
                    SystemMessage(content="必须调用营业时间工具回答问题。"),
                    HumanMessage(content="现在人工客服营业吗？"),
                ]
                response = await tool_model.ainvoke(messages)
                self.assertEqual(len(response.tool_calls), 1)
                call = response.tool_calls[0]
                normalized, _ = plugin_tools.validate(
                    call["name"],
                    call.get("args", {}),
                )
                result = await plugin_tools.execute(call["name"], normalized)
                final = await model.ainvoke([
                    *messages,
                    response,
                    ToolMessage(
                        content=json.dumps(result, ensure_ascii=False),
                        tool_call_id=call["id"],
                    ),
                ])

            self.assertEqual(call["name"], "get_customer_service_hours")
            self.assertIsInstance(result["is_open"], bool)
            self.assertTrue(str(final.content).strip())
        finally:
            await shutdown_plugins(plugin_manager)

    async def test_deepseek_requests_and_executes_one_read_only_service_tool(self):
        self.assertEqual(settings.MODEL_NAME, "deepseek-v4-flash")
        client = AsyncIOMotorClient(settings.MONGODB_URL)
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
                    tool_choice="list_shops",
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
            client.close()


if __name__ == "__main__":
    unittest.main()
