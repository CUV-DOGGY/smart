# 负责统一的插件的启动和停止的管理

from collections.abc import Iterable

from app.plugins.base import Plugin
from app.plugins.context import PluginContext


class PluginManager:
    def __init__(self, plugins: Iterable[Plugin]) -> None:
        self._plugins = list(plugins)
        self._started_plugins: list[Plugin] = []

    async def start(self, context: PluginContext) -> None:
        for plugin in self._plugins:
            await plugin.start(context)
            self._started_plugins.append(plugin)

    async def stop(self) -> None:
        for plugin in reversed(self._started_plugins):
            await plugin.stop()

        self._started_plugins.clear()
