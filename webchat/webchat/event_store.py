"""事件存储：按会话分区 JSONL，先落盘再广播，seq 单调，支持重放。"""

from __future__ import annotations

__all__ = ["EventStore"]

import json
import threading
import time
from pathlib import Path


def _parse_line(line: bytes) -> dict | None:
    """解析单行事件；空行/坏行返回 None（与既有 replay 容错一致）。"""
    text = line.strip()
    if not text:
        return None
    try:
        return json.loads(text.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


class EventStore:
    """会话事件持久化与 seq 分配。"""

    def __init__(self, base_dir: Path | str):
        """初始化存储。

        Args:
            base_dir: 事件文件根目录（按会话 ID 分文件）。
        """
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._seqs: dict[str, int] = {}
        # 会话文件字节大小缓存：无新增事件时无需打开文件即可返回
        self._sizes: dict[str, int] = {}

    def _file(self, session_id: str) -> Path:
        return self.base_dir / f"{session_id}.jsonl"

    def append(self, session_id: str, event_type: str, payload: dict) -> dict:
        """分配 seq、落盘并返回完整事件字典。

        Args:
            session_id: 会话 ID。
            event_type: 事件类型。
            payload: 事件载荷。

        Returns:
            含 v/seq/session_id/ts/type/payload 的事件字典。
        """
        with self._lock:
            seq = self._seqs.get(session_id, 0) + 1
            self._seqs[session_id] = seq
        event = {
            "v": 1,
            "seq": seq,
            "session_id": session_id,
            "ts": time.time(),
            "type": event_type,
            "payload": payload,
        }
        line = json.dumps(event, ensure_ascii=False)
        path = self._file(session_id)
        with self._lock:
            with path.open("a", encoding="utf-8") as fp:
                fp.write(line + "\n")
            try:
                self._sizes[session_id] = path.stat().st_size
            except OSError:
                self._sizes.pop(session_id, None)
        return event

    def replay(self, session_id: str, after_seq: int = 0) -> list[dict]:
        """重放 seq 大于 after_seq 的全部事件（按序）。"""
        path = self._file(session_id)
        if not path.exists():
            return []
        events = []
        with path.open("r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("seq", 0) > after_seq:
                    events.append(event)
        return events

    def replay_with_offset(
        self, session_id: str, after_seq: int = 0
    ) -> tuple[list[dict], int]:
        """重放事件并返回当前文件字节偏移（SSE 建连起点）。

        读文件与取偏移在同一锁内完成，避免"重放结束后、记录偏移前"新增
        的事件被漏掉。文件不存在时返回 ``([], 0)``。
        """
        with self._lock:
            path = self._file(session_id)
            if not path.exists():
                return [], 0
            events: list[dict] = []
            offset = 0
            with path.open("rb") as fp:
                for raw in fp:
                    offset = fp.tell()
                    event = _parse_line(raw)
                    if event and event.get("seq", 0) > after_seq:
                        events.append(event)
            self._sizes[session_id] = offset
            return events, offset

    def read_after_offset(
        self, session_id: str, offset: int
    ) -> tuple[list[dict], int]:
        """从字节偏移读取**完整**新增行，返回 ``(events, new_offset)``。

        只处理末尾换行符之前的完整行；写入中的半行留待下次读取，避免
        解析到残缺 JSON。无新增时不改变偏移。
        """
        with self._lock:
            path = self._file(session_id)
            size = self._sizes.get(session_id)
            if size is None:
                try:
                    size = path.stat().st_size
                except OSError:
                    return [], offset
                self._sizes[session_id] = size
            if size <= offset:
                # 无新增：不打开文件（100 连接 × 2Hz 轮询的关键快路径）
                return [], offset
            try:
                with path.open("rb") as fp:
                    fp.seek(offset)
                    chunk = fp.read()
            except OSError:
                return [], offset
        if not chunk:
            return [], offset
        end = chunk.rfind(b"\n")
        if end < 0:
            return [], offset
        complete = chunk[: end + 1]
        events = [
            event for event in (
                _parse_line(raw) for raw in complete.splitlines()
            ) if event
        ]
        return events, offset + len(complete)

    def last_seq(self, session_id: str) -> int:
        """返回会话当前最大 seq。"""
        return self._seqs.get(session_id, 0)
