"""公网暴露门控测试（C7 public-access-hardening 组 1）。

覆盖：配置默认值与解析、真实客户端 IP（XFF 可信代理）、路由层门控矩阵
（模式 on/off × 本机/远程/allowlist × 三类端点）、URL 凭据端点收紧
（templates 四种组合 + 本机不变、/api/logs 远程 ?token= 被忽略）。
"""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
import tempfile
from pathlib import Path

import pytest

_MCP_DIR = Path(__file__).parent.parent
if str(_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_MCP_DIR))


def _make_app(server):
    """构造仅用于路由/门控测试的 CompositeApp（不触碰 MCP 协议层）。"""
    with tempfile.TemporaryDirectory() as td:
        registry = Path(td) / "registry.json"
        manager = server.TokenManager(admin_token="", registry_path=registry)
    return server.CompositeApp(None, "<html>", manager)


def _drive_get(app, client_ip, path, query=b"", headers=None):
    """以 GET 语义驱动 CompositeApp.__call__，返回 (status, body, reached)。

    reached 表示请求是否通过了门控进入既有分发（pass 类端点由 auth 桩记录）。
    """
    captured = {"status": 0, "body": b""}
    state = {"reached": False}

    async def send(message):
        if message["type"] == "http.response.start":
            captured["status"] = message["status"]
        elif message["type"] == "http.response.body":
            captured["body"] += message.get("body", b"")

    async def auth_stub(scope, receive, send_):
        state["reached"] = True
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    app.auth = auth_stub
    scope = {
        "type": "http",
        "path": path,
        "method": "GET",
        "headers": headers or [],
        "client": (client_ip, 50000),
        "query_string": query,
    }

    async def receive():
        return {"type": "http.disconnect"}

    asyncio.run(app(scope, receive, send))
    return captured["status"], captured["body"], state["reached"]


@pytest.fixture
def gating_env(monkeypatch):
    """门控测试环境：开关/allowlist/信任代理均可按用例覆写。"""
    import server

    monkeypatch.setattr(server, "MCP_PUBLIC_MODE", False)
    monkeypatch.setattr(server, "MCP_PUBLIC_ALLOWLIST", set())
    monkeypatch.setattr(server, "MCP_TRUSTED_PROXY", set())
    app = _make_app(server)
    return server, app


# ── 1.1 配置默认值与解析 ──


def test_public_mode_defaults(monkeypatch) -> None:
    """未设环境变量时：开关默认关、allowlist 与信任代理默认空。"""
    for key in ("MCP_PUBLIC_MODE", "MCP_PUBLIC_ALLOWLIST", "MCP_TRUSTED_PROXY"):
        monkeypatch.delenv(key, raising=False)
    sys.modules.pop("server", None)
    fresh = importlib.reload(importlib.import_module("server"))
    try:
        assert fresh.MCP_PUBLIC_MODE is False
        assert fresh.MCP_PUBLIC_ALLOWLIST == set()
        assert fresh.MCP_TRUSTED_PROXY == set()
    finally:
        sys.modules.pop("server", None)
        importlib.reload(importlib.import_module("server"))


def test_public_mode_env_parsing(monkeypatch) -> None:
    """环境变量解析：开关认 1/true/on；逗号清单去空格成集合。"""
    monkeypatch.setenv("MCP_PUBLIC_MODE", "1")
    monkeypatch.setenv("MCP_PUBLIC_ALLOWLIST", "10.1.1.1, 10.1.1.2 ,")
    monkeypatch.setenv("MCP_TRUSTED_PROXY", "192.168.0.9")
    sys.modules.pop("server", None)
    fresh = importlib.reload(importlib.import_module("server"))
    try:
        assert fresh.MCP_PUBLIC_MODE is True
        assert fresh.MCP_PUBLIC_ALLOWLIST == {"10.1.1.1", "10.1.1.2"}
        assert fresh.MCP_TRUSTED_PROXY == {"192.168.0.9"}
    finally:
        sys.modules.pop("server", None)
        importlib.reload(importlib.import_module("server"))


# ── 1.2 真实客户端 IP 解析 ──


def _resolve(server, client_ip, headers):
    return server._resolve_client_ip(
        {"client": (client_ip, 50000), "headers": headers}
    )


def _xff(value):
    return [(b"x-forwarded-for", value.encode())]


