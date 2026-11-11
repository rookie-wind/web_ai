"""会话 API 门禁端点测试：/confirm 铸票、gate_blocked 入流回放、审计台账持久。

平台登录、mint/revoke、agent 句柄全部 fake，不依赖外网与真实 CLI。
GateProbeHandle 在 run_turn 中驱动注入的 WriteGate，验证"确认→放行/拒绝→
gate_blocked 事件落盘"整条链路联通。
"""

from __future__ import annotations

import asyncio
import json
import time

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
        self.pat_env = pat_env
        self.gate = gate
        self.decisions: list[tuple[str, bool]] = []
        self.closed = False

    async def list_models(self) -> list[dict]:
        """返回测试用模型清单。"""
        return [
            {"value": "m1", "display_name": "Model 1", "is_enabled": True,
             "is_free": True, "price_factor": 1.0},
        ]

    async def set_model(self, model: str) -> None:
        """切换模型（测试桩，无操作）。"""
        pass

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


def _wait_status(
    client: TestClient, headers: dict, sid: str, want: str, timeout: float = 5.0
) -> dict:
    """轮询会话列表直到指定会话进入期望状态（后台慢路完成）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        items = client.get("/api/sessions", headers=headers).json()["sessions"]
        found = [x for x in items if x["session_id"] == sid]
        if found and found[0].get("status") == want:
            return found[0]
        time.sleep(0.05)
    raise AssertionError(f"session {sid} not '{want}' within {timeout}s")


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
    # 等待后台慢路就绪（写路径要求 ready，design D2）
    _wait_status(client, headers, session_id, "ready")
    leased = client.post(
        f"/api/sessions/{session_id}/lease",
        headers=headers,
        json={"holder_id": HOLDER},
    )
    assert leased.status_code == 200, leased.text
    return headers, session_id, client.app.state.auth


def test_write_paths_rejected_while_creating(tmp_path, monkeypatch) -> None:
    """初始化中写路径被拒：发消息/切模型 409「会话初始化中，请稍候」。"""

    class SlowHandle(GateProbeHandle):
        async def list_models(self) -> list[dict]:
            """模拟连接耗时：拉长 creating 窗口。"""
            await asyncio.sleep(0.6)
            return await GateProbeHandle.list_models(self)

    client = _make_client(tmp_path, monkeypatch)
    monkeypatch.setattr("webchat.runtime.AgentHandle", SlowHandle)
    # with 模式共享 portal：后台慢路跨请求持续推进（验证 creating 窗口）
    with client as c:
        login = c.post(
            "/api/auth/login",
            json={"username": "alice", "password": PASSWORD},
        )
        headers = {"Authorization": f"Bearer {login.json()['session_token']}"}
        created = c.post("/api/sessions", headers=headers)
        assert created.status_code == 200, created.text
        sid = created.json()["session_id"]
        leased = c.post(
            f"/api/sessions/{sid}/lease",
            headers=headers,
            json={"holder_id": HOLDER},
        )
        assert leased.status_code == 200, leased.text
        blocked = c.post(
            f"/api/sessions/{sid}/messages",
            headers={**headers, "x-holder-id": HOLDER},
            json={"text": "hi"},
        )
        assert blocked.status_code == 409, blocked.text
        assert "初始化中" in blocked.json()["detail"]
        model_blocked = c.post(
            f"/api/sessions/{sid}/model",
            headers={**headers, "x-holder-id": HOLDER},
            json={"model": "m1"},
        )
        assert model_blocked.status_code == 409, model_blocked.text
        # 初始化完成后写路径恢复
        _wait_status(c, headers, sid, "ready")
        ok = c.post(
            f"/api/sessions/{sid}/messages",
            headers={**headers, "x-holder-id": HOLDER},
            json={"text": "hi"},
        )
        assert ok.status_code == 200, ok.text


def test_list_sessions_includes_status(tmp_path, monkeypatch) -> None:
    """会话列表携带 status/status_error；失败会话呈 failed 且保留记录。"""
    from webchat.sdk_runtime import AdapterError

    class RejectingHandle(GateProbeHandle):
        async def list_models(self) -> list[dict]:
            """模拟 PAT 校验失败。"""
            raise AdapterError("bad pat")

    client = _make_client(tmp_path, monkeypatch)
    monkeypatch.setattr("webchat.runtime.AgentHandle", RejectingHandle)
    login = client.post(
        "/api/auth/login",
        json={"username": "alice", "password": PASSWORD},
    )
    headers = {"Authorization": f"Bearer {login.json()['session_token']}"}
    created = client.post(
        "/api/sessions",
        headers=headers,
        json={"account_source": "byo", "pat": "bad"},
    )
    assert created.status_code == 200, created.text
    sid = created.json()["session_id"]
    meta = _wait_status(client, headers, sid, "failed")
    assert "bad pat" in (meta.get("status_error") or "")
    # 失败记录保留供查看与删除（不再无残留）
    items = client.get("/api/sessions", headers=headers).json()["sessions"]
    assert [x["session_id"] for x in items] == [sid]


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


def test_create_session_byo_pat_binds_account(tmp_path, monkeypatch) -> None:
    """自带 PAT 建会话：会话绑定 byo 账号，句柄 pat_env 收到该 PAT（仅经 env）。"""
    client = _make_client(tmp_path, monkeypatch)
    login = client.post(
        "/api/auth/login",
        json={"username": "alice", "password": PASSWORD},
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['session_token']}"}
    created = client.post(
        "/api/sessions",
        headers=headers,
        json={"account_source": "byo", "pat": "byo-pat-123"},
    )
    assert created.status_code == 200, created.text
    session_id = created.json()["session_id"]
    _wait_status(client, headers, session_id, "ready")
    state = client.app.state.auth
    session = state.runtime.get(session_id)
    assert session.account_source == "byo"
    assert session.handle is not None
    assert session.handle.pat_env == "byo-pat-123"


def test_create_session_rejects_invalid_pat(tmp_path, monkeypatch) -> None:
    """无效自带 PAT → 会话转 failed（原因可辨识），记录保留可删除。"""
    from webchat.sdk_runtime import AdapterError

    class RejectingHandle(GateProbeHandle):
        async def list_models(self) -> list[dict]:
            """模拟握手超时或无效 PAT。"""
            raise AdapterError("handshake timeout / invalid PAT")

    client = _make_client(tmp_path, monkeypatch)
    monkeypatch.setattr("webchat.runtime.AgentHandle", RejectingHandle)
    login = client.post(
        "/api/auth/login",
        json={"username": "alice", "password": PASSWORD},
    )
    headers = {"Authorization": f"Bearer {login.json()['session_token']}"}
    created = client.post(
        "/api/sessions",
        headers=headers,
        json={"account_source": "byo", "pat": "bad-pat"},
    )
    assert created.status_code == 200, created.text
    sid = created.json()["session_id"]
    meta = _wait_status(client, headers, sid, "failed")
    assert "PAT" in (meta.get("status_error") or "")
    state = client.app.state.auth
    assert len(state.runtime.list_for("alice")) == 1  # 失败记录保留
    failed = [
        e for e in state.events.replay(sid) if e["type"] == "session_failed"
    ]
    assert failed and "PAT" in failed[0]["payload"]["message"]


def test_default_account_unavailable_prompts_byo(tmp_path, monkeypatch) -> None:
    """默认账号校验失败 → 会话转 failed，原因提示需自带 PAT。"""
    from webchat.sdk_runtime import AdapterError

    class RejectingHandle(GateProbeHandle):
        async def list_models(self) -> list[dict]:
            """模拟无可用凭据。"""
            raise AdapterError("no credentials available")

    client = _make_client(tmp_path, monkeypatch)
    monkeypatch.setattr("webchat.runtime.AgentHandle", RejectingHandle)
    login = client.post(
        "/api/auth/login",
        json={"username": "alice", "password": PASSWORD},
    )
    headers = {"Authorization": f"Bearer {login.json()['session_token']}"}
    created = client.post("/api/sessions", headers=headers)
    assert created.status_code == 200, created.text
    sid = created.json()["session_id"]
    meta = _wait_status(client, headers, sid, "failed")
    assert "自带" in (meta.get("status_error") or "")


def test_session_models_list_enabled_only(tmp_path, monkeypatch) -> None:
    """会话模型清单经 API 暴露，只列启用模型并带成本字段。"""
    class MixedModelsHandle(GateProbeHandle):
        async def list_models(self) -> list[dict]:
            """返回测试用模型清单。"""
            return [
                {"value": "m1", "display_name": "Model 1", "is_enabled": True,
                 "is_free": True, "price_factor": 1.0},
                {"value": "m2", "display_name": "Disabled", "is_enabled": False,
                 "is_free": False, "price_factor": 2.0},
            ]

    client = _make_client(tmp_path, monkeypatch)
    monkeypatch.setattr("webchat.runtime.AgentHandle", MixedModelsHandle)
    headers, session_id, _state = _bootstrap(client)
    resp = client.get(f"/api/sessions/{session_id}/models", headers=headers)
    assert resp.status_code == 200, resp.text
    models = resp.json()["models"]
    assert [m["value"] for m in models] == ["m1"]
    assert models[0]["display_name"] == "Model 1"
    assert models[0]["is_free"] is True
    assert models[0]["price_factor"] == 1.0


def test_set_model_endpoint(tmp_path, monkeypatch) -> None:
    """模型切换端点：清单内放行并更新 current_model，越清单拒绝。"""
    class TwoModelsHandle(GateProbeHandle):
        async def list_models(self) -> list[dict]:
            """返回测试用模型清单。"""
            return [
                {"value": "m1", "display_name": "M1", "is_enabled": True,
                 "is_free": True, "price_factor": 1.0},
                {"value": "m2", "display_name": "M2", "is_enabled": True,
                 "is_free": False, "price_factor": 2.0},
            ]

    client = _make_client(tmp_path, monkeypatch)
    monkeypatch.setattr("webchat.runtime.AgentHandle", TwoModelsHandle)
    headers, session_id, state = _bootstrap(client)
    ok = client.post(
        f"/api/sessions/{session_id}/model",
        headers={**headers, "x-holder-id": HOLDER},
        json={"model": "m2"},
    )
    assert ok.status_code == 200, ok.text
    assert state.runtime.get(session_id).current_model == "m2"
    bad = client.post(
        f"/api/sessions/{session_id}/model",
        headers={**headers, "x-holder-id": HOLDER},
        json={"model": "nope"},
    )
    assert bad.status_code >= 400


def test_remembered_pat_prefill_and_revalidate(tmp_path, monkeypatch) -> None:
    """记住 PAT 持久化 + 预填端点；失效 PAT 建会话仍被重校验拒绝。"""
    client = _make_client(tmp_path, monkeypatch)
    login = client.post(
        "/api/auth/login",
        json={"username": "alice", "password": PASSWORD},
    )
    headers = {"Authorization": f"Bearer {login.json()['session_token']}"}
    created = client.post(
        "/api/sessions",
        headers=headers,
        json={"account_source": "byo", "pat": "remembered-pat", "remember": True},
    )
    assert created.status_code == 200, created.text
    _wait_status(client, headers, created.json()["session_id"], "ready")
    state = client.app.state.auth
    assert state.accounts.find("alice").qoder_pat == "remembered-pat"
    pre = client.get("/api/account/qoder-pat", headers=headers)
    assert pre.status_code == 200, pre.text
    assert pre.json()["pat"] == "remembered-pat"
    # 失效重校验：换拒绝句柄，用记住的 PAT 建会话 → failed（不落盘新记录）
    from webchat.sdk_runtime import AdapterError

    class RejectingHandle(GateProbeHandle):
        async def list_models(self) -> list[dict]:
            """模拟凭据过期。"""
            raise AdapterError("expired")

    monkeypatch.setattr("webchat.runtime.AgentHandle", RejectingHandle)
    bad = client.post(
        "/api/sessions",
        headers=headers,
        json={"account_source": "byo", "pat": "remembered-pat"},
    )
    assert bad.status_code == 200, bad.text
    _wait_status(client, headers, bad.json()["session_id"], "failed")


def test_e2e_model_account_flow(tmp_path, monkeypatch) -> None:
    """端到端：建自带账号会话→清单→发消息→切模型→回放→记住/清除。"""
    class FlowHandle(GateProbeHandle):
        async def list_models(self) -> list[dict]:
            """返回测试用模型清单。"""
            return [
                {"value": "m1", "display_name": "M1", "is_enabled": True,
                 "is_free": True, "price_factor": 1.0},
                {"value": "m2", "display_name": "M2", "is_enabled": True,
                 "is_free": False, "price_factor": 2.0},
            ]

    client = _make_client(tmp_path, monkeypatch)
    monkeypatch.setattr("webchat.runtime.AgentHandle", FlowHandle)
    login = client.post(
        "/api/auth/login",
        json={"username": "alice", "password": PASSWORD},
    )
    headers = {"Authorization": f"Bearer {login.json()['session_token']}"}
    created = client.post(
        "/api/sessions",
        headers=headers,
        json={"account_source": "byo", "pat": "flow-pat", "remember": True},
    )
    assert created.status_code == 200, created.text
    sid = created.json()["session_id"]
    _wait_status(client, headers, sid, "ready")
    state = client.app.state.auth
    session = state.runtime.get(sid)
    assert session.account_source == "byo"
    assert session.qoder_pat == "flow-pat"
    assert [m["value"] for m in session.models] == ["m1", "m2"]
    models = client.get(f"/api/sessions/{sid}/models", headers=headers).json()
    assert [m["value"] for m in models["models"]] == ["m1", "m2"]
    # 发消息（直接 run 以求确定性）
    session.hold_lease(HOLDER, 45)
    asyncio.run(state.runtime.run_message(session, "你好", holder_id=HOLDER))
    handle_before = session.handle
    # 切模型 m2：session_id 与句柄不变
    sw = client.post(
        f"/api/sessions/{sid}/model",
        headers={**headers, "x-holder-id": HOLDER},
        json={"model": "m2"},
    )
    assert sw.status_code == 200, sw.text
    assert session.current_model == "m2"
    assert session.handle is handle_before
    assert session.id == sid
    asyncio.run(state.runtime.run_message(session, "再见", holder_id=HOLDER))
    hist = client.get(
        f"/api/sessions/{sid}/history", headers=headers
    ).json()["events"]
    seqs = [e["seq"] for e in hist]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    assert sum(e["type"] == "turn_done" for e in hist) == 2
    # 记住与清除
    assert client.get(
        "/api/account/qoder-pat", headers=headers
    ).json()["pat"] == "flow-pat"
    assert client.delete(
        "/api/account/qoder-pat", headers=headers
    ).status_code == 200
    assert client.get(
        "/api/account/qoder-pat", headers=headers
    ).json()["pat"] == ""


def test_create_byo_empty_pat_rejected(tmp_path, monkeypatch) -> None:
    """byo 空 PAT 不静默回落本机登录态 → 会话转 failed（原因可辨识）。"""
    client = _make_client(tmp_path, monkeypatch)
    login = client.post(
        "/api/auth/login",
        json={"username": "alice", "password": PASSWORD},
    )
    headers = {"Authorization": f"Bearer {login.json()['session_token']}"}
    created = client.post(
        "/api/sessions",
        headers=headers,
        json={"account_source": "byo", "pat": "  "},
    )
    assert created.status_code == 200, created.text
    meta = _wait_status(client, headers, created.json()["session_id"], "failed")
    assert "PAT" in (meta.get("status_error") or "")


def test_create_empty_model_list_rejected(tmp_path, monkeypatch) -> None:
    """账号返回空清单 → 会话转 failed，不留模型不可用的可用会话。"""
    class EmptyModelsHandle(GateProbeHandle):
        async def list_models(self) -> list[dict]:
            """返回空模型清单。"""
            return []

    client = _make_client(tmp_path, monkeypatch)
    monkeypatch.setattr("webchat.runtime.AgentHandle", EmptyModelsHandle)
    login = client.post(
        "/api/auth/login",
        json={"username": "alice", "password": PASSWORD},
    )
    headers = {"Authorization": f"Bearer {login.json()['session_token']}"}
    created = client.post(
        "/api/sessions",
        headers=headers,
        json={"account_source": "byo", "pat": "p"},
    )
    assert created.status_code == 200, created.text
    meta = _wait_status(client, headers, created.json()["session_id"], "failed")
    assert "可用模型" in (meta.get("status_error") or "")


def test_create_validation_failure_rolls_back(tmp_path, monkeypatch) -> None:
    """校验抛原始 SDK 异常也回滚槽位/凭据，失败记录保留，随后可正常创建。"""
    class BoomHandle(GateProbeHandle):
        async def list_models(self) -> list[dict]:
            """模拟 SDK 原始异常。"""
            raise RuntimeError("raw sdk boom")

    client = _make_client(tmp_path, monkeypatch)
    monkeypatch.setattr("webchat.runtime.AgentHandle", BoomHandle)
    login = client.post(
        "/api/auth/login",
        json={"username": "alice", "password": PASSWORD},
    )
    headers = {"Authorization": f"Bearer {login.json()['session_token']}"}
    bad = client.post(
        "/api/sessions",
        headers=headers,
        json={"account_source": "byo", "pat": "p"},
    )
    assert bad.status_code == 200, bad.text
    bad_sid = bad.json()["session_id"]
    meta = _wait_status(client, headers, bad_sid, "failed")
    assert "raw sdk boom" in (meta.get("status_error") or "")
    state = client.app.state.auth
    assert state.runtime.get(bad_sid).closed is True  # close 语义回收
    assert state.runtime._user_counts.get("alice", 0) == 0
    # 槽位已回滚：换正常句柄可再创建
    monkeypatch.setattr("webchat.runtime.AgentHandle", GateProbeHandle)
    ok = client.post("/api/sessions", headers=headers)
    assert ok.status_code == 200, ok.text
    _wait_status(client, headers, ok.json()["session_id"], "ready")
