"""C7 组2 后端验证：gate 参数摘要 / 回放 / 授权激活 / 身份提取 / 限流真实 IP。

覆盖 tasks.md 2.1~2.5 的验证要求：
- 2.1 白名单提取、敏感键不出现、超长截断、反查分支与降级标记；
- 2.2 gate_blocked 事件落 event_store 可重放（history 仍含 arg_summary）；
- 2.3 mock /mcp 断言 login 被调用一次且失败时不产生会话记录；
- 2.4 实测形状提取 business_user_id/phone + is_super 命中；
- 2.5 伪造 XFF 不改变计数维度、命中信任代理按 XFF 最左值分桶、
  不同来源失败互不影响（账号级/来源级双阈值）。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import AsyncIterator

from starlette.requests import Request

from webchat.event_store import EventStore
from webchat.grants import GrantStore, WriteGate, build_arg_summary
from webchat.platform_auth import extract_account_identity, is_super_account
from webchat.ratelimit import RateLimiter
from webchat.runtime import SessionActivationFailed, SessionRuntime
from webchat.sdk_runtime import ActivationError, WEvent


# ── 脚手架 ──

class GateRecordingHandle:
    """run_turn 时经 gate 裁决一次云端写（触发 gate_blocked 事件）。"""

    def __init__(self, config, pat_env=None, gate=None):
        self.config = config
        self.gate = gate
        self.closed = False

    async def close(self):
        self.closed = True

    async def run_turn(self, prompt, **kwargs) -> AsyncIterator[WEvent]:
        self.gate.decide(
            "mcp__xlpa__add_brand",
            {"brand": "南瑞", "password": "secret123", "remark": "隐藏我"},
        )
        yield WEvent(type="text_delta", payload={"text": "ok"})
        yield WEvent(type="turn_done", payload={})


class PlanFlowHandle:
    """模拟计划工具事件流：tool_call → tool_result（plan 成功回包）。"""

    PLAN_JSON = json.dumps({
        "plan_id": "plan-7",
        "node_count": 3,
        "nodes": [
            {"device_type": "电表"},
            {"device_type": "水表"},
        ],
    }, ensure_ascii=False)

    def __init__(self, config, pat_env=None, gate=None):
        self.config = config
        self.gate = gate
        self.closed = False

    async def close(self):
        self.closed = True

    async def run_turn(self, prompt, **kwargs) -> AsyncIterator[WEvent]:
        yield WEvent(
            type="tool_call",
            payload={"id": "tu-1", "name": "mcp__xlpa__plan_device_archive"},
        )
        yield WEvent(
            type="tool_result",
            payload={
                "tool_use_id": "tu-1",
                "content": [{"type": "text", "text": self.PLAN_JSON}],
                "is_error": False,
            },
        )
        yield WEvent(type="turn_done", payload={})


def _http_scope(client_ip: str, xff: str | None = None) -> dict:
    """构造最小 http scope（带 client 与可选 X-Forwarded-For）。"""
    headers: list[tuple[bytes, bytes]] = []
    if xff is not None:
        headers.append((b"x-forwarded-for", xff.encode()))
    return {
        "type": "http",
        "method": "POST",
        "path": "/api/auth/login",
        "headers": headers,
        "client": (client_ip, 12345),
        "query_string": b"",
    }


# ── 2.1 build_arg_summary：白名单 / 敏感键 / 截断 ──

def test_arg_summary_whitelist_extraction():
    """白名单键提取，非白名单键一律不进摘要。"""
    summary = build_arg_summary({
        "brand": "南瑞",
        "model": "M1",
        "task_id": "t-9",
        "remark": "自由文本不应出现",
        "payload": {"nested": "dict 值不应出现"},
        "flag": True,
        "empty": "",
    })
    assert summary == {"brand": "南瑞", "model": "M1", "task_id": "t-9"}


def test_arg_summary_sensitive_keys_never_appear():
    """敏感键模式（password/token/code/phone 等）任何情况下不出现。"""
    raw = {
        "password": "p", "access_token": "t", "sms_code": "1234",
        "phoneNum": "13900000000", "secret": "s", "verify_key": "v",
        "auth_header": "a",
    }
    assert build_arg_summary(raw) == {}


def test_arg_summary_truncation_and_key_cap():
    """单值超 40 字符截断加省略号；最多 12 键。"""
    long_val = "长" * 60
    summary = build_arg_summary({"brand": long_val})
    assert summary["brand"] == "长" * 39 + "\u2026"
    many = {
        "brand": "1", "model": "2", "protocol": "3", "protocol_type": "4",
        "device_type": "5", "device_name": "6", "classify": "7",
        "plan_id": "8", "task_id": "9", "report_id": "10", "file_id": "11",
        "file_name": "12", "template_name": "13", "node_count": "14",
    }
    assert len(build_arg_summary(many)) == 12


# ── 2.1 WriteGate：arg_summary 分层与降级 ──

def _gate_with_events(summary_lookup=None):
    events: list = []
    store = GrantStore(ttl_seconds=300)
    gate = WriteGate(
        "sess-1", store,
        event_writer=lambda t, p: events.append((t, p)),
        summary_lookup=summary_lookup,
    )
    return gate, events


def test_gate_blocked_payload_carries_arg_summary_and_masks():
    """deny 事件带 arg_summary：白名单键在、敏感/非白名单键不在。"""
    gate, events = _gate_with_events()
    gate.decide(
        "mcp__xlpa__add_brand",
        {"brand": "南瑞", "token": "leak-me", "notes": "x" * 100},
    )
    assert events and events[0][0] == "gate_blocked"
    summary = events[0][1]["arg_summary"]
    assert summary["brand"] == "南瑞"
    assert "token" not in summary and "notes" not in summary


def test_gate_summary_lookup_merges_plan_fields():
    """反查分支：summary_lookup 命中时台数/设备类型并入摘要、无降级标记。"""
    gate, events = _gate_with_events(
        lambda target: (
            {"device_total": 3, "device_types": "电表、水表"}
            if target == "plan-7" else {}
        )
    )
    gate.decide(
        "mcp__xlpa__edge_upsert_device",
        {"plan_id": "plan-7", "device_name": "1号表"},
    )
    summary = events[0][1]["arg_summary"]
    assert summary["device_total"] == 3
    assert summary["device_types"] == "电表、水表"
    assert "note" not in summary


def test_gate_summary_unavailable_marks_note():
    """反查不足（无回调）：明示「摘要不可用，仅显示计划标识」。"""
    gate, events = _gate_with_events()
    gate.decide("mcp__xlpa__execute_archive_task", {"task_id": "t-5"})
    summary = events[0][1]["arg_summary"]
    assert summary["note"] == "摘要不可用，仅显示计划标识"
    assert summary["task_id"] == "t-5"


def test_gate_summary_lookup_crash_degrades():
    """反查回调抛异常：降级为明示不可用，不放大崩溃。"""
    def boom(_target: str) -> dict:
        raise RuntimeError("plan store down")

    gate, events = _gate_with_events(boom)
    gate.decide("mcp__xlpa__edge_upsert_device", {"plan_id": "plan-8"})
    summary = events[0][1]["arg_summary"]
    assert summary["note"] == "摘要不可用，仅显示计划标识"


# ── 2.2 事件落 event_store，history 回放仍含 arg_summary ──

def test_history_replay_keeps_arg_summary(client_factory, login_as):
    """run_message 产生的 gate_blocked 事件可经 history 重放且带摘要。"""
    client = client_factory(handle_cls=GateRecordingHandle)
    headers = login_as(client, "alice")
    created = client.post("/api/sessions", headers=headers)
    assert created.status_code == 200
    sid = created.json()["session_id"]
    state = client.app.state.auth
    session = state.runtime.get(sid)
    # 先取租约再跑消息（run_message 要求持有者一致）
    leased = client.post(
        f"/api/sessions/{sid}/lease", headers=headers,
        json={"holder_id": "holder-1"},
    )
    assert leased.status_code == 200
    asyncio.run(state.runtime.run_message(session, "写入品牌", holder_id="holder-1"))
    hist = client.get(f"/api/sessions/{sid}/history", headers=headers)
    assert hist.status_code == 200
    blocked = [
        e for e in hist.json()["events"] if e["type"] == "gate_blocked"
    ]
    assert blocked, "history 应可重放 gate_blocked 事件"
    payload = blocked[0]["payload"]
    assert payload["arg_summary"]["brand"] == "南瑞"
    assert "password" not in payload["arg_summary"]
    assert "secret123" not in json.dumps(payload, ensure_ascii=False)


def test_plan_summary_harvest_and_turn_done(client_factory, login_as):
    """tool_result 收割计划摘要进 plan_summaries；turn_done 带真实轮次。"""
    client = client_factory(handle_cls=PlanFlowHandle)
    headers = login_as(client, "alice")
    sid = client.post("/api/sessions", headers=headers).json()["session_id"]
    client.post(
        f"/api/sessions/{sid}/lease", headers=headers,
        json={"holder_id": "h1"},
    )
    state = client.app.state.auth
    session = state.runtime.get(sid)
    asyncio.run(state.runtime.run_message(session, "规划建档", holder_id="h1"))
    assert session.plan_summaries["plan-7"] == {
        # 设备类型按码点排序：「水」(U+6C34) < 「电」(U+7535)
        "device_total": 3, "device_types": "水表、电表",
    }
    hist = client.get(f"/api/sessions/{sid}/history", headers=headers)
    turn_done = [
        e for e in hist.json()["events"] if e["type"] == "turn_done"
    ]
    assert turn_done[-1]["payload"]["turn"] == 1
    assert isinstance(turn_done[-1]["payload"]["duration_ms"], int)


# ── 2.3 会话授权激活（design D9）──

def test_activation_called_once_with_account_creds(client_factory, login_as, monkeypatch):
    """mint 成功后恰好调用一次 login 激活，凭据来自账号库而非用户输入。"""
    calls: list[tuple] = []

    async def fake_activate(mcp_url, token, phone, code):
        calls.append((mcp_url, token, phone, code))
        return {"success": True}

    monkeypatch.setattr("webchat.runtime.call_login_tool", fake_activate)
    client = client_factory()
    headers = login_as(client, "alice")
    created = client.post("/api/sessions", headers=headers)
    assert created.status_code == 200
    assert len(calls) == 1
    mcp_url, token, phone, code = calls[0]
    assert mcp_url.endswith("/mcp")
    assert phone == "13900000000" and code == "9413"
    session = client.app.state.auth.runtime.get(created.json()["session_id"])
    assert token == session.mcp_token


def test_activation_failure_yields_502_and_no_session(client_factory, login_as, monkeypatch, tmp_path):
    """激活失败 → 502 可辨识原因；不产生会话记录、回滚工作区。"""
    async def failing_activate(mcp_url, token, phone, code):
        raise ActivationError("平台拒绝：凭据无效")

    monkeypatch.setattr("webchat.runtime.call_login_tool", failing_activate)
    client = client_factory()
    headers = login_as(client, "alice")
    created = client.post("/api/sessions", headers=headers)
    assert created.status_code == 502
    assert "激活失败" in created.json()["detail"]
    listed = client.get("/api/sessions", headers=headers)
    assert listed.json()["sessions"] == []
    workspaces = tmp_path / "workspaces"
    assert not any(workspaces.iterdir()), "失败会话的工作区必须回滚清理"


def test_runtime_rolls_back_slot_after_activation_failure(client_factory, login_as, monkeypatch):
    """激活失败释放实例槽位：后续会话仍可创建（配额不被中毒占用）。"""
    attempts = {"n": 0}

    async def flaky_activate(mcp_url, token, phone, code):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise ActivationError("瞬时故障")
        return {"ok": True}

    monkeypatch.setattr("webchat.runtime.call_login_tool", flaky_activate)
    client = client_factory(settings_kwargs={"max_instances": 1})
    headers = login_as(client, "alice")
    assert client.post("/api/sessions", headers=headers).status_code == 502
    # 槽位已回滚：第二次创建（max_instances=1）应成功而非 409
    assert client.post("/api/sessions", headers=headers).status_code == 200


def test_no_activation_without_account(tmp_path, monkeypatch):
    """未提供 account 凭据时不调激活（存量测试/无预设凭据场景）。"""
    calls: list[tuple] = []

    async def spy_activate(*args):
        calls.append(args)
        return {"ok": True}

    async def fake_mint(self, username, session_id):
        return f"tok-{username}"

    monkeypatch.setattr(SessionRuntime, "_mint", fake_mint)
    runtime = SessionRuntime(
        mint_url="http://mint.test",
        mint_secret="s",
        workspaces_dir=tmp_path / "workspaces",
        events=EventStore(tmp_path / "events"),
        activate=spy_activate,
    )
    session = asyncio.run(runtime.create("alice"))
    assert session.id
    assert calls == []
    assert Path(runtime._workspaces_dir) == tmp_path / "workspaces"


# ── 2.4 身份提取对齐（design D10）──

def test_extract_identity_real_world_shape():
    """实测形状 {data:{user:{userId:int, mobilePhone}}} 全字段提取。"""
    body = {"data": {"user": {
        "userId": 55, "mobilePhone": "13900000000", "token": "biz-abc",
    }}}
    identity = extract_account_identity(body)
    assert identity["userId"] == "55"
    assert identity["phone"] == "13900000000"
    assert identity["token"] == "biz-abc"


def test_is_super_matches_int_user_id():
    """整型 userId 经 str() 宽容后可命中 superAccounts（修复恒 False）。"""
    identity = extract_account_identity({"user": {"userId": 55, "phone": "139"}})
    super_accounts = {"userIds": {"55"}, "phones": set()}
    assert is_super_account(identity, super_accounts) is True


# ── 2.5 限流真实客户端 IP（design D11）──

def test_client_ip_trusted_proxy_semantics():
    """仅直连命中可信代理才采信 XFF 最左值；否则只用直连地址。"""
    from webchat.api import _client_ip

    spoof = Request(_http_scope("203.0.113.7", "1.2.3.4, 5.6.7.8"))
    # 未配置可信代理：任何转发头都不采信
    assert _client_ip(spoof) == "203.0.113.7"
    assert _client_ip(spoof, ("10.0.0.1",)) == "203.0.113.7"
    # 直连命中可信代理：取 XFF 最左值
    assert _client_ip(spoof, ("203.0.113.7",)) == "1.2.3.4"
    # 可信代理但无 XFF：回退直连地址
    plain = Request(_http_scope("10.0.0.1"))
    assert _client_ip(plain, ("10.0.0.1",)) == "10.0.0.1"


def test_rate_limiter_split_account_and_source_thresholds():
    """账号级阈值先触发；来源级独立更宽；不同来源互不影响。"""
    limiter = RateLimiter(window_seconds=60, max_failures=2, source_max_failures=5)
    for _ in range(2):
        limiter.record_failure("1.1.1.1", "alice")
    assert limiter.check("1.1.1.1", "alice") is not None
    assert limiter.check("1.1.1.1", "bob") is None
    # 来源级：多账号小额失败累计达 5 后封锁该 IP 的新账号
    limiter.record_failure("1.1.1.1", "carol")
    limiter.record_failure("1.1.1.1", "dave")
    limiter.record_failure("1.1.1.1", "erin")
    assert limiter.check("1.1.1.1", "frank") is not None
    # 不同来源互不影响
    assert limiter.check("2.2.2.2", "alice") is None


def test_limiter_default_source_follows_account_cap():
    """未配置来源级阈值时沿用账号级（向后兼容）。"""
    limiter = RateLimiter(window_seconds=60, max_failures=3)
    assert limiter.source_max_failures == 3


def test_login_buckets_by_xff_only_when_trusted(client_factory):
    """API 级：信任代理时按 XFF 分桶（换 XFF 即换桶）；不信任时伪造 XFF 无效。"""
    # 直连 "testclient" 命中可信代理 → XFF 值参与分桶
    client = client_factory(
        settings_kwargs={
            "rate_max_failures": 1,
            "trusted_proxies": ("testclient",),
        },
    )
    bad = {"username": "alice", "password": "wrong"}
    r1 = client.post("/api/auth/login", json=bad, headers={"X-Forwarded-For": "9.9.9.9"})
    assert r1.status_code == 401
    r2 = client.post("/api/auth/login", json=bad, headers={"X-Forwarded-For": "8.8.8.8"})
    assert r2.status_code == 401, "不同来源的失败应互不影响"
    r3 = client.post("/api/auth/login", json=bad, headers={"X-Forwarded-For": "9.9.9.9"})
    assert r3.status_code == 429, "同来源再次失败应触发账号级限流"

    # 未配置可信代理：伪造 XFF 不改变计数维度（同一直连桶连续累计）
    client2 = client_factory(settings_kwargs={"rate_max_failures": 1})
    assert client2.post(
        "/api/auth/login", json=bad,
        headers={"X-Forwarded-For": "9.9.9.9"},
    ).status_code == 401
    assert client2.post(
        "/api/auth/login", json=bad,
        headers={"X-Forwarded-For": "8.8.8.8"},
    ).status_code == 429


def test_settings_new_fields_parsed(monkeypatch):
    """WEBCHAT_LOGIN_SOURCE_MAX / WEBCHAT_TRUSTED_PROXY 解析。"""
    from webchat.config import load_settings

    env = {
        "WEBCHAT_ACCOUNTS_PATH": "a.json",
        "WEBCHAT_PERMISSIONS_PATH": "p.json",
        "WEBCHAT_MINT_SECRET": "s",
        "WEBCHAT_LOGIN_SOURCE_MAX": "120",
        "WEBCHAT_TRUSTED_PROXY": "10.0.0.1, 10.0.0.2",
    }
    settings = load_settings(env)
    assert settings.rate_source_max_failures == 120
    assert settings.trusted_proxies == ("10.0.0.1", "10.0.0.2")
    # 缺省：来源级 60、可信代理为空
    defaults = load_settings({k: v for k, v in env.items() if k not in (
        "WEBCHAT_LOGIN_SOURCE_MAX", "WEBCHAT_TRUSTED_PROXY")})
    assert defaults.rate_source_max_failures == 60
    assert defaults.trusted_proxies == ()