def test_xff_ignored_without_trusted_proxy(gating_env) -> None:
    """未配置信任代理时，伪造 XFF 不改变本机/远程判定。"""
    server, _ = gating_env
    assert _resolve(server, "10.9.9.9", _xff("127.0.0.1")) == "10.9.9.9"
    assert _resolve(server, "127.0.0.1", _xff("10.9.9.9")) == "127.0.0.1"


def test_xff_taken_from_trusted_proxy(gating_env, monkeypatch) -> None:
    """直连来源命中信任代理时采信 XFF 最左值；头缺失时回落直连地址。"""
    server, _ = gating_env
    monkeypatch.setattr(server, "MCP_TRUSTED_PROXY", {"192.168.0.9"})
    assert _resolve(server, "192.168.0.9", _xff("8.8.8.8, 192.168.0.9")) == "8.8.8.8"
    assert _resolve(server, "192.168.0.9", []) == "192.168.0.9"


def test_xff_ignored_from_untrusted_source(gating_env, monkeypatch) -> None:
    """配置了信任代理但直连来源不在清单时仍用直连地址。"""
    server, _ = gating_env
    monkeypatch.setattr(server, "MCP_TRUSTED_PROXY", {"192.168.0.9"})
    assert _resolve(server, "10.9.9.9", _xff("127.0.0.1")) == "10.9.9.9"


# ── 1.3 路由门控矩阵 ──

_OPEN_PATHS = [
    "/", "/showcase", "/access", "/api/access-info",
    "/api/showcase/data", "/api/docs/export-skills",
    "/api/docs/export-skills-package",
]


def test_gate_off_allows_everything(gating_env, monkeypatch) -> None:
    """模式关闭时展示类远程来源按既有行为进入处理，pass 类不介入。"""
    server, app = gating_env
    monkeypatch.setattr(app, "_handle_access_info", _record_handler(app))
    for path in _OPEN_PATHS:
        status, _, _ = _drive_get(app, "10.9.9.9", path)
        assert status != 403, path
    status, _, reached = _drive_get(app, "10.9.9.9", "/mcp")
    assert status == 204 and reached

def _record_handler(app):
    """构造记录型展示页 handler 替身：门控放行则回 200。"""

    async def _handler(scope, send):
        await app._send_json(send, 200, {"ok": True})

    return _handler


def test_gate_on_remote_open_paths_403(gating_env, monkeypatch) -> None:
    """模式开启：展示类非本机来源 403，且响应不回显 allowlist 内容。"""
    server, app = gating_env
    monkeypatch.setattr(server, "MCP_PUBLIC_MODE", True)
    monkeypatch.setattr(server, "MCP_PUBLIC_ALLOWLIST", {"10.2.2.2"})
    for path in _OPEN_PATHS:
        status, body, _ = _drive_get(app, "10.9.9.9", path)
        assert status == 403, path
        assert b"10.2.2.2" not in body
        assert b"token" not in body.lower()


def test_gate_on_local_and_allowlist_and_bearer_paths(gating_env, monkeypatch) -> None:
    """模式开启：本机/allowlist 展示类放行；/mcp 与 mint 等既有鉴权路径不介入。"""
    server, app = gating_env
    monkeypatch.setattr(server, "MCP_PUBLIC_MODE", True)
    monkeypatch.setattr(server, "MCP_PUBLIC_ALLOWLIST", {"10.2.2.2"})
    monkeypatch.setattr(app, "_handle_access_info", _record_handler(app))
    status, _, _ = _drive_get(app, "127.0.0.1", "/api/access-info")
    assert status == 200
    status, _, _ = _drive_get(app, "10.2.2.2", "/api/access-info")
    assert status == 200
    status, _, reached = _drive_get(app, "10.9.9.9", "/mcp")
    assert status == 204 and reached
    # bearer 既有类由自身 handler/鉴权层处理（门控不介入）：
    # 无凭据的 401 来自既有鉴权而非门控的 403，证明既有行为不变
    for path in ("/api/mcp-token/mint", "/api/mcp-token/revoke",
                 "/api/archive/uploads"):
        status, _, _ = _drive_get(app, "10.9.9.9", path)
        assert status == 401, path


def test_gate_on_remote_xff_spoof_still_403(gating_env, monkeypatch) -> None:
    """远程来源伪造 XFF 声称本机：门控仍按直连地址拒绝。"""
    server, app = gating_env
    monkeypatch.setattr(server, "MCP_PUBLIC_MODE", True)
    status, _, _ = _drive_get(app, "10.9.9.9", "/", headers=_xff("127.0.0.1"))
    assert status == 403


