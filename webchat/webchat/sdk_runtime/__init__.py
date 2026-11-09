"""SDK 适配层：qodercn_agent_sdk 的唯一 import 边界。

对外只暴露 AgentHandle / AdapterConfig / 自有事件契约类型；
SDK 类型与字段名不得出现在本包之外。
"""

from .adapter import AdapterConfig, AdapterError, AgentHandle, TurnAborted
from .events import EVENT_TYPES, WEvent
from .login_activation import ActivationError, call_login_tool

__all__ = [
    "AdapterConfig",
    "AdapterError",
    "AgentHandle",
    "TurnAborted",
    "EVENT_TYPES",
    "WEvent",
    "ActivationError",
    "call_login_tool",
]
