import unittest
from typing import Any

from pydantic import Field

from app.plugins import (
    PluginToolArguments,
    PluginToolRegistry,
    ToolAlreadyRegisteredError,
    ToolArgumentsValidationError,
    ToolNotFoundError,
)
from app.tools.service_tools import ServiceToolRegistry, ToolValidationFailure


class EchoArguments(PluginToolArguments):
    message: str = Field(min_length=1)


class PluginToolRegistryTests(unittest.IsolatedAsyncioTestCase):
    async def test_registers_and_executes_tool(self) -> None:
        registry = PluginToolRegistry()

        async def echo(
            arguments: dict[str, Any],
        ) -> dict[str, Any]:
            return {
                "received": arguments,
            }

        registry.register(
            name="echo",
            description="返回输入参数",
            handler=echo,
            arguments_model=EchoArguments,
        )

        result = await registry.execute(
            "echo",
            {
                "message": "你好",
            },
        )

        self.assertEqual(
            result,
            {
                "received": {
                    "message": "你好",
                }
            },
        )

    async def test_rejects_duplicate_tool_name(self) -> None:
        registry = PluginToolRegistry()

        async def handler(
            arguments: dict[str, Any],
        ) -> dict[str, Any]:
            return arguments

        registry.register(
            name="echo",
            description="第一个工具",
            handler=handler,
        )

        with self.assertRaises(ToolAlreadyRegisteredError):
            registry.register(
                name="echo",
                description="重复工具",
                handler=handler,
            )

    async def test_unregister_removes_tool(self) -> None:
        registry = PluginToolRegistry()

        async def handler(
            arguments: dict[str, Any],
        ) -> dict[str, Any]:
            return arguments

        registry.register(
            name="echo",
            description="测试工具",
            handler=handler,
        )

        removed = registry.unregister("echo")

        self.assertTrue(removed)
        self.assertFalse(registry.has("echo"))

        with self.assertRaises(ToolNotFoundError):
            await registry.execute("echo", {})

    async def test_exports_function_calling_schema(self) -> None:
        registry = PluginToolRegistry()

        async def handler(arguments: dict[str, Any]) -> dict[str, Any]:
            return arguments

        registry.register(
            name="echo",
            description="返回输入参数",
            handler=handler,
            arguments_model=EchoArguments,
        )

        definition = registry.definitions()[0]["function"]
        parameters = definition["parameters"]
        self.assertEqual(definition["name"], "echo")
        self.assertEqual(parameters["properties"]["message"]["type"], "string")
        self.assertEqual(parameters["required"], ["message"])
        self.assertFalse(parameters["additionalProperties"])

    async def test_validates_and_normalizes_arguments(self) -> None:
        registry = PluginToolRegistry()

        async def handler(arguments: dict[str, Any]) -> dict[str, Any]:
            return arguments

        registry.register(
            name="echo",
            description="返回输入参数",
            handler=handler,
            arguments_model=EchoArguments,
        )

        normalized, missing = registry.validate("echo", {"message": "你好"})
        self.assertEqual(normalized, {"message": "你好"})
        self.assertEqual(missing, [])

        with self.assertRaises(ToolArgumentsValidationError):
            registry.validate("echo", {"unexpected": "value"})

        service_registry = ServiceToolRegistry(
            catalog_service=object(),
            address_service=object(),
            order_service=object(),
            plugin_tools=registry,
        )
        with self.assertRaisesRegex(
            ToolValidationFailure,
            "INVALID_TOOL_ARGUMENTS",
        ):
            service_registry.validate_with_plugins("echo", {})

    async def test_service_registry_executes_plugin_tool(self) -> None:
        plugin_tools = PluginToolRegistry()

        async def handler(arguments: dict[str, Any]) -> dict[str, Any]:
            return {"ok": True, "arguments": arguments}

        plugin_tools.register(
            name="echo",
            description="返回输入参数",
            handler=handler,
        )
        registry = ServiceToolRegistry(
            catalog_service=object(),
            address_service=object(),
            order_service=object(),
            plugin_tools=plugin_tools,
        )

        result = await registry.execute(
            "echo",
            {"message": "你好"},
            user_id="user-001",
            action_id="action-001",
        )

        self.assertEqual(
            result,
            {"ok": True, "arguments": {"message": "你好"}},
        )


if __name__ == "__main__":
    unittest.main()
