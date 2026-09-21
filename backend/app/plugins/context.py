# 定义主体运行插件能够使用什么能力

from dataclasses import dataclass
from logging import Logger

from app.plugins.tools import PluginToolRegistry


@dataclass(frozen=True)
class PluginContext:
    logger: Logger
    tools: PluginToolRegistry
