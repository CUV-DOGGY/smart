from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

ToolHandler = Callable[
    [dict[str, Any]],
    Awaitable[dict[str, Any]],
]


class PluginToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoArguments(PluginToolArguments):
    pass


class ToolAlreadyRegisteredError(RuntimeError):
    """工具名称已经被占用。"""


class ToolNotFoundError(RuntimeError):
    """指定工具不存在。"""


class ToolArgumentsValidationError(RuntimeError):
    """工具参数不符合已注册的参数模型。"""


@dataclass(frozen=True)
class RegisteredTool:
    name: str
    description: str
    handler: ToolHandler
    arguments_model: type[PluginToolArguments]

    def openai_schema(self) -> dict[str, Any]:
        parameters = self.arguments_model.model_json_schema()
        parameters.pop("title", None)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": parameters,
            },
        }


class PluginToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(
        self,
        *,
        name: str,
        description: str,
        handler: ToolHandler,
        arguments_model: type[PluginToolArguments] = NoArguments,
    ) -> None:
        if name in self._tools:
            raise ToolAlreadyRegisteredError(f"Tool is already registered: {name}")

        self._tools[name] = RegisteredTool(
            name=name,
            description=description,
            handler=handler,
            arguments_model=arguments_model,
        )

    def unregister(self, name: str) -> bool:
        return self._tools.pop(name, None) is not None

    def has(self, name: str) -> bool:
        return name in self._tools

    def definitions(self) -> list[dict[str, Any]]:
        return [tool.openai_schema() for tool in self._tools.values()]

    def validate(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        if name not in self._tools:
            raise ToolNotFoundError(f"Tool is not registered: {name}")
        tool = self._tools[name]
        try:
            normalized = tool.arguments_model.model_validate(arguments).model_dump(
                exclude_none=True,
                mode="json",
            )
        except ValidationError as exc:
            raise ToolArgumentsValidationError("INVALID_TOOL_ARGUMENTS") from exc
        return normalized, []

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        tool = self._tools.get(name)

        if tool is None:
            raise ToolNotFoundError(f"Tool is not registered: {name}")

        return await tool.handler(arguments)
