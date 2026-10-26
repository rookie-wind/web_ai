"""自动建档任务报告持久化存储。

将脱敏计划、动作意图/结果和补偿清单持久化到私有报告目录，
支持进程中断后查询、任务过期后由所属身份查报告。
"""

from __future__ import annotations

__all__ = [
    "TaskReportStore",
    "TaskReport",
    "TaskReportError",
]

import json
import os
import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .log_sanitizer import sanitize_report

DEFAULT_TTL_DAYS = 30


def _now() -> datetime:
    """返回当前 UTC 时间。"""
    return datetime.now(timezone.utc)


def _default_base_dir() -> Path:
    """返回默认报告目录。"""
    env = os.environ.get("PCA_TASK_REPORTS_DIR", "")
    if env:
        return Path(env)
    return Path.home() / ".pca" / "task_reports"


class TaskReportError(Exception):
    """任务报告存储异常。"""


@dataclass
class TaskReport:
    """任务报告数据。"""

    report_id: str = ""
    task_id: str = ""
    owner_id: str = ""
    created_at: str = ""
    expires_at: str = ""
    plan_summary: dict = field(default_factory=dict)
    actions: list[dict] = field(default_factory=list)
    compensation: dict = field(default_factory=dict)
    stage_failures: dict[str, str] = field(default_factory=dict)
    stages: dict[str, dict] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """序列化为字典。"""
        return {
            "report_id": self.report_id,
            "task_id": self.task_id,
            "owner_id": self.owner_id,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "plan_summary": self.plan_summary,
            "actions": self.actions,
            "compensation": self.compensation,
            "stage_failures": self.stage_failures,
            "stages": self.stages,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TaskReport:
        """从字典反序列化。"""
        return cls(
            report_id=str(data.get("report_id", "")),
            task_id=str(data.get("task_id", "")),
            owner_id=str(data.get("owner_id", "")),
            created_at=str(data.get("created_at", "")),
            expires_at=str(data.get("expires_at", "")),
            plan_summary=dict(data.get("plan_summary", {})),
            actions=list(data.get("actions", [])),
            compensation=dict(data.get("compensation", {})),
            stage_failures=dict(data.get("stage_failures", {})),
            stages=dict(data.get("stages", {})),
        )


class TaskReportStore:
    """任务报告的私有存储。

    目录布局（``base_dir`` 下）：
      - ``<report_id>.json``：脱敏任务报告。

    所有写入均为临时文件 + ``os.replace`` 原子落盘。
    """

    def __init__(
        self,
        base_dir: Path | str | None = None,
        *,
        ttl_days: int = DEFAULT_TTL_DAYS,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        """初始化存储。

        Args:
            base_dir: 私有状态目录；None 时用默认。
            ttl_days: 报告有效期天数。
            now_fn: 当前时间回调（测试注入用）。
        """
        self.base_dir = Path(base_dir) if base_dir else _default_base_dir()
        self.ttl_days = int(ttl_days)
        self._now_fn = now_fn or _now

    def _report_path(self, report_id: str) -> Path:
        """返回报告文件路径。"""
        if not re.fullmatch(r"rpt_[0-9]{14}_[0-9a-f]{8}", report_id):
            raise TaskReportError("报告 ID 格式非法")
        return self.base_dir / f"{report_id}.json"

    def _atomic_write_json(self, path: Path, data: dict) -> None:
        """原子写 JSON：先写临时文件再 ``os.replace``。"""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{secrets.token_hex(8)}.tmp")
        with tmp.open("x", encoding="utf-8") as stream:
            os.chmod(tmp, 0o600)
            json.dump(sanitize_report(data), stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(6):
            try:
                os.replace(tmp, path)
                return
            except OSError as exc:
                # Windows文件暂时占用时只重试本地原子替换，不重发设备请求。
                if getattr(exc, "winerror", None) not in (5, 32, 33) or attempt == 5:
                    raise
                time.sleep(0.01 * (2 ** attempt))

    def save(
        self,
        *,
        task_id: str,
        owner_id: str,
        plan_summary: dict | None = None,
        actions: list[dict] | None = None,
        compensation: dict | None = None,
        stage_failures: dict[str, str] | None = None,
        stages: dict[str, dict] | None = None,
        report_id: str = "",
    ) -> TaskReport:
        """保存任务报告。

        Args:
            task_id: 任务 ID。
            owner_id: 归属身份摘要。
            plan_summary: 脱敏计划摘要。
            actions: 动作意图/结果列表。
            compensation: 补偿清单。
            stage_failures: 阶段失败记录。
            stages: 逐设备、逐阶段的执行状态。
            report_id: 已有报告 ID，空值时新建；不改变原归属。

        Returns:
            已落盘的 TaskReport。

        Raises:
            TaskReportError: 归属为空或无法分配唯一报告 ID。
        """
        if not owner_id:
            raise TaskReportError("报告归属 owner_id 不能为空")

        now = self._now_fn()
        previous = self.load(report_id) if report_id else None
        if previous and (previous.owner_id != owner_id or previous.task_id != task_id):
            raise TaskReportError("报告归属或任务不匹配")
        report_id = report_id or f"rpt_{now.strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(4)}"
        report = TaskReport(
            report_id=report_id,
            task_id=task_id,
            owner_id=owner_id,
            created_at=previous.created_at if previous else now.isoformat(),
            expires_at=(
                previous.expires_at if previous
                else (now + timedelta(days=self.ttl_days)).isoformat()
            ),
            plan_summary=plan_summary or {},
            actions=actions or [],
            compensation=compensation or {},
            stage_failures=stage_failures or {},
            stages=stages or {},
        )
        path = self._report_path(report_id)
        self._atomic_write_json(path, report.to_dict())
        return report

    def load(self, report_id: str) -> TaskReport:
        """加载报告。

        Args:
            report_id: 报告 ID。

        Returns:
            TaskReport。

        Raises:
            TaskReportError: 报告不存在或读取失败。
        """
        path = self._report_path(report_id)
        if not path.exists():
            raise TaskReportError(f"报告 {report_id} 不存在")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise TaskReportError(f"报告 {report_id} 读取失败: {exc}") from exc
        report = TaskReport.from_dict(data)
        try:
            expiry = datetime.fromisoformat(report.expires_at)
            if expiry.tzinfo is None or self._now_fn() >= expiry:
                raise TaskReportError("报告已过期")
        except (TypeError, ValueError) as exc:
            raise TaskReportError("报告有效期非法") from exc
        return report

    def find_by_task(self, task_id: str, owner_id: str) -> TaskReport | None:
        """按 task_id 和 owner_id 查找报告。

        Args:
            task_id: 任务 ID。
            owner_id: 归属身份。

        Returns:
            匹配的 TaskReport 或 None。
        """
        if not self.base_dir.exists():
            return None
        for report in self.list_by_owner(owner_id):
            if report.task_id == task_id:
                return report
        return None

    def list_by_owner(self, owner_id: str) -> list[TaskReport]:
        """列出归属身份的全部报告。

        Args:
            owner_id: 归属身份。

        Returns:
            TaskReport 列表。
        """
        reports: list[TaskReport] = []
        if not self.base_dir.exists():
            return reports
        for path in self.base_dir.glob("rpt_*.json"):
            try:
                report = self.load(path.stem)
                if report.owner_id == owner_id:
                    reports.append(report)
            except (TaskReportError, OSError):
                continue
        return sorted(reports, key=lambda r: r.created_at, reverse=True)