# ── 1.4 URL 凭据端点收紧 ──


def _seed_template(server, tmp_path):
    """落一份真实快照模板，返回 (file_id, owner_id, token)。"""
    from archiving.models import TemplateSnapshot
    from archiving.snapshot_store import SnapshotStore, derive_owner_id
    from edge_tools import _generate_template_bytes
    import edge_tools

    owner_token = "route-bearer-token"
    owner_id = derive_owner_id(owner_token)
    store = SnapshotStore(base_dir=tmp_path)
    record = store.save(
        TemplateSnapshot(version="v15-engineer"),
        owner_id=owner_id,
        template_bytes=_generate_template_bytes(),
        template_name="gating_test.xlsx",
    )
    file_id = record.snapshot_id
    edge_template = store.read_template_bytes(file_id, owner_id=owner_id)
    return store, file_id, owner_id, owner_token, edge_template


def _drive_template(app, client_ip, query, bearer=None):
    headers = []
    if bearer:
        headers.append((b"authorization", f"Bearer {bearer}".encode()))
    status, body, _ = _drive_get(
        app, client_ip, f"/api/archive/templates/{query[0]}",
        query=query[1].encode(), headers=headers,
    )
    return status, body


def test_template_download_public_matrix(gating_env, monkeypatch, tmp_path) -> None:
    """公网模式 templates：无 Bearer 401 / 归属不一致 404 / 一致 200 / 本机不变。"""
    server, app = gating_env
    store, file_id, owner_id, owner_token, tpl_bytes = _seed_template(server, tmp_path)
    import edge_tools
    monkeypatch.setattr(edge_tools, "template_store", store)
    monkeypatch.setattr(server, "MCP_PUBLIC_MODE", True)
    query = (file_id, f"owner={owner_id}")

    # 远程无 Bearer → 401
    status, _ = _drive_template(app, "10.9.9.9", query)
    assert status == 401
    # 远程 Bearer 归属不一致 → 404（不泄漏存在性）
    status, _ = _drive_template(app, "10.9.9.9", query, bearer="someone-else")
    assert status == 404
    # 远程 Bearer 归属一致 → 200 且返回文件内容
    status, body = _drive_template(app, "10.9.9.9", query, bearer=owner_token)
    assert status == 200 and body == tpl_bytes
    # 本机维持票据直下（无需 Bearer）
    status, body = _drive_template(app, "127.0.0.1", query)
    assert status == 200 and body == tpl_bytes


def test_template_download_mode_off_unchanged(gating_env, monkeypatch, tmp_path) -> None:
    """模式关闭：远程票据直下行为与基线一致（无需 Bearer）。"""
    server, app = gating_env
    store, file_id, owner_id, _, tpl_bytes = _seed_template(server, tmp_path)
    import edge_tools
    monkeypatch.setattr(edge_tools, "template_store", store)
    status, body = _drive_template(
        app, "10.9.9.9", (file_id, f"owner={owner_id}")
    )
    assert status == 200 and body == tpl_bytes


def test_logs_remote_query_token_ignored(gating_env, monkeypatch) -> None:
    """公网模式 /api/logs：远程 ?token= 被忽略（count=0 等同无 Token），Bearer 头仍可用。"""
    server, app = gating_env
    entries = []

    class _Store:
        def list_current(self, owner_id, cursor=""):
            entries.append(owner_id)
            return ([], "")

        def get_current_trace(self, owner_id):
            return "trace-x"

    monkeypatch.setattr(server, "MCP_PUBLIC_MODE", True)
    monkeypatch.setattr(server, "_op_store", _Store())

    status, body, _ = _drive_get(
        app, "10.9.9.9", "/api/logs", query=b"token=some-token"
    )
    data = json.loads(body)
    assert status == 200 and data["count"] == 0 and entries == []

    # 本机来源 ?token= 仍可用（既有行为）
    _drive_get(app, "127.0.0.1", "/api/logs", query=b"token=some-token")
    assert entries and entries[-1]

    # 远程 Bearer 头仍可用
    status, body, _ = _drive_get(
        app, "10.9.9.9", "/api/logs",
        headers=[(b"authorization", b"Bearer some-token")],
    )
    data = json.loads(body)
    assert status == 200 and data["count"] == 0 and entries[-1]
