"""会话工作区与产物的保留期清理（沿用 cleanup.py 分类语义，不 import mcp_server）。

分类与处置（design D6）：
- ``xlpa-tmp/``       temp           会话销毁即清（由 runtime.close 处理，本模块跳过）
- ``xlpa-output/``    result         30 天
- ``xlpa-input/``     input          30 天
- ``xlpa-sensitive/`` sensitive_temp 7 天（表格默认不落工作区，此项针对确需落地的副本）
- ``xlpa-audit/``     audit          不清
- 未知分类            —              一律保留

用户主动删除会话 ⇒ 立即物理删除（由 sessions_api DELETE 处理，不经本模块）。
"""

from __future__ import annotations

__all__ = [
    "BACKGROUND_DIRS",
    "category_for",
    "retention_days_for",
    "sweep_workspaces",
    "retention_sweep_loop",
]

import asyncio
import logging
import time
from pathlib import Path

from .config import Settings

logger = logging.getLogger(__name__)

# 目录名 → 分类（顺序匹配相对路径首段）。
BACKGROUND_DIRS = {
    "xlpa-tmp": "temp",
    "xlpa-output": "result",
    "xlpa-input": "input",
    "xlpa-sensitive": "sensitive_temp",
    "xlpa-audit": "audit",
}


def category_for(rel_path: str | Path) -> str:
    """按工作区相对路径首段判定分类；未知返回空串（一律保留）。"""
    parts = Path(str(rel_path)).parts
    if not parts:
        return ""
    return BACKGROUND_DIRS.get(parts[0], "")


def retention_days_for(category: str, settings: Settings) -> int | None:
    """分类对应保留天数；``None`` 表示不按 TTL 清理（temp/audit/未知）。"""
    if category == "result":
        return settings.retention_result_days
    if category == "template":
        return settings.retention_template_days
    if category == "input":
        return settings.retention_input_days
    if category == "sensitive_temp":
        return settings.retention_sensitive_temp_days
    return None


def sweep_workspaces(
    workspaces_dir: Path | str,
    settings: Settings,
    *,
    now: float | None = None,
) -> dict:
    """按目录 mtime + 分类扫描并清理过期文件。

    ``temp`` 交由会话销毁时清理（此处跳过）；``audit``/未知分类一律保留。
    返回 ``{"deleted": [...], "kept": [...], "unknown": [...], "skipped": [...]}``。
    """
    current = time.time() if now is None else now
    workspaces = Path(workspaces_dir)
    result: dict[str, list[str]] = {
        "deleted": [], "kept": [], "unknown": [], "skipped": [],
    }
    if not workspaces.exists():
        return result

    for session_dir in sorted(workspaces.iterdir()):
        if not session_dir.is_dir():
            continue
        for path in sorted(session_dir.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(session_dir).as_posix()
            category = category_for(rel)
            if not category:
                result["unknown"].append(str(path))
                continue
            days = retention_days_for(category, settings)
            if days is None:
                # temp（会话销毁即清）/ audit（不清）→ 本扫描不处理
                result["skipped"].append(str(path))
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError:
                result["kept"].append(str(path))
                continue
            if current - mtime > days * 86400:
                try:
                    path.unlink()
                    result["deleted"].append(str(path))
                except OSError:
                    result["kept"].append(str(path))
            else:
                result["kept"].append(str(path))
    return result


async def retention_sweep_loop(settings: Settings) -> None:
    """轻量后台任务：按 ``WEBCHAT_RETENTION_SWEEP_INTERVAL`` 周期扫描清理。"""
    interval = settings.retention_sweep_interval
    while True:
        try:
            summary = sweep_workspaces(settings.workspaces_dir, settings)
            if summary["deleted"]:
                logger.info(
                    "保留期清理：删除 %d 个过期文件", len(summary["deleted"])
                )
        except Exception:  # noqa: BLE001 - 后台任务不得拖垮服务
            logger.exception("保留期清理任务异常（下轮重试）")
        await asyncio.sleep(interval)
