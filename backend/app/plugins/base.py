# 本文件用于定义什么样的对象能够称为插件
from typing import Protocol
from app.plugins.context import PluginContext


class Plugin(Protocol):
    name: str

    async def start(self, context: PluginContext) -> None:
        "主体启动插件时使用"
        ...

    async def stop(self) -> None:
        "主体停止插件时使用"
        ...
