"""自有事件契约 v1 的数据类型。

SDK 类型不得出现在本模块之外；业务层与前端只认这些事件。
"""

from __future__ import annotations

__all__ = ["EVENT_TYPES", "WEvent"]

from dataclasses import dataclass, field
from typing import Any

EVENT_TYPES = (
    "session_started",
    "text_delta",
    "tool_call",
    "tool_result",
    "ask_user",
    "gate_blocked",
    "artifact",
    "upload_text",
    "turn_aborted",
    "turn_done",
    "session_closed",
    "error",
    "unknown",
)


@dataclass
class WEvent:
    """自有事件契约 v1 事件。"""

    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    session_id: str = ""
    seq: int = 0
    ts: float = 0.0

    def to_dict(self) -> dict:
        """序列化为对外契约结构（v=1）。"""
        return {
            "v": 1,
            "seq": self.seq,
            "session_id": self.session_id,
            "ts": self.ts,
            "type": self.type,
            "payload": self.payload,
        }
