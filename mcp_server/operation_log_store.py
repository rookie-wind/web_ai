"""写操作日志存储。

按调用方身份（owner_id）分区记录服务端写操作（建档/下发/召测/登录等）的
操作名、脱敏入参/结果摘要、状态、耗时与 trace 会话窗，采用内存环形缓冲与
本地 ``.jsonl`` 追加落盘双存，供客户端凭接入 Token 定向回看"本次操作"日志。

落盘与 TTL 范式参考 archiving/task_report_store.py，脱敏复用
archiving/log_sanitizer.sanitize_report。
"""

from __future__ import annotations

__all__ = ["OperationLogEntry", "OperationLogStore", "default_store"]

import json
import os
import re
import secrets
import time
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from archiving.log_sanitizer import sanitize_report
from archiving.snapshot_store import derive_owner_id

# 仓库根目录（mcp_server 的上一级），日志默认落在此处项目内
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_TTL_DAYS = 7
DEFAULT_RING_CAPACITY = 200
# 平衡档：保留后端结果与错误详情、较完整入参；仅对超大报文与
# 超长字段截断（raw/request_body 已由 sanitize_report 剔除）。
MAX_SUMMARY_CHARS = 20000
_MAX_STR_LEN = 1000
_MAX_LIST_ITEMS = 100
_MAX_DICT_ITEMS = 200

_OWNER_RE = re.compile(r"^[0-9a-f]{64}$")


def _now() -> datetime:
    """返回当前 UTC 时间。"""
    return datetime.now(timezone.utc)


def _default_base_dir() -> Path:
    """返回默认操作日志目录（项目内 ``logs/`` 下，不写系统盘）。

    优先用环境变量 ``PCA_OPERATION_LOGS_DIR``；否则落在仓库根目录的
    ``logs/operation_logs``，避免写入用户主目录（C 盘）。
    """
    env = os.environ.get("PCA_OPERATION_LOGS_DIR", "")
    if env:
        return Path(env)
    return _PROJECT_ROOT / "logs" / "operation_logs"


def _shrink(value: Any) -> Any:
    """递归收缩摘要：截断长字符串、限制列表长度，保持结构可读。"""
    if isinstance(value, str):
        return value if len(value) <= _MAX_STR_LEN else value[:_MAX_STR_LEN] + "…"
    if isinstance(value, dict):
        return {str(k): _shrink(v) for k, v in list(value.items())[:_MAX_DICT_ITEMS]}
    if isinstance(value, (list, tuple)):
        return [_shrink(v) for v in list(value)[:_MAX_LIST_ITEMS]]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _shrink(str(value))


def _summarize(raw: Any, secrets: tuple[str, ...]) -> Any:
    """脱敏并收缩一份入参/结果摘要，控制序列化体积。"""
    if raw is None:
        return None
    sanitized = sanitize_report(raw, secrets)
    shrunk = _shrink(sanitized)
    try:
        text = json.dumps(shrunk, ensure_ascii=False)
    except (TypeError, ValueError):
        return {"_repr": str(shrunk)[:MAX_SUMMARY_CHARS]}
    if len(text) > MAX_SUMMARY_CHARS:
        return {"_truncated": text[:MAX_SUMMARY_CHARS]}
    return shrunk


