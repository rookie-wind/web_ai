"""写操作日志采集与内联的集成测试。

覆盖：白名单判定、wrapper 记录 + 内联、login 记录、fail-open、边缘动作记录。
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock

import pytest

import edge_tools
import operation_log_store as ols
import server
from archiving.snapshot_store import derive_owner_id
from session import mcp_token_var


@pytest.fixture
def store(tmp_path, monkeypatch):
    """将 server 与 edge_tools 的共享存储替换为临时目录实例。"""
    fresh = ols.OperationLogStore(tmp_path / "oplogs")
    monkeypatch.setattr(server, "_op_store", fresh)
    monkeypatch.setattr(edge_tools, "_op_store", fresh)
    return fresh


def test_write_whitelist() -> None:
    """云端 write 与 login 命中白名单，只读不命中。"""
    assert "add_classify" in server._CLOUD_WRITE_TOOL_NAMES
    assert "login" in server._CLOUD_WRITE_TOOL_NAMES
    assert "get_classify_list" not in server._CLOUD_WRITE_TOOL_NAMES


def test_classify_write_result() -> None:
    """状态分类覆盖成功/业务失败/阶段态。"""
    assert server._classify_write_result({"error": False, "code": 20000}) == ("SUCCESS", "")
    assert server._classify_write_result({"error": True, "code": "API_ERROR"}) == ("ERROR", "API_ERROR")
    assert server._classify_write_result({"stage_state": "SUCCEEDED"}) == ("SUCCESS", "SUCCEEDED")
    assert server._classify_write_result({"success": False, "error": "LOGIN_FAILED"}) == ("ERROR", "LOGIN_FAILED")


def test_wrapper_records_and_inlines(store) -> None:
    """包裹后的写工具返回内联 operation_log 且既有键不变，日志落库。"""
    mcp_token_var.set("tokW")

    async def original(sysName: str) -> dict:
        return {"error": False, "code": 20000, "data": {"id": 1}, "message": "成功"}

    wrapped = server._wrap_logged_tool("add_classify", original, True)
    result = asyncio.run(wrapped(sysName="X"))

    assert result["error"] is False and result["code"] == 20000
    assert "operation_log" in result
    assert result["operation_log"]["status"] == "SUCCESS"
    entries, _ = store.list_current(derive_owner_id("tokW"), trace_id="")
    assert len(entries) == 1
    assert entries[0].tool == "add_classify"


def test_failopen_preserves_result(store, monkeypatch) -> None:
    """落库异常时业务返回原样保留，不抛错、不加内联。"""
    mcp_token_var.set("tokF")

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(store, "record", boom)

    async def original(sysName: str) -> dict:
        return {"error": False, "code": 20000}

    wrapped = server._wrap_logged_tool("add_classify", original, True)
    result = asyncio.run(wrapped(sysName="X"))

    assert result == {"error": False, "code": 20000}
    assert "operation_log" not in result


def test_login_records_via_call_tool(store, monkeypatch) -> None:
    """通过真实 MCP 调用路径执行 login 失败，写日志计数 +1。"""
    mcp_token_var.set("tokL")

    async def login_fail(phoneNum, code):
        return {"error": True}

    monkeypatch.setattr(server.api_client, "login", login_fail)

    before_len = len(store.list_current(derive_owner_id("tokL"), trace_id="")[0])
    result = asyncio.run(server.mcp._tool_manager.call_tool(
        "login", {"phoneNum": "13800000000", "code": "0000"}, convert_result=False,
    ))

    assert isinstance(result, dict) and result.get("success") is False
    assert "operation_log" in result
    entries, _ = store.list_current(derive_owner_id("tokL"), trace_id="")
    assert len(entries) == before_len + 1


def test_edge_action_logs_request_payload(store) -> None:
    """请求报文随日志留存，其中凭证字段（authParam）落库时被脱敏。"""
    mcp_token_var.set("tokP")
    action = {
        "state": "SUCCEEDED",
        "started_at": "2026-01-01T00:00:00+00:00",
        "finished_at": "2026-01-01T00:00:01+00:00",
        "dispatches": [{
            "path": "/callDeviceParam", "state": "DISPATCHED", "payload_digest": "ab",
            "payload": {"deviceId": "D1", "authParam": "SECRET123",
                        "dataItem": {"itemId": "31800006", "itemBody": [{"roadNo": 6}]}},
        }],
    }
    edge_tools._record_edge_action(
        "edge_call_monitor_debug", action,
        {"ok": True, "data": {"rtnData": 1}}, {"task_id": "t"},
    )
    owner = derive_owner_id("tokP")
    disk = (store.base_dir / f"{owner}.jsonl").read_text(encoding="utf-8")
    assert "SECRET123" not in disk
    assert "31800006" in disk and "D1" in disk
    entry = store.list_current(owner, trace_id="")[0][0]
    payload = entry.result_summary["dispatches"][0]["payload"]
    assert payload["deviceId"] == "D1"
    assert payload["authParam"] == "***"


def test_edge_action_recorded(store) -> None:
    """边缘动作经 _record_edge_action 落入日志并返回内联摘要。"""
    mcp_token_var.set("tokE")
    action = {
        "state": "SUCCEEDED", "started_at": "2026-01-01T00:00:00+00:00",
        "finished_at": "2026-01-01T00:00:01+00:00",
    }
    inline = edge_tools._record_edge_action(
        "edge_set_device_param", action, {"ok": True}, {"task_id": "t", "password": "secret"},
    )

    assert inline["status"] == "SUCCESS"
    assert inline["duration_ms"] == 1000
    owner = derive_owner_id("tokE")
    disk = (store.base_dir / f"{owner}.jsonl").read_text(encoding="utf-8")
    assert "secret" not in disk


def _drive_logs(app, token: str, cursor: str = "") -> dict:
    """以最小 ASGI 桩驱动 _handle_operation_logs，返回解析后的 JSON。"""
    captured = {"body": b""}

    async def send(message):
        if message["type"] == "http.response.body":
            captured["body"] += message.get("body", b"")

    headers = []
    if token:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    query = f"cursor={cursor}" if cursor else ""
    scope = {"headers": headers, "query_string": query.encode("utf-8")}
    asyncio.run(app._handle_operation_logs(scope, send))
    return json.loads(captured["body"].decode("utf-8"))


@pytest.fixture
def composite_app():
    """构造仅用于日志端点测试的 CompositeApp（其余依赖为 mock）。"""
    return server.CompositeApp(
        MagicMock(), "<html>", MagicMock(), showcase_content="<html>",
    )


def test_api_logs_returns_own_entries(store, composite_app) -> None:
    """/api/logs 仅返回该 Token 身份的日志，经脱敏。"""
    store.record(mcp_token="tokV", tool="add_brand", status="SUCCESS", trace_id="w1")
    store.record(mcp_token="tokOther", tool="add_model", status="SUCCESS", trace_id="w1")
    store.set_current_trace(derive_owner_id("tokV"), "w1")

    payload = _drive_logs(composite_app, "tokV")
    assert payload["ok"] is True
    assert payload["trace_id"] == "w1"
    assert [item["tool"] for item in payload["logs"]] == ["add_brand"]


def test_api_logs_empty_without_token(store, composite_app) -> None:
    """无 Token 时返回空集合，不泄露任何日志。"""
    store.record(mcp_token="tokV", tool="add_brand", status="SUCCESS", trace_id="w1")
    payload = _drive_logs(composite_app, "")
    assert payload["logs"] == []
    assert payload["count"] == 0


def test_e2e_current_window_and_restart(store, composite_app) -> None:
    """端到端：协议写 + 边缘写归入当前窗，回读与重启后磁盘回看。"""
    token = "tokZ"
    owner = derive_owner_id(token)
    mcp_token_var.set(token)
    trace = store.next_trace_id()
    store.set_current_trace(owner, trace)

    store.record(mcp_token=token, tool="add_classify", status="SUCCESS")
    edge_tools._record_edge_action(
        "edge_set_device_param",
        {"state": "SUCCEEDED", "started_at": "2026-01-01T00:00:00+00:00",
         "finished_at": "2026-01-01T00:00:02+00:00"},
        {"ok": True}, {"task_id": "t", "password": "secret"},
    )

    payload = _drive_logs(composite_app, token)
    tools = {item["tool"] for item in payload["logs"]}
    assert {"add_classify", "edge_set_device_param"} <= tools
    assert payload["trace_id"] == trace
    raw = payload["body"] if "body" in payload else json.dumps(payload)
    assert "secret" not in raw

    restarted = ols.OperationLogStore(store.base_dir)
    entries, _ = restarted.list_current(owner, trace_id=trace)
    assert {e.tool for e in entries} >= {"add_classify", "edge_set_device_param"}
