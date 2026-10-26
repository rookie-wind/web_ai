"""edge_check_monitor_online 免模板路径测试。

覆盖独立登录会话（template=None）：按后端档案类型自动选路、
感知事件在线判定、召测缺分路号的兜底、以及显式 check_method 优先。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import edge_tools as tools
from edge_tools import register_edge_tools


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """隔离运行态目录并复位会话表与 owner。"""
    monkeypatch.setenv("PCA_TASK_REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("PCA_OPERATION_LOGS_DIR", str(tmp_path / "oplogs"))
    from session import mcp_token_var
    mcp_token_var.set("tok-online")
    monkeypatch.setattr(tools, "edge_sessions", tools.EdgeSessionStore())
    monkeypatch.setattr(tools, "_current_owner_id", lambda: "tester")


def _token_session() -> str:
    return tools.edge_sessions.create_token_session(owner_id="tester")


def _client(records: dict, smart: dict) -> MagicMock:
    """按请求路径分派的 fake client。

    records: getDeviceList 响应；smart: getSmartEventData 响应。
    """
    client = MagicMock()

    def _call(path, payload, *args, **kwargs):
        if path == tools.PATH_GET_DEVICE_LIST:
            return records
        if path == tools.PATH_SMART_EVENT:
            return smart
        raise AssertionError(f"未预期路径 {path}")

    client.call.side_effect = _call
    return client


def test_free_template_lighting_routes_smart_event() -> None:
    """免模板：照明 deviceId → 读档案类型 → 自动走感知事件判在线。"""
    mcp = MagicMock()
    mcp.tool.return_value = lambda f: f
    register_edge_tools(mcp)
    tid = _token_session()

    records = {"ok": True, "data": {"rows": [
        {"deviceId": "LIT_DEV", "deviceType": "照明", "agentNum": 1},
    ]}}
    smart = {"ok": True, "data": {"responseData": [
        {"deviceId": "LIT_DEV", "dataLabel": "onOff",
         "dataArray": [{"dataTime": "t", "dataVal": "1"}]},
    ]}}
    tools._client_for = lambda s: _client(records, smart)

    res = tools.edge_check_monitor_online(task_id=tid, device_id="LIT_DEV")
    assert res["ok"] is True
    assert res["method"] == "smart_event"
    assert res["online"] is True


def test_free_template_monitor_debug_needs_road_no() -> None:
    """免模板：XLBA 走召测但档案无 agentNum 且未给 road_no → needs_user_input。"""
    mcp = MagicMock()
    mcp.tool.return_value = lambda f: f
    register_edge_tools(mcp)
    tid = _token_session()

    records = {"ok": True, "data": {"rows": [
        {"deviceId": "XLBA_DEV", "deviceType": "XLBA电表"},
    ]}}
    tools._client_for = lambda s: _client(records, {"ok": True, "data": {}})

    res = tools.edge_check_monitor_online(task_id=tid, device_id="XLBA_DEV")
    assert res["online"] is None
    assert res["method"] == "monitor_debug"
    assert res["needs_user_input"] is True


def test_free_template_explicit_method_overrides() -> None:
    """显式 check_method=smart_event 跳过档案读取直接查感知事件。"""
    mcp = MagicMock()
    mcp.tool.return_value = lambda f: f
    register_edge_tools(mcp)
    tid = _token_session()

    smart = {"ok": True, "data": {"responseData": [
        {"deviceId": "X", "dataArray": [{"dataTime": "t", "dataVal": "1"}]},
    ]}}
    tools._client_for = lambda s: _client({"ok": True, "data": {}}, smart)

    res = tools.edge_check_monitor_online(
        task_id=tid, device_id="X", check_method="smart_event",
    )
    assert res["method"] == "smart_event" and res["online"] is True


def test_free_template_requires_device_id() -> None:
    """免模板且未给 device_id → 明确报错。"""
    mcp = MagicMock()
    mcp.tool.return_value = lambda f: f
    register_edge_tools(mcp)
    tid = _token_session()

    res = tools.edge_check_monitor_online(task_id=tid)
    assert res.get("error") is True
    assert "device_id" in res.get("message", "")
