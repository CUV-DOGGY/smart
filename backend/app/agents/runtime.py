from dataclasses import dataclass
from typing import Any

from app.tools.service_tools import ServiceToolRegistry


@dataclass(frozen=True)
class AgentRuntimeContext:
    user_id: str
    llm: Any
    tools: ServiceToolRegistry
    command_service: Any = None
    conversation_id: str = ""
