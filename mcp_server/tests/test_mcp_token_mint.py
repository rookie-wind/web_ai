"""mint / revoke 端点测试（直接驱动 CompositeApp handler，最小 ASGI 桩）。"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

import pytest

_MCP_DIR = Path(__file__).parent.parent
if str(_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_MCP_DIR))


def _drive(handler, *, headers: list, body: bytes) -> tuple[int, dict]:
    """以最小 ASGI 桩驱动 handler，返回 (status, 解析后的 JSON body)。"""
    captured = {"status": 0, "body": b""}

    async def send(message):
        if message["type"] == "http.response.start":
            captured["status"] = message["status"]
        elif message["type"] == "http.response.body":
            captured["body"] += message.get("body", b"")

    scope = {
        "headers": headers,
        "client": ("127.0.0.1", 50000),
        "query_string": b"",
    }
    messages = [
        {"type": "http.request", "body": body, "more_body": False},
    ]

    async def receive():
        return messages.pop(0) if messages else {"type": "http.disconnect"}

    asyncio.run(handler(scope, receive, send))
    payload = json.loads(captured["body"].decode("utf-8")) if captured["body"] else {}
    return captured["status"], payload


@pytest.fixture
def mint_env(monkeypatch):
    """构造 mint 测试环境：secret + 回环白名单 + 真实 TokenManager。"""
    import server

    monkeypatch.setattr(server, "MINT_SECRET", "test-mint-secret")
    monkeypatch.setattr(server, "MINT_ALLOWED_IPS", {"127.0.0.1", "::1"})
    monkeypatch.setattr(server, "MINT_RATE_LIMIT", 100)
    monkeypatch.setattr(server, "MINT_TTL_DEFAULT", 7200)
    monkeypatch.setattr(server, "MINT_TTL_CAP", 86400)
    monkeypatch.setattr(server, "_mint_attempt_times", [])
    monkeypatch.setattr(server, "_mint_audit", [])
    with tempfile.TemporaryDirectory() as td:
        registry = Path(td) / "registry.json"
        manager = server.TokenManager(admin_token="", registry_path=registry)
        app = server.CompositeApp(None, "<html>", manager)
        yield server, app


def _secret_headers() -> list:
    return [(b"x-mint-secret", b"test-mint-secret")]


def test_mint_requires_secret(mint_env) -> None:
    """无 secret / 错误 secret → 401。"""
    server, app = mint_env
    status, _ = _drive(app._handle_mint, headers=[], body=b"{}")
    assert status == 401
    status2, _ = _drive(
        app._handle_mint, headers=[(b"x-mint-secret", b"wrong")], body=b"{}"
    )
    assert status2 == 401


def test_mint_rejects_foreign_source(mint_env) -> None:
    """来源不在白名单 → 403。"""
    server, app = mint_env
    captured = {"status": 0, "body": b""}

    async def send(message):
        if message["type"] == "http.response.start":
            captured["status"] = message["status"]
        elif message["type"] == "http.response.body":
            captured["body"] += message.get("body", b"")

    scope = {
        "headers": _secret_headers(),
        "client": ("10.9.9.9", 50000),
        "query_string": b"",
    }

    async def receive():
        return {"type": "http.disconnect"}

    asyncio.run(app._handle_mint(scope, receive, send))
    assert captured["status"] == 403


def test_mint_issues_usable_webchat_token(mint_env) -> None:
    """合法请求签出可用凭据：family/TTL/owner_ref 落入 registry。"""
    server, app = mint_env
    status, payload = _drive(
        app._handle_mint,
        headers=_secret_headers(),
        body=json.dumps({"username": "  alice  "}).encode("utf-8"),
    )
    assert status == 200
    token = payload["token"]
    assert payload["family"] == "webchat"
    assert payload["accessLevel"] == "user"
    assert payload["ttl"] == 7200
    # registry 记录完整（含 strip 规范化的 owner_ref）
    entry = app.token_manager.get_entry(token)
    assert entry["family"] == "webchat"
    assert entry["owner_ref"]
    assert "alice" not in entry["owner_ref"]  # 是摘要而非明文
    assert entry["expires_at"] is not None
    # 凭据可过 /mcp 鉴权语义
    assert app.token_manager.is_valid(token)
    # 审计存在且含 owner_ref
    assert server._mint_audit and server._mint_audit[-1]["username"] == "alice"


def test_mint_ttl_capped(mint_env) -> None:
    """ttl_seconds 超过上限被截断为 cap。"""
    server, app = mint_env
    status, payload = _drive(
        app._handle_mint,
        headers=_secret_headers(),
        body=json.dumps({"username": "bob", "ttl_seconds": 999999}).encode("utf-8"),
    )
    assert status == 200
    assert payload["ttl"] == 86400


def test_mint_rejects_missing_username(mint_env) -> None:
    """缺 username → 400。"""
    server, app = mint_env
    status, _ = _drive(app._handle_mint, headers=_secret_headers(), body=b"{}")
    assert status == 400


def test_revoke_webchat_only(mint_env) -> None:
    """revoke：webchat 族生效，IDE 族 403。"""
    server, app = mint_env
    # 先 mint 一把 webchat 凭据，并给同 manager 建一把 IDE 凭据
    status, payload = _drive(
        app._handle_mint,
        headers=_secret_headers(),
        body=json.dumps({"username": "alice"}).encode("utf-8"),
    )
    web_token = payload["token"]
    ide_token = app.token_manager.get_or_create_token("192.168.1.200")
    assert ide_token != web_token
    # IDE 族撤销被拒
    status, body = _drive(
        app._handle_revoke,
        headers=_secret_headers(),
        body=json.dumps({"token": ide_token}).encode("utf-8"),
    )
    assert status == 403
    assert app.token_manager.is_valid(ide_token)
    # webchat 族撤销生效
    status, body = _drive(
        app._handle_revoke,
        headers=_secret_headers(),
        body=json.dumps({"token": web_token}).encode("utf-8"),
    )
    assert status == 200
    assert not app.token_manager.is_valid(web_token)
    # 不存在 token → 404
    status, _ = _drive(
        app._handle_revoke,
        headers=_secret_headers(),
        body=json.dumps({"token": "metam_pat_deadbeef"}).encode("utf-8"),
    )
    assert status == 404


def test_mint_rate_limited(mint_env) -> None:
    """限流：窗口内超过上限 → 429。"""
    import time as _time

    server, app = mint_env
    server.MINT_RATE_LIMIT = 2
    server._mint_attempt_times = []
    # 前两次通过限流检查（不论后续成败）
    _drive(app._handle_mint, headers=_secret_headers(), body=b"{}")
    _drive(app._handle_mint, headers=_secret_headers(), body=b"{}")
    status, _ = _drive(app._handle_mint, headers=_secret_headers(), body=b"{}")
    assert status == 429
