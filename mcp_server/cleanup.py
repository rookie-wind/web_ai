"""资源包备份与自动建档产物的清理策略。

集中定义「什么可以删、什么必须留」的判定，供资源包更新流程与
XLPA 自动建档流程复用，并可被单元测试独立覆盖。

核心原则：
  - 资源包旧版本备份：仅在 manifest 校验通过且用户确认新版可用后删除。
  - 建档产物：仅删除后续不会复用的临时产物（temp / sensitive_temp），
    保留输入、结果、审计、补偿、模板和可复用缓存。
"""

from __future__ import annotations

__all__ = [
    "ARTIFACT_KEEP_CATEGORIES",
    "ARTIFACT_DELETE_CATEGORIES",
    "should_cleanup_package_backup",
    "cleanup_package_backups",
    "should_delete_artifact",
    "cleanup_artifacts",
]

import os
import shutil

# 必须保留的产物分类：输入、结果、审计、补偿、模板、可复用缓存
ARTIFACT_KEEP_CATEGORIES = frozenset(
    {"input", "result", "audit", "compensation", "template", "cache"}
)
# 可删除的产物分类：普通临时产物与敏感临时产物
ARTIFACT_DELETE_CATEGORIES = frozenset({"temp", "sensitive_temp"})


def should_cleanup_package_backup(validation_ok: bool, user_confirmed: bool) -> bool:
    """判定资源包更新后是否可删除旧版本备份。

    仅当 manifest 校验通过且用户确认新版可用时才允许删除；
    校验失败时保留备份用于回滚与诊断。

    Args:
        validation_ok: 更新后资源包 manifest 校验是否通过。
        user_confirmed: 用户是否已确认新版可用。

    Returns:
        允许删除备份返回 True，否则返回 False。
    """
    return bool(validation_ok and user_confirmed)


def cleanup_package_backups(
    backup_dirs: list[str],
    validation_ok: bool,
    user_confirmed: bool,
) -> dict:
    """按判定删除或保留资源包旧版本备份目录。

    Args:
        backup_dirs: 本次更新产生的备份目录路径列表。
        validation_ok: 更新后 manifest 校验是否通过。
        user_confirmed: 用户是否已确认新版可用。

    Returns:
        包含 deleted、kept 和 reason 的结果字典。校验失败或未确认时
        不删除任何备份，并在 reason 中说明原因。
    """
    if not should_cleanup_package_backup(validation_ok, user_confirmed):
        reason = (
            "manifest 校验未通过，保留备份用于回滚"
            if not validation_ok
            else "用户未确认新版可用，保留备份"
        )
        return {"deleted": [], "kept": list(backup_dirs), "reason": reason}

    deleted: list[str] = []
    kept: list[str] = []
    for path in backup_dirs:
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
            deleted.append(path)
        elif os.path.exists(path):
            # 非目录备份（如打包 zip）同样视为不可复用临时备份
            os.remove(path)
            deleted.append(path)
        else:
            kept.append(path)
    return {"deleted": deleted, "kept": kept, "reason": "校验通过且用户已确认，删除不可复用备份"}


def should_delete_artifact(category: str) -> bool:
    """判定某分类的建档产物是否可删除。

    Args:
        category: 产物分类，取值见 ARTIFACT_DELETE_CATEGORIES /
            ARTIFACT_KEEP_CATEGORIES。

    Returns:
        仅 temp / sensitive_temp 返回 True；未知分类按保留处理返回 False。
    """
    return category in ARTIFACT_DELETE_CATEGORIES


def cleanup_artifacts(entries: list[dict]) -> dict:
    """按分类清理建档产物，仅删除临时产物。

    未知分类一律保留，避免误删可复用或可审计资产。敏感临时产物
    （sensitive_temp）优先删除。

    Args:
        entries: 产物条目列表，每项形如
            ``{"path": "<文件路径>", "category": "<分类>"}``。

    Returns:
        包含 deleted、kept 和 unknown 三个路径列表的结果字典。
    """
    deleted: list[str] = []
    kept: list[str] = []
    unknown: list[str] = []
    for entry in entries:
        path = entry.get("path", "")
        category = entry.get("category", "")
        if category not in ARTIFACT_DELETE_CATEGORIES and category not in ARTIFACT_KEEP_CATEGORIES:
            unknown.append(path)
            continue
        if should_delete_artifact(category):
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
                deleted.append(path)
            elif os.path.exists(path):
                os.remove(path)
                deleted.append(path)
            else:
                kept.append(path)
        else:
            kept.append(path)
    return {"deleted": deleted, "kept": kept, "unknown": unknown}