@dataclass
class OperationLogEntry:
    """单条写操作日志。"""

    entry_id: str = ""
    seq: int = 0
    owner_id: str = ""
    trace_id: str = ""
    tool: str = ""
    source: str = "unknown"
    access_level: str = "user"
    status: str = "UNKNOWN"
    code: str = ""
    args_summary: Any = None
    result_summary: Any = None
    started_at: str = ""
    finished_at: str = ""
    duration_ms: int = 0
    created_at: str = ""

    def to_dict(self) -> dict:
        """序列化为字典。"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "OperationLogEntry":
        """从字典反序列化。"""
        allowed = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in allowed})


class OperationLogStore:
    """按 owner_id 分区的写操作日志存储（内存 + 落盘）。"""

    def __init__(
        self,
        base_dir: Path | str | None = None,
        *,
        ttl_days: int = DEFAULT_TTL_DAYS,
        ring_capacity: int = DEFAULT_RING_CAPACITY,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        """初始化存储。

        Args:
            base_dir: 操作日志目录；None 时用默认（可被环境变量覆盖）。
            ttl_days: 落盘日志有效期天数。
            ring_capacity: 每个身份的内存环形缓冲上限。
            now_fn: 当前时间回调（测试注入用）。
        """
        self.base_dir = Path(base_dir) if base_dir else _default_base_dir()
        self.ttl_days = int(ttl_days)
        self.ring_capacity = int(ring_capacity)
        self._now_fn = now_fn or _now
        self._mem: dict[str, deque[OperationLogEntry]] = {}
        self._current_trace: dict[str, str] = {}
        self._seq = 0

    # ── trace 会话窗 ──

    def next_trace_id(self) -> str:
        """生成新的 trace 会话窗标识。"""
        return f"trc_{self._now_fn().strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(4)}"

    def set_current_trace(self, owner_id: str, trace_id: str) -> None:
        """绑定某身份当前 trace 会话窗。"""
        if owner_id and trace_id:
            self._current_trace[owner_id] = trace_id

    def get_current_trace(self, owner_id: str) -> str:
        """读取某身份当前 trace 会话窗，缺省为空串。"""
        return self._current_trace.get(owner_id, "")

    # ── 写入 ──

    def _file_path(self, owner_id: str) -> Path:
        """返回某身份的落盘文件路径，owner 非法时返回 None。"""
        if not _OWNER_RE.match(owner_id or ""):
            return None
        return self.base_dir / f"{owner_id}.jsonl"

    def record(
        self,
        *,
        mcp_token: str,
        tool: str,
        status: str,
        code: str = "",
        args: Any = None,
        result: Any = None,
        trace_id: str = "",
        source: str = "unknown",
        access_level: str = "user",
        duration_ms: int = 0,
        started_at: str = "",
        secrets_: tuple[str, ...] = (),
    ) -> OperationLogEntry:
        """记录一条写操作日志（脱敏 + 内存环形 + 落盘）。

        Args:
            mcp_token: 当前已验证 MCP 接入 Token，用于派生 owner_id。
            tool: 工具/操作名。
            status: 结果状态（SUCCESS/ERROR/PARTIAL/UNVERIFIED/BLOCKED/UNKNOWN）。
            code: 业务错误码或阶段状态（可选）。
            args: 原始入参（内部脱敏与截断后存储）。
            result: 原始结果（内部脱敏与截断后存储）。
            trace_id: 所属会话窗；留空时取当前身份绑定值。
            source: 来源展示标识。
            access_level: 权限级别。
            duration_ms: 调用耗时（毫秒）。
            started_at: 调用开始时间 ISO 串。
            secrets_: 需额外剔除的明文凭据（如口令/验证码）。

        Returns:
            已写入的 OperationLogEntry。
        """
        owner_id = derive_owner_id(mcp_token)
        now = self._now_fn()
        self._seq += 1
        entry = OperationLogEntry(
            entry_id=f"op{self._seq:013d}",
            seq=self._seq,
            owner_id=owner_id,
            trace_id=trace_id or self._current_trace.get(owner_id, ""),
            tool=tool,
            source=source,
            access_level=access_level,
            status=status,
            code=str(code or ""),
            args_summary=_summarize(args, secrets_),
            result_summary=_summarize(result, secrets_),
            started_at=started_at or now.isoformat(),
            finished_at=now.isoformat(),
            duration_ms=int(duration_ms),
            created_at=now.isoformat(),
        )
        if owner_id:
            self._append_mem(owner_id, entry)
            self._append_disk(owner_id, entry)
        return entry

    def _append_mem(self, owner_id: str, entry: OperationLogEntry) -> None:
        """写入内存环形缓冲，超出上限丢弃最旧。"""
        buf = self._mem.get(owner_id)
        if buf is None:
            buf = self._load_disk(owner_id)
            self._mem[owner_id] = buf
        buf.append(entry)
        while len(buf) > self.ring_capacity:
            buf.popleft()

    def _append_disk(self, owner_id: str, entry: OperationLogEntry) -> None:
        """追加一行 JSON 到该身份落盘文件（0o600 权限，占用时短重试）。"""
        path = self._file_path(owner_id)
        if path is None:
            return
        self.base_dir.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry.to_dict(), ensure_ascii=False)
        for attempt in range(6):
            try:
                new = not path.exists()
                with path.open("a", encoding="utf-8") as stream:
                    stream.write(line + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                if new:
                    os.chmod(path, 0o600)
                return
            except OSError as exc:
                if getattr(exc, "winerror", None) not in (5, 32, 33) or attempt == 5:
                    raise
                time.sleep(0.01 * (2 ** attempt))

    # ── 读取 ──

    def _expires(self, entry: OperationLogEntry) -> bool:
        """判断条目是否已过 TTL。"""
        try:
            created = datetime.fromisoformat(entry.created_at)
        except (TypeError, ValueError):
            return True
        return self._now_fn() >= created + timedelta(days=self.ttl_days)

    def _load_disk(self, owner_id: str) -> deque[OperationLogEntry]:
        """从落盘文件读取未过期条目（取最近 ring_capacity 条）。"""
        buf: deque[OperationLogEntry] = deque(maxlen=self.ring_capacity)
        path = self._file_path(owner_id)
        if path is None or not path.exists():
            return buf
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            return buf
        entries: list[OperationLogEntry] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = OperationLogEntry.from_dict(json.loads(line))
            except (json.JSONDecodeError, OSError, TypeError):
                continue
            if not self._expires(entry):
                entries.append(entry)
        for entry in entries[-self.ring_capacity:]:
            buf.append(entry)
        return buf

    def list_current(
        self,
        owner_id: str,
        *,
        trace_id: str | None = None,
        cursor: str = "",
        limit: int = 50,
    ) -> tuple[list[OperationLogEntry], str]:
        """列出某身份本次会话窗内的操作日志。

        Args:
            owner_id: 归属身份（由 Token 派生）。
            trace_id: 指定会话窗；None 时用当前绑定值，空值则返回该身份全部未过期日志。
            cursor: 增量游标（entry 序号），仅返回其后的条目。
            limit: 单次返回上限。

        Returns:
            ``(按时间升序的条目列表, 新游标)``。
        """
        if not owner_id:
            return [], str(cursor or "")
        buf = self._mem.get(owner_id)
        if buf is None:
            buf = self._load_disk(owner_id)
            self._mem[owner_id] = buf
        wanted = self.get_current_trace(owner_id) if trace_id is None else trace_id
        try:
            after = int(cursor) if cursor else 0
        except (TypeError, ValueError):
            after = 0
        selected = [
            e for e in buf
            if e.seq > after and not self._expires(e)
            and (not wanted or e.trace_id == wanted)
        ]
        page = selected[-limit:] if limit > 0 else selected
        next_cursor = str(page[-1].seq) if page else str(after)
        return page, next_cursor


_default_store: OperationLogStore | None = None


def default_store() -> OperationLogStore:
    """返回进程共享的默认操作日志存储单例。"""
    global _default_store
    if _default_store is None:
        _default_store = OperationLogStore()
    return _default_store
