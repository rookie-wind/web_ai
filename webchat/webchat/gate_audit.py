"""门禁审计台账：confirm/allow/deny 决策的持久化 JSONL 追加。

独立于会话生命周期——会话结束不清理，供验收举证与汇报引用。
与 EventStore 区分：事件流按会话分区、随会话回放；审计台账全局单文件、
只追加不重放。
"""

from __future__ import annotations

__all__ = ["GateAuditLog"]

import json
import threading
from pathlib import Path


class GateAuditLog:
    """门禁决策审计台账（全局单 JSONL 文件，线程安全追加）。"""

    def __init__(self, path: Path | str):
        """初始化台账。

        Args:
            path: 审计 JSONL 文件路径（父目录自动创建）。
        """
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def append(self, entry: dict) -> None:
        """追加一条审计记录。

        Args:
            entry: 至少含 ts/session_id/target/tool_name/decision/reason。
        """
        line = json.dumps(entry, ensure_ascii=False)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as fp:
                fp.write(line + "\n")

    def read_all(self) -> list[dict]:
        """读取全部审计记录（举证/测试用）。"""
        if not self.path.exists():
            return []
        entries: list[dict] = []
        with self.path.open("r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return entries
