"""保留期清理测试：分类处置、TTL 扫描、临时目录随会话销毁即清。"""

from __future__ import annotations

import os

import pytest

from webchat.config import load_settings
from webchat.retention import (
    category_for,
    retention_days_for,
    sweep_workspaces,
)

DAY = 86400


def _settings(tmp_path, **env_overrides):
    env = {
        "WEBCHAT_MINT_SECRET": "test-secret",
        "WEBCHAT_WORKSPACES_DIR": str(tmp_path / "workspaces"),
    }
    env.update(env_overrides)
    return load_settings(env)


def _touch(path, age_days):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    stamp = 1_600_000_000 - age_days * DAY
    os.utime(path, (stamp, stamp))


def test_category_mapping():
    """目录首段 → cleanup.py 分类；未知分类为空串（一律保留）。"""
    assert category_for("xlpa-tmp/a.txt") == "temp"
    assert category_for("xlpa-output/report.xlsx") == "result"
    assert category_for("xlpa-input/doc.pdf") == "input"
    assert category_for("xlpa-sensitive/copy.xlsx") == "sensitive_temp"
    assert category_for("xlpa-audit/log.jsonl") == "audit"
    assert category_for("other/file.txt") == ""


def test_retention_days_by_category(tmp_path):
    """各分类保留天数取自配置；temp/audit/未知不按 TTL 处理。"""
    settings = _settings(
        tmp_path,
        WEBCHAT_RETENTION_INPUT_DAYS="30",
        WEBCHAT_RETENTION_RESULT_DAYS="30",
        WEBCHAT_RETENTION_TEMPLATE_DAYS="30",
        WEBCHAT_RETENTION_SENSITIVE_TEMP_DAYS="7",
    )
    assert retention_days_for("input", settings) == 30
    assert retention_days_for("result", settings) == 30
    assert retention_days_for("template", settings) == 30
    assert retention_days_for("sensitive_temp", settings) == 7
    assert retention_days_for("temp", settings) is None
    assert retention_days_for("audit", settings) is None
    assert retention_days_for("", settings) is None


def test_sweep_workspaces_by_category(tmp_path):
    """过期删除、未过期保留、audit 不清、temp 跳过、未知保留。"""
    settings = _settings(tmp_path)
    workspace = tmp_path / "workspaces" / "s1"
    old_input = workspace / "xlpa-input" / "old.pdf"
    fresh_input = workspace / "xlpa-input" / "fresh.pdf"
    old_result = workspace / "xlpa-output" / "old.xlsx"
    fresh_result = workspace / "xlpa-output" / "fresh.xlsx"
    old_sensitive = workspace / "xlpa-sensitive" / "old.xlsx"
    tmp_file = workspace / "xlpa-tmp" / "scratch.txt"
    audit_file = workspace / "xlpa-audit" / "log.jsonl"
    unknown_file = workspace / "notes.txt"
    _touch(old_input, 31)
    _touch(fresh_input, 1)
    _touch(old_result, 31)
    _touch(fresh_result, 1)
    _touch(old_sensitive, 8)
    _touch(tmp_file, 40)
    _touch(audit_file, 40)
    _touch(unknown_file, 40)

    now = 1_600_000_000
    summary = sweep_workspaces(settings.workspaces_dir, settings, now=now)

    assert str(old_input) in summary["deleted"]
    assert str(old_result) in summary["deleted"]
    assert str(old_sensitive) in summary["deleted"]
    assert str(fresh_input) in summary["kept"]
    assert str(fresh_result) in summary["kept"]
    assert str(tmp_file) in summary["skipped"]  # temp 由会话销毁时清
    assert str(audit_file) in summary["skipped"]  # audit 不清
    assert str(unknown_file) in summary["unknown"]  # 未知分类保留
    # 磁盘事实：过期已删、保留仍在
    assert not old_input.exists() and not old_result.exists()
    assert fresh_input.exists() and fresh_result.exists()
    assert audit_file.exists() and unknown_file.exists() and tmp_file.exists()


def test_sweep_missing_dir_is_noop(tmp_path):
    """工作区根不存在时安全返回空摘要。"""
    settings = _settings(tmp_path)
    summary = sweep_workspaces(tmp_path / "absent", settings, now=1_600_000_000)
    assert summary == {"deleted": [], "kept": [], "unknown": [], "skipped": []}


@pytest.mark.asyncio
async def test_close_clears_temp_but_keeps_output(client_factory, bootstrap):
    """会话销毁：xlpa-tmp 立即清空，xlpa-output 产物按保留期留存。"""
    client = client_factory()
    _, session_id, state = bootstrap(client)
    session = state.runtime.get(session_id)
    (session.workspace / "xlpa-tmp" / "scratch.txt").write_text("t", encoding="utf-8")
    (session.workspace / "xlpa-output" / "report.txt").write_text("r", encoding="utf-8")
    await state.runtime.close(session)
    assert list((session.workspace / "xlpa-tmp").iterdir()) == []
    assert (session.workspace / "xlpa-output" / "report.txt").exists()
