"""edge_get_device_parameters 通用读参数测试。

覆盖免模板会话：按类型默认读、显式 item_ids、项缺失宽松返回。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import edge_tools as tools
from edge_tools import register_edge_tools


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("PCA_TASK_REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("PCA_OPERATION_LOGS_DIR", str(tmp_path / "oplogs"))
    from session import mcp_token_var
    mcp_token_var.set("tok-params")
    monkeypatch.setattr(tools, "edge_sessions", tools.EdgeSessionStore())
    monkeypatch.setattr(tools, "_current_owner_id", lambda: "tester")
    mcp = MagicMock()
    mcp.tool.return_value = lambda f: f
    register_edge_tools(mcp)


def _token_session() -> str:
    return tools.edge_sessions.create_token_session(owner_id="tester")


def _client(param_items: list, device_type: str = "") -> MagicMock:
    client = MagicMock()

    def _call(path, payload, *args, **kwargs):
        if path == tools.PATH_GET_DEVICE_LIST:
            return {"ok": True, "data": {"rows": [
                {"deviceId": payload["deviceId"], "deviceType": device_type,
                 "agentNum": 3},
            ]}}
        if path == tools.PATH_GET_DEVICE_PARAM:
            return {"ok": True, "data": param_items}
        raise AssertionError(f"未预期路径 {path}")

    client.call.side_effect = _call
    return client


def test_free_template_meter_reads_deploy_item() -> None:
    """免模板监测点：默认读 20200002 当前运行参数。"""
    tid = _token_session()
    body = {"roadNo": "3", "commAddr": "435600000009"}
    tools._client_for = lambda s: _client(
        [{"itemId": tools.METER_DEPLOY_ITEM_ID, "itemBody": body}], "照明",
    )
    res = tools.edge_get_device_parameters(task_id=tid, device_id="DEV_L")
    assert res["ok"] is True
    assert res["itemIds"] == [tools.METER_DEPLOY_ITEM_ID]
    assert res["deviceType"] == "照明"
    assert res["params"][0]["present"] is True
    assert res["params"][0]["itemBody"] == body


def test_free_template_gateway_reads_address_item() -> None:
    """免模板网关：默认读 20100024 通讯地址参数。"""
    tid = _token_session()
    tools._client_for = lambda s: _client(
        [{"itemId": tools.GATEWAY_ADDRESS_ITEM_ID,
          "itemBody": {"commAddr": "224356000099"}}], "8163网关",
    )
    res = tools.edge_get_device_parameters(task_id=tid, device_id="DEV_GW")
    assert res["itemIds"] == [tools.GATEWAY_ADDRESS_ITEM_ID]
    assert res["params"][0]["present"] is True


def test_list_itembody_passthrough() -> None:
    """后端 itemBody 为 list（电表通信参数）时原样透传，不被丢成空。"""
    tid = _token_session()
    body_list = [{"roadNo": "3", "commAddr": "435700002617", "authParam": ""}]
    tools._client_for = lambda s: _client(
        [{"itemId": tools.METER_DEPLOY_ITEM_ID, "itemName": "电表通信参数",
          "itemBody": body_list}], "XLBA电表",
    )
    res = tools.edge_get_device_parameters(task_id=tid, device_id="DEV_L")
    p = res["params"][0]
    assert p["present"] is True
    assert p["itemBody"] == body_list  # list 原样返回


def test_empty_list_itembody_present_false() -> None:
    """itemBody 为空 list 时 present=False。"""
    tid = _token_session()
    tools._client_for = lambda s: _client(
        [{"itemId": tools.METER_DEPLOY_ITEM_ID, "itemBody": []}], "XLBA电表",
    )
    res = tools.edge_get_device_parameters(task_id=tid, device_id="DEV_E")
    assert res["params"][0]["present"] is False


def test_explicit_item_ids_reads_multiple() -> None:
    """显式 item_ids 一次读多项，不做类型解析。"""
    tid = _token_session()
    tools._client_for = lambda s: _client([
        {"itemId": "20200002", "itemBody": {"a": 1}},
        {"itemId": "31800006", "itemBody": {"b": 2}},
    ])
    res = tools.edge_get_device_parameters(
        task_id=tid, device_id="DEV_X", item_ids="20200002,31800006",
    )
    assert res["itemIds"] == ["20200002", "31800006"]
    assert {p["itemId"] for p in res["params"]} == {"20200002", "31800006"}
    assert all(p["present"] for p in res["params"])


def test_missing_item_present_false_no_error() -> None:
    """项缺失时宽松返回 present=False，不报错。"""
    tid = _token_session()
    tools._client_for = lambda s: _client([], "照明")
    res = tools.edge_get_device_parameters(task_id=tid, device_id="DEV_M")
    assert res["ok"] is True
    assert res["params"][0]["present"] is False
    assert res["params"][0]["itemBody"] is None
