"""测试报告持久化：owner 隔离 + 短 TTL 保留 + 越权不存在语义。

报告 JSON 落盘（test_run_id → 文件），按 owner_id 隔离；查询越权返回 None
（与"不存在"同语义，不泄漏报告存在性）；过期惰性删除。
"""

from __future__ import annotations

__all__ = ["ReportStore"]

import json
import os
import secrets
import time
from pathlib import Path

DEFAULT_TTL_SECONDS = 7 * 86400  # 7 天（对齐 sensitive_temp 短保留口径）


def _default_base_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "conversion_reports"


class ReportStore:
    """测试报告存储（owner 隔离，短 TTL）。"""

    def __init__(self, base_dir: Path | str | None = None, *,
                 ttl_seconds: int = DEFAULT_TTL_SECONDS, now_fn=None):
        self.base_dir = Path(base_dir) if base_dir else _default_base_dir()
        self.ttl_seconds = int(ttl_seconds)
        self._now_fn = now_fn or time.time

    def save(self, owner_id: str, report: dict) -> str:
        """保存报告，返回 test_run_id。"""
        test_run_id = secrets.token_hex(16)
        payload = {
            "test_run_id": test_run_id,
            "owner_id": owner_id,
            "created_at": self._now_fn(),
            "report": report,
        }
        self.base_dir.mkdir(parents=True, exist_ok=True)
        path = self.base_dir / f"{test_run_id}.json"
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
        return test_run_id

    def get(self, test_run_id: str, owner_id: str) -> dict | None:
        """按归属查询报告；不存在/过期/越权返回 None。"""
        if not test_run_id:
            return None
        path = self.base_dir / f"{test_run_id}.json"
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if payload.get("owner_id") != owner_id:
            return None
        if self._now_fn() - payload.get("created_at", 0) > self.ttl_seconds:
            path.unlink(missing_ok=True)
            return None
        return payload.get("report")
