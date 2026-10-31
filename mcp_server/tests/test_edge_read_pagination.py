"""edge_get_device_tree / edge_get_device_list 分页读取测试。

覆盖：不分页保持旧行为（完整嵌套树 / 全列表）；limit>0 展平分页并给出
pagination 元数据；字符预算夹断单页；多页可无重无漏取回全量。
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

import edge_tools as tools
from edge_tools import register_edge_tools


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("PCA_TASK_REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("PCA_OPERATION_LOGS_DIR", str(tmp_path / "oplogs"))
    from session import mcp_token_var
    mcp_token_var.set("tok-page")
    monkeypatch.setattr(tools, "edge_sessions", tools.EdgeSessionStore())
    monkeypatch.setattr(tools, "_current_owner_id", lambda: "tester")
    mcp = MagicMock()
    mcp.tool.return_value = lambda f: f
    register_edge_tools(mcp)


def _session() -> str:
    return tools.edge_sessions.create_token_session(owner_id="tester")


TREE = [{
    "deviceId": "R", "name": "根网关", "children": [
        {"deviceId": "A", "children": [
            {"deviceId": "A1"}, {"deviceId": "A2"},
        ]},
        {"deviceId": "B", "children": [
            {"deviceId": "B1"}, {"deviceId": "B2"}, {"deviceId": "B3"},
        ]},
    ],
}]
# 深度优先展平共 8 个节点：R A A1 A2 B B1 B2 B3


def _client_for_tree() -> MagicMock:
    client = MagicMock()

    def _call(path, payload, *args, **kwargs):
        if path == tools.PATH_GET_DEVICE_TREE:
            return {"ok": True, "data": TREE}
        raise AssertionError(f"未预期路径 {path}")

    client.call.side_effect = _call
    return client


def test_tree_unpaged_keeps_nested() -> None:
    """limit<=0 时返回完整嵌套树，无 pagination（旧行为不变）。"""
    tid = _session()
    tools._client_for = lambda s: _client_for_tree()
    res = tools.edge_get_device_tree(task_id=tid)
    assert res["ok"] is True
    assert "pagination" not in res
    assert res["data"][0]["deviceId"] == "R"
    assert res["data"][0]["children"], "嵌套 children 应保留"


def test_tree_paged_flattens_with_meta() -> None:
    """limit>0 时展平分页：节点行无 children，附 depth/parent_id 与分页元数据。"""
    tid = _session()
    tools._client_for = lambda s: _client_for_tree()
    res = tools.edge_get_device_tree(task_id=tid, offset=0, limit=3)
    page = res["data"]
    assert len(page) == 3
    assert [r["deviceId"] for r in page] == ["R", "A", "A1"]
    assert all("children" not in r for r in page)
    assert page[0]["depth"] == 0 and page[0]["parent_id"] == ""
    assert page[2]["depth"] == 2 and page[2]["parent_id"] == "A"
    pg = res["pagination"]
    assert pg["total"] == 8 and pg["returned"] == 3
    assert pg["has_more"] is True and pg["next_offset"] == 3


def test_tree_pages_reassemble_all() -> None:
    """按 next_offset 续取，多页无重无漏取回全部节点。"""
    tid = _session()
    tools._client_for = lambda s: _client_for_tree()
    seen: list[str] = []
    offset = 0
    while True:
        res = tools.edge_get_device_tree(task_id=tid, offset=offset, limit=3)
        seen.extend(r["deviceId"] for r in res["data"])
        pg = res["pagination"]
        if not pg["has_more"]:
            break
        offset = pg["next_offset"]
    assert sorted(seen) == sorted(
        ["R", "A", "A1", "A2", "B", "B1", "B2", "B3"],
    )


def test_tree_char_budget_caps_page() -> None:
    """单页字符超预算时提前夹断，returned 远小于 limit 且有 has_more。"""
    big = [{"deviceId": f"D{i}", "blob": "x" * 5000} for i in range(10)]
    client = MagicMock()
    client.call.side_effect = lambda path, payload, *a, **k: {
        "ok": True, "data": big,
    }
    tid = _session()
    tools._client_for = lambda s: client
    res = tools.edge_get_device_tree(task_id=tid, offset=0, limit=500)
    page = res["data"]
    # 单条约 5020 字符，预算 12000 → 仅容 2 条，虽 limit=500
    assert len(page) == 2
    used = sum(len(json.dumps(r, ensure_ascii=False)) for r in page)
    assert used <= tools.TREE_PAGE_MAX_CHARS
    assert res["pagination"]["has_more"] is True
    assert res["pagination"]["next_offset"] == 2


def _client_for_list(items: list) -> MagicMock:
    client = MagicMock()

    def _call(path, payload, *args, **kwargs):
        if path == tools.PATH_GET_DEVICE_LIST_BY_PID:
            return {"ok": True, "data": items}
        raise AssertionError(f"未预期路径 {path}")

    client.call.side_effect = _call
    return client


def test_list_unpaged_returns_full() -> None:
    """limit<=0 返回全列表，无 pagination。"""
    items = [{"deviceId": f"D{i}"} for i in range(10)]
    tid = _session()
    tools._client_for = lambda s: _client_for_list(items)
    res = tools.edge_get_device_list(task_id=tid, device_id="P")
    assert "pagination" not in res
    assert len(res["data"]) == 10


def test_list_paged_with_meta() -> None:
    """limit>0 分页返回，附 pagination；末页 has_more=False。"""
    items = [{"deviceId": f"D{i}"} for i in range(10)]
    tid = _session()
    tools._client_for = lambda s: _client_for_list(items)
    first = tools.edge_get_device_list(
        task_id=tid, device_id="P", offset=0, limit=4,
    )
    assert len(first["data"]) == 4
    assert first["pagination"] == {
        "total": 10, "offset": 0, "limit": 4,
        "returned": 4, "has_more": True, "next_offset": 4,
    }
    last = tools.edge_get_device_list(
        task_id=tid, device_id="P", offset=8, limit=4,
    )
    assert [r["deviceId"] for r in last["data"]] == ["D8", "D9"]
    assert last["pagination"]["has_more"] is False
