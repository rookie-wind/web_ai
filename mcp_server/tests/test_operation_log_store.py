"""operation_log_store 单元测试。

覆盖：落盘读回、脱敏、按身份隔离、TTL 过期、游标增量、跨重启回看。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

import operation_log_store as ols
from archiving.snapshot_store import derive_owner_id


@pytest.fixture(autouse=True)
def private_logs(tmp_path, monkeypatch) -> None:
    """将操作日志写入测试临时目录，避免触及用户目录。"""
    monkeypatch.setenv("PCA_OPERATION_LOGS_DIR", str(tmp_path / "oplogs"))


def _ts(base: datetime, offset_days: int = 0) -> str:
    """构造带偏移的 ISO 时间串。"""
    return (base + timedelta(days=offset_days)).isoformat()


def test_record_then_reload_from_disk(tmp_path) -> None:
    """写入后新建实例可从磁盘读回相同条数。"""
    store = ols.OperationLogStore(tmp_path / "oplogs")
    store.record(mcp_token="tokA", tool="add_classify", status="SUCCESS")
    store.record(mcp_token="tokA", tool="del_classify", status="ERROR", code="API_ERROR")

    reloaded = ols.OperationLogStore(tmp_path / "oplogs")
    owner = derive_owner_id("tokA")
    entries, _ = reloaded.list_current(owner, trace_id="")
    assert len(entries) == 2
    assert [e.tool for e in entries] == ["add_classify", "del_classify"]


def test_summaries_are_sanitized(tmp_path) -> None:
    """含口令/Token 的入参与凭据落库后不出现明文。"""
    store = ols.OperationLogStore(tmp_path / "oplogs")
    store.record(
        mcp_token="tokA", tool="login", status="SUCCESS",
        args={"phone": "13800000000", "code": "123456", "sysName": "ok"},
        secrets_=("123456",),
    )
    owner = derive_owner_id("tokA")
    disk = (tmp_path / "oplogs" / f"{owner}.jsonl").read_text(encoding="utf-8")
    assert "123456" not in disk
    assert "13800000000" not in disk
    assert "ok" in disk


def test_detail_retained_and_raw_stripped(tmp_path) -> None:
    """平衡档保留长 message 与结构化 detail，raw 请求体被脱敏。"""
    store = ols.OperationLogStore(tmp_path / "oplogs")
    long_msg = "下发失败：网关无响应，已重试 3 次仍超时。" + ("x" * 600)
    store.record(
        mcp_token="tokA", tool="edge_set_device_param", status="ERROR",
        code="rtnCode=500",
        result={"message": long_msg, "raw": "BIG-RAW-BODY", "request_body": "RB",
                "dispatches": [{"path": "/p", "state": "FAILED"}]},
    )
    owner = derive_owner_id("tokA")
    disk = (tmp_path / "oplogs" / f"{owner}.jsonl").read_text(encoding="utf-8")
    entry = store.list_current(owner, trace_id="")[0][0]
    # 长 message 未被截回 200（新上限 1000）
    assert len(entry.result_summary["message"]) > 200
    # raw / request_body 脱敏为 ***
    assert entry.result_summary["raw"] == "***"
    assert entry.result_summary["request_body"] == "***"
    # 结构化 dispatches 保留
    assert entry.result_summary["dispatches"][0]["path"] == "/p"
    assert "BIG-RAW-BODY" not in disk


def test_owner_isolation(tmp_path) -> None:
    """一个身份只读到自己的日志。"""
    store = ols.OperationLogStore(tmp_path / "oplogs")
    store.record(mcp_token="tokA", tool="add_brand", status="SUCCESS")
    store.record(mcp_token="tokB", tool="add_model", status="SUCCESS")

    a_entries, _ = store.list_current(derive_owner_id("tokA"), trace_id="")
    b_entries, _ = store.list_current(derive_owner_id("tokB"), trace_id="")
    assert [e.tool for e in a_entries] == ["add_brand"]
    assert [e.tool for e in b_entries] == ["add_model"]


def test_empty_owner_returns_nothing(tmp_path) -> None:
    """空 owner 不返回任何数据。"""
    store = ols.OperationLogStore(tmp_path / "oplogs")
    store.record(mcp_token="tokA", tool="add_brand", status="SUCCESS")
    entries, cursor = store.list_current("", trace_id="")
    assert entries == []
    assert cursor == ""


def test_current_trace_scoping(tmp_path) -> None:
    """list_current 默认只看当前 trace 会话窗。"""
    store = ols.OperationLogStore(tmp_path / "oplogs")
    owner = derive_owner_id("tokA")
    t1 = store.next_trace_id()
    store.set_current_trace(owner, t1)
    store.record(mcp_token="tokA", tool="add_brand", status="SUCCESS", trace_id=t1)

    t2 = store.next_trace_id()
    store.set_current_trace(owner, t2)
    store.record(mcp_token="tokA", tool="add_model", status="SUCCESS", trace_id=t2)

    current, _ = store.list_current(owner)
    assert [e.tool for e in current] == ["add_model"]
    # 旧窗在同身份下仍可显式查询
    old, _ = store.list_current(owner, trace_id=t1)
    assert [e.tool for e in old] == ["add_brand"]


def test_cursor_incremental(tmp_path) -> None:
    """游标仅返回其后条目并给出新游标。"""
    store = ols.OperationLogStore(tmp_path / "oplogs")
    owner = derive_owner_id("tokA")
    for i in range(3):
        store.record(mcp_token="tokA", tool=f"t{i}", status="SUCCESS", trace_id="w")
    page, cursor = store.list_current(owner, trace_id="w", limit=2)
    assert [e.tool for e in page] == ["t1", "t2"]
    nxt, cursor2 = store.list_current(owner, trace_id="w", cursor=cursor)
    assert nxt == []
    assert cursor2 == cursor


def test_ttl_expiry_skips_old(tmp_path) -> None:
    """超过 TTL 的落盘条目在读取时被剔除。"""
    now = datetime.now(timezone.utc)
    store = ols.OperationLogStore(
        tmp_path / "oplogs", ttl_days=7, now_fn=lambda: now,
    )
    owner = derive_owner_id("tokA")
    path = tmp_path / "oplogs" / f"{owner}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    fresh = ols.OperationLogEntry(
        entry_id="op1", seq=1, owner_id=owner, trace_id="w", tool="fresh",
        status="SUCCESS", created_at=_ts(now),
    )
    stale = ols.OperationLogEntry(
        entry_id="op2", seq=2, owner_id=owner, trace_id="w", tool="stale",
        status="SUCCESS", created_at=_ts(now, offset_days=-30),
    )
    lines = "\n".join(json.dumps(e.to_dict()) for e in (stale, fresh))
    path.write_text(lines + "\n", encoding="utf-8")

    fresh_store = ols.OperationLogStore(tmp_path / "oplogs", ttl_days=7, now_fn=lambda: now)
    entries, _ = fresh_store.list_current(owner, trace_id="w")
    assert [e.tool for e in entries] == ["fresh"]
