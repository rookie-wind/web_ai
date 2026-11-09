"""会话 API 门禁端点测试：/confirm 铸票、gate_blocked 入流回放、审计台账持久。

平台登录、mint/revoke、agent 句柄全部 fake，不依赖外网与真实 CLI。
GateProbeHandle 在 run_turn 中驱动注入的 WriteGate，验证"确认→放行/拒绝→
gate_blocked 事件落盘"整条链路联通。
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from webchat.api import create_app
from webchat.config import Settings
from webchat.hashing import encode_password
from webchat.runtime import SessionRuntime
from webchat.sdk_runtime import WEvent

FAST_ITERATIONS = 1000
PASSWORD = "test-password-1"
PHONE = "13900000000"
HOLDER = "holder-1"


class GateProbeHandle:
    """伪造 agent 句柄：run_turn 时用注入的 gate 逐条裁决脚本工具。"""

    script: list[tuple[str, dict]] = []

    def __init__(self, config, pat_env=None, gate=None):
        self.config = config
        self.gate = gate
        self.decisions: list[tuple[str, bool]] = []
        self.closed = False

    async def close(self):
        self.closed = True

    async def run_turn(self, prompt, **kwargs):
        for tool_name, tool_input in GateProbeHandle.script:
            allow, _reason = self.gate.decide(tool_name, tool_input)
            self.decisions.append((tool_name, allow))
            yield WEvent(
                type="tool_call", payload={"name": tool_name, "allow": allow}
            )
        yield WEvent(type="turn_done", payload={})


def _make_client(tmp_path, monkeypatch) -> TestClient:
    """构造带 fake 登录/mint/句柄的 TestClient。"""
    accounts_path = tmp_path / "accounts.json"
    accounts_path.write_text(
        json.dumps({
            "accounts": [{
                "username": "alice",
                "password_hash": encode_password(PASSWORD, FAST_ITERATIONS),
                "phone": PHONE,
                "code": "9413",
                "enabled": True,
            }]
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    permissions_path = tmp_path / "permissions.json"
    permissions_path.write_text(
        json.dumps({"superAccounts": {"userIds": [], "phones": []}}),
        encoding="utf-8",
    )
    settings = Settings(
        session_ttl=3600,
        rate_window=60,
        rate_max_failures=1000,
        accounts_path=str(accounts_path),
        permissions_path=str(permissions_path),
        platform_base_url="https://platform.test",
        host="127.0.0.1",
        port=8800,
        mint_secret="test-mint-secret",
        mint_url="http://127.0.0.1:8765",
        max_instances=4,
        max_sessions_per_user=2,
        max_turns=25,
        workspaces_dir=tmp_path / "workspaces",
        events_dir=tmp_path / "events",
        lease_ttl=45,
        grant_ttl=300,
        gate_audit_path=tmp_path / "gate_audit.jsonl",
    )

    async def fake_login(phone, code, base_url, transport=None):
        return {"userId": "1001", "phone": PHONE, "token": "biz-token-1"}

    async def fake_mint(self, username, session_id):
        return f"tok-{username}"

    async def fake_revoke(self, token):
        return None

    async def fake_activate(mcp_url, token, phone, code):
        # C7 2.3：桩掉平台授权激活，避免真实 /mcp 连接
        return {"success": True}

    monkeypatch.setattr(SessionRuntime, "_mint", fake_mint)
    monkeypatch.setattr(SessionRuntime, "_revoke", fake_revoke)
    monkeypatch.setattr("webchat.runtime.call_login_tool", fake_activate)
    monkeypatch.setattr("webchat.runtime.AgentHandle", GateProbeHandle)
    GateProbeHandle.script = []
    return TestClient(create_app(settings, platform_login_impl=fake_login))


def _bootstrap(client: TestClient) -> tuple[dict, str, str]:
    """登录 → 建会话 → 取租约，返回 (auth_header, session_id, state)。"""
    login = client.post(
        "/api/auth/login",
        json={"username": "alice", "password": PASSWORD},
    )
    assert login.status_code == 200, login.text
    token = login.json()["session_token"]
    headers = {"Authorization": f"Bearer {token}"}
    created = client.post("/api/sessions", headers=headers)
    assert created.status_code == 200, created.text
    session_id = created.json()["session_id"]
    leased = client.post(
        f"/api/sessions/{session_id}/lease",
        headers=headers,
        json={"holder_id": HOLDER},
    )
    assert leased.status_code == 200, leased.text
    return headers, session_id, client.app.state.auth


def test_confirm_requires_lease(tmp_path, monkeypatch):
    """非租约持有者确认 → 409（不铸票）。"""
    client = _make_client(tmp_path, monkeypatch)
    headers, session_id, state = _bootstrap(client)
    resp = client.post(
        f"/api/sessions/{session_id}/confirm",
        headers={**headers, "x-holder-id": "someone-else"},
        json={"target": "add_brand"},
    )
    assert resp.status_code == 409
    assert state.runtime._grants.check(session_id, "add_brand") is False


def test_confirm_mints_grant_and_audits(tmp_path, monkeypatch):
    """租约持有者确认 → 铸票 + 审计 confirm 落盘。"""
    client = _make_client(tmp_path, monkeypatch)
    headers, session_id, state = _bootstrap(client)
    resp = client.post(
        f"/api/sessions/{session_id}/confirm",
        headers={**headers, "x-holder-id": HOLDER},
        json={"target": "add_brand"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True
    assert state.runtime._grants.check(session_id, "add_brand") is True
    confirms = [
        e for e in state.audit.read_all()
        if e["decision"] == "confirm" and e["target"] == "add_brand"
    ]
    assert confirms and confirms[-1]["session_id"] == session_id


def test_confirm_rejects_empty_and_unknown_session(tmp_path, monkeypatch):
    """空目标 400；未知会话 404。"""
    client = _make_client(tmp_path, monkeypatch)
    headers, session_id, _ = _bootstrap(client)
    empty = client.post(
        f"/api/sessions/{session_id}/confirm",
        headers={**headers, "x-holder-id": HOLDER},
        json={"target": "   "},
    )
    assert empty.status_code == 400
    missing = client.post(
        "/api/sessions/nope/confirm",
        headers={**headers, "x-holder-id": HOLDER},
        json={"target": "add_brand"},
    )
    assert missing.status_code == 404


def test_confirm_refuses_forbidden_and_allows_provision(tmp_path, monkeypatch):
    """绝对禁止目标 login → 403 不铸票；provision edge_get_token → 200 铸票。"""
    client = _make_client(tmp_path, monkeypatch)
    headers, session_id, state = _bootstrap(client)
    forbidden = client.post(
        f"/api/sessions/{session_id}/confirm",
        headers={**headers, "x-holder-id": HOLDER},
        json={"target": "login", "tool_name": "login"},
    )
    assert forbidden.status_code == 403
    assert state.runtime._grants.check(session_id, "login") is False
    provision = client.post(
        f"/api/sessions/{session_id}/confirm",
        headers={**headers, "x-holder-id": HOLDER},
        json={"target": "edge_get_token", "tool_name": "edge_get_token"},
    )
    assert provision.status_code == 200, provision.text
    assert state.runtime._grants.check(session_id, "edge_get_token") is True
    # 审计 confirm 记录带来源 tool_name（修硬编码空串）
    confirms = [
        e for e in state.audit.read_all()
        if e["decision"] == "confirm" and e["target"] == "edge_get_token"
    ]
    assert confirms and confirms[-1]["tool_name"] == "edge_get_token"


def test_confirmed_grant_allows_and_denied_write_emits_event(tmp_path, monkeypatch):
    """确认后同目标写放行；未确认目标写被拒并产 gate_blocked，可回放。"""
    client = _make_client(tmp_path, monkeypatch)
    headers, session_id, state = _bootstrap(client)
    client.post(
        f"/api/sessions/{session_id}/confirm",
        headers={**headers, "x-holder-id": HOLDER},
        json={"target": "add_brand"},
    )
    GateProbeHandle.script = [
        ("mcp__xlpa__add_brand", {"brand": "X"}),   # 已确认 → allow
        ("mcp__xlpa__del_brand", {"brand": "Y"}),   # 未确认 → deny + gate_blocked
    ]
    runtime = state.runtime
    session = runtime.get(session_id)
    asyncio.run(runtime.run_message(session, "go", holder_id=HOLDER))

    history = client.get(
        f"/api/sessions/{session_id}/history", headers=headers
    ).json()["events"]
    blocked = [e for e in history if e["type"] == "gate_blocked"]
    assert blocked and blocked[0]["payload"]["tool_name"] == "del_brand"
    # 断线回放：after_seq 重放仍能取到 gate_blocked
    before = blocked[0]["seq"] - 1
    replayed = client.get(
        f"/api/sessions/{session_id}/history",
        headers=headers,
        params={"after_seq": before},
    ).json()["events"]
    assert any(e["type"] == "gate_blocked" for e in replayed)
    # 审计台账留有该次 deny
    assert any(
        e["decision"] == "deny" and e["tool_name"] == "del_brand"
        for e in state.audit.read_all()
    )


def test_message_rejected_when_turn_limit_reached(tmp_path, monkeypatch):
    """并发轮次名额耗尽 → 发送消息 409 系统繁忙（不拉起新轮次）。"""
    client = _make_client(tmp_path, monkeypatch)
    headers, session_id, state = _bootstrap(client)
    state.runtime._max_concurrent_turns = 1
    state.runtime._active_turns = 1
    resp = client.post(
        f"/api/sessions/{session_id}/messages",
        headers={**headers, "x-holder-id": HOLDER},
        json={"text": "hi"},
    )
    assert resp.status_code == 409
    assert "系统繁忙" in resp.json()["detail"]


def test_message_rejected_while_turn_running(tmp_path, monkeypatch):
    """同会话上一轮仍在执行 → 409，不并发拉起第二个轮次。"""
    client = _make_client(tmp_path, monkeypatch)
    headers, session_id, state = _bootstrap(client)
    state.runtime.get(session_id).turn_running = True
    resp = client.post(
        f"/api/sessions/{session_id}/messages",
        headers={**headers, "x-holder-id": HOLDER},
        json={"text": "hi"},
    )
    assert resp.status_code == 409
    assert "上一轮仍在执行" in resp.json()["detail"]


def test_confirm_reports_turn_running(tmp_path, monkeypatch):
    """确认响应带 turn_running，前端据此不在执行中自动续跑。"""
    client = _make_client(tmp_path, monkeypatch)
    headers, session_id, state = _bootstrap(client)
    resp = client.post(
        f"/api/sessions/{session_id}/confirm",
        headers={**headers, "x-holder-id": HOLDER},
        json={"target": "gen_script"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["turn_running"] is False
    state.runtime.get(session_id).turn_running = True
    again = client.post(
        f"/api/sessions/{session_id}/confirm",
        headers={**headers, "x-holder-id": HOLDER},
        json={"target": "gen_script"},
    )
    assert again.status_code == 200, again.text
    assert again.json()["turn_running"] is True


def test_abort_requires_lease_and_emits_event(tmp_path, monkeypatch):
    """中止端点：非租约 409；无执行轮次时返回 aborted=false 并留痕。"""
    client = _make_client(tmp_path, monkeypatch)
    headers, session_id, state = _bootstrap(client)
    denied = client.post(
        f"/api/sessions/{session_id}/abort",
        headers={**headers, "x-holder-id": "someone-else"},
        json={},
    )
    assert denied.status_code == 409
    resp = client.post(
        f"/api/sessions/{session_id}/abort",
        headers={**headers, "x-holder-id": HOLDER},
        json={},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["aborted"] is False
    events = client.get(
        f"/api/sessions/{session_id}/history", headers=headers
    ).json()["events"]
    assert any(e["type"] == "turn_aborted" for e in events)
    # 会话列表暴露 turn_running，供前端恢复“停止”按钮
    listed = client.get("/api/sessions", headers=headers).json()["sessions"]
    assert listed and "turn_running" in listed[0]


def test_audit_survives_session_close(tmp_path, monkeypatch):
    """会话结束后审计台账仍可查（不随会话生命周期清理）。"""
    client = _make_client(tmp_path, monkeypatch)
    headers, session_id, state = _bootstrap(client)
    client.post(
        f"/api/sessions/{session_id}/confirm",
        headers={**headers, "x-holder-id": HOLDER},
        json={"target": "plan-77"},
    )
    closed = client.post(f"/api/sessions/{session_id}/close", headers=headers)
    assert closed.status_code == 200
    # 票据随会话清理，但审计台账保留
    assert state.runtime._grants.check(session_id, "plan-77") is False
    entries = state.audit.read_all()
    assert any(
        e["decision"] == "confirm" and e["target"] == "plan-77" for e in entries
    )
