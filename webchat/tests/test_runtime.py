"""会话运行时测试（fake mint/revoke 与 fake agent 句柄）。"""

from __future__ import annotations

import asyncio
import time

import pytest

from webchat.artifacts import ArtifactRegistry
from webchat.errors import InvalidQoderPat, SessionActivationFailed
from webchat.event_store import EventStore
from webchat.runtime import (
    QuotaExceeded,
    SessionRuntime,
    WebSession,
)
from webchat.sdk_runtime import ActivationError, TurnAborted, WEvent


class FakeHandle:
    """伪造 agent 句柄：产出两段固定事件后结束。"""

    def __init__(self, config, pat_env=None, gate=None):
        self.config = config
        self.pat_env = pat_env
        self.gate = gate
        self.closed = False
        self.stop = asyncio.Event()

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
        yield WEvent(type="text_delta", payload={"text": f"echo:{prompt[:20]}"})
        yield WEvent(type="tool_call", payload={"name": "list_mcp_tools", "input": {}})
        yield WEvent(type="turn_done", payload={})


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    """构造运行时：fake mint/revoke + fake handle。"""
    minted: list[str] = []
    revoked: list[str] = []

    async def fake_mint(self, username, session_id):
        token = f"tok-{username}-{len(minted)}"
        minted.append(token)
        return token

    async def fake_revoke(self, token):
        revoked.append(token)

    monkeypatch.setattr(SessionRuntime, "_mint", fake_mint)
    monkeypatch.setattr(SessionRuntime, "_revoke", fake_revoke)
    monkeypatch.setattr("webchat.runtime.AgentHandle", FakeHandle)
    events = EventStore(tmp_path / "events")
    rt = SessionRuntime(
        mint_url="http://127.0.0.1:8765",
        mint_secret="x",
        workspaces_dir=tmp_path / "ws",
        events=events,
        max_instances=2,
        max_sessions_per_user=2,
        max_turns=25,
        lease_ttl=45,
    )
    rt._mint_log = minted  # 测试观察用
    rt._revoke_log = revoked
    return rt


@pytest.mark.asyncio
async def test_create_returns_fast_creating(runtime):
    """快路只做注册：create 返回时 creating、无句柄、清单未就绪。"""
    s = await runtime.create("alice")
    assert s.status == "creating"
    assert s.handle is None
    assert s.models == []
    assert [e["type"] for e in runtime._events.replay(s.id)] == ["session_started"]


@pytest.mark.asyncio
async def test_initialize_session_ready(runtime):
    """显式慢路：激活+连接+清单完成后 ready 并填充模型。"""
    s = await runtime.create("alice")
    # 不传 account：不执行平台激活（存量测试/无预设凭据场景）
    await runtime.initialize_session(
        s, account_source="byo", qoder_pat="p"
    )
    assert s.status == "ready"
    assert s.handle is not None
    assert s.current_model == "m1"
    assert s.account_source == "byo"


@pytest.mark.asyncio
async def test_initialize_emits_ready_event(runtime):
    """慢路就绪写入 session_ready 事件（payload 无凭据）。"""
    s = await runtime.create("alice")
    await runtime.initialize_session(s, account_source="byo", qoder_pat="p")
    events = runtime._events.replay(s.id)
    ready = [e for e in events if e["type"] == "session_ready"]
    assert len(ready) == 1
    assert "pat" not in str(ready[0]["payload"]).lower()


@pytest.mark.asyncio
async def test_initialize_activation_failure_emits_failed(runtime, monkeypatch):
    """慢路激活失败：写 session_failed（含原因）且回滚无残留。"""

    async def fail_activate(mcp_url, token, phone, code):
        raise ActivationError("boom")

    # _activate 是实例属性（init 时绑定），直接替换实例引用
    monkeypatch.setattr(runtime, "_activate", fail_activate)
    s = await runtime.create("alice")
    # 走生产路径 finalize：失败统一转 failed 并回收（design D2）
    await runtime.finalize_session(
        s, account={"phone": "13900000000", "code": "9413"}, timeout=5
    )
    assert s.status == "failed"
    events = runtime._events.replay(s.id)
    failed = [e for e in events if e["type"] == "session_failed"]
    assert len(failed) == 1
    assert "boom" in failed[0]["payload"]["message"]
    # 失败记录保留（closed 供列表呈现与删除，design D2）
    assert len(runtime.list_for("alice")) == 1
    assert runtime.list_for("alice")[0].closed is True


@pytest.mark.asyncio
async def test_failed_session_releases_once(runtime, monkeypatch):
    """慢路失败：槽位/每用户配额恰好释放一次，工作区删除。"""

    async def fail_activate(mcp_url, token, phone, code):
        raise ActivationError("boom")

    monkeypatch.setattr(runtime, "_activate", fail_activate)
    s = await runtime.create("alice")
    ws = s.workspace
    await runtime.finalize_session(
        s, account={"phone": "13900000000", "code": "9413"}, timeout=5
    )
    assert s.status == "failed"
    assert runtime._user_counts.get("alice", 0) == 0
    assert not ws.exists()
    # 信号量恰好释放一次：再创建不被槽位繁忙阻塞（2 上限）
    s2 = await runtime.create("bob")
    b2 = await runtime.create("bob")
    assert s2.id != b2.id


@pytest.mark.asyncio
async def test_failed_then_recreate_succeeds(runtime):
    """失败回滚后立即再创建成功（无槽位/配额泄漏）。"""

    async def fail_activate(mcp_url, token, phone, code):
        raise ActivationError("boom")

    runtime._activate = fail_activate
    s = await runtime.create("alice")
    await runtime.finalize_session(
        s, account={"phone": "13900000000", "code": "9413"}, timeout=5
    )
    s2 = await runtime.create("alice")
    await runtime.initialize_session(s2)
    assert s2.status == "ready"


@pytest.mark.asyncio
async def test_failed_byo_empty_pat_rolls_back(runtime):
    """自带 PAT 为空：失败事件可辨识且回滚无残留。"""
    s = await runtime.create("alice")
    await runtime.finalize_session(
        s, account_source="byo", qoder_pat="", timeout=5
    )
    assert len(runtime.list_for("alice")) == 1
    failed = [
        e for e in runtime._events.replay(s.id)
        if e["type"] == "session_failed"
    ]
    assert failed and "PAT" in failed[0]["payload"]["message"]


@pytest.mark.asyncio
async def test_delete_during_init_no_stray_events(runtime, monkeypatch):
    """初始化中关闭会话：慢路被取消，不再写失败事件，资源由 close 回收。"""
    started = asyncio.Event()

    async def slow_activate(mcp_url, token, phone, code):
        started.set()
        await asyncio.sleep(5)
        raise ActivationError("late")

    monkeypatch.setattr(runtime, "_activate", slow_activate)
    s = await runtime.create("alice")
    task = asyncio.create_task(
        runtime.finalize_session(
            s, account={"phone": "13900000000", "code": "9413"}, timeout=30
        )
    )
    s.init_task = task
    await asyncio.wait_for(started.wait(), timeout=2)
    await runtime.close(s)
    assert task.done() and task.cancelled()
    types = [e["type"] for e in runtime._events.replay(s.id)]
    assert "session_failed" not in types
    assert "session_closed" in types
    assert s.closed is True


@pytest.mark.asyncio
async def test_initialize_timeout_fails(runtime, monkeypatch):
    """慢路超时：转 failed、保留记录、写 session_failed 与 session_closed。"""

    async def slow_activate(mcp_url, token, phone, code):
        await asyncio.sleep(3)
        raise ActivationError("late")

    monkeypatch.setattr(runtime, "_activate", slow_activate)
    s = await runtime.create("alice")
    await runtime.finalize_session(
        s, account={"phone": "13900000000", "code": "9413"}, timeout=0.1
    )
    assert s.status == "failed"
    assert "超时" in s.status_error
    assert s.closed is True
    types = [e["type"] for e in runtime._events.replay(s.id)]
    assert "session_failed" in types
    assert "session_closed" in types
    # 配额已释放：可再创建
    s2 = await runtime.create("alice")
    assert s2.id != s.id


@pytest.mark.asyncio
async def test_1to1_binding(runtime):
    """两会话（不同用户）：凭据/工作区互不相同。"""
    a = await runtime.create("alice")
    b = await runtime.create("bob")
    assert a.mcp_token != b.mcp_token
    assert a.workspace != b.workspace
    assert (a.workspace / "xlpa-output").exists()
    assert runtime._mint_log == [a.mcp_token, b.mcp_token]
    # 事件流互不串扰：各自 session_started 落在各自分区
    assert runtime._events.replay(a.id)[0]["session_id"] == a.id
    assert runtime._events.replay(b.id)[0]["session_id"] == b.id


@pytest.mark.asyncio
async def test_create_session_default_account_uses_global_pat(runtime) -> None:
    """不带账号选择 → 默认账号，沿用全局 PAT 与配置默认模型（向后兼容）。"""
    runtime._pat = "global-pat"
    runtime._agent_model = "Qwen3.8-Flash"
    s = await runtime.create("alice")
    await runtime.initialize_session(s)
    assert s.account_source == "default"
    assert s.qoder_pat == "global-pat"
    assert s.handle is not None
    assert s.handle.pat_env == "global-pat"
    assert s.handle.config.model == "Qwen3.8-Flash"


@pytest.mark.asyncio
async def test_account_bound_at_build_not_switched(runtime) -> None:
    """账号会话级固定：跨轮复用同一句柄，pat_env 与账号来源不变。"""
    s = await runtime.create("alice")
    await runtime.initialize_session(
        s, account_source="byo", qoder_pat="byo-pat"
    )
    s.hold_lease("h1", 45)
    handle = s.handle
    assert handle is not None
    await runtime.run_message(s, "第一轮", holder_id="h1")
    await runtime.run_message(s, "第二轮", holder_id="h1")
    assert s.handle is handle  # 同一句柄，未重建
    assert s.handle.pat_env == "byo-pat"
    assert s.account_source == "byo"
    assert s.qoder_pat == "byo-pat"


@pytest.mark.asyncio
async def test_default_model_preselect_rule(runtime) -> None:
    """预选：配置默认在清单则优先，否则取清单首个启用模型。"""
    # FakeHandle.list_models 返回 canned [m1]
    runtime._agent_model = "m1"
    s = await runtime.create("alice")
    await runtime.initialize_session(
        s, account_source="byo", qoder_pat="p"
    )
    assert s.current_model == "m1"  # 配置默认在清单 → 优先
    runtime._agent_model = "not-in-list"
    s2 = await runtime.create("bob")
    await runtime.initialize_session(
        s2, account_source="byo", qoder_pat="p"
    )
    assert s2.current_model == "m1"  # 配置默认不在清单 → 首个启用


@pytest.mark.asyncio
async def test_switch_model_outside_list_rejected(runtime) -> None:
    """切换到账号清单外的模型被拒绝，current_model 不变。"""
    s = await runtime.create("alice")
    await runtime.initialize_session(
        s, account_source="byo", qoder_pat="p"
    )
    with pytest.raises(ValueError):
        await runtime.set_model(s, "not-in-list")
    assert s.current_model == "m1"


@pytest.mark.asyncio
async def test_switch_model_during_turn_rejected(runtime) -> None:
    """执行中轮次拒绝切换模型（沿用串行约束）。"""
    s = await runtime.create("alice")
    await runtime.initialize_session(
        s, account_source="byo", qoder_pat="p"
    )
    s.turn_running = True
    with pytest.raises(ValueError):
        await runtime.set_model(s, "m1")


@pytest.mark.asyncio
async def test_set_model_keeps_state_on_sdk_failure(runtime) -> None:
    """SDK 切模型失败时 current_model 不变（先调 SDK 成功再改状态）。"""
    s = await runtime.create("alice")
    await runtime.initialize_session(
        s, account_source="byo", qoder_pat="p"
    )

    class FailSwitch:
        async def set_model(self, model: str) -> None:
            """模拟模型切换失败。"""
            raise RuntimeError("sdk fail")

    s.handle = FailSwitch()
    s.models.append({"value": "m2", "display_name": "M2", "is_enabled": True})
    with pytest.raises(RuntimeError):
        await runtime.set_model(s, "m2")
    assert s.current_model == "m1"


@pytest.mark.asyncio
async def test_quota_limits(runtime):
    """全局实例上限与每用户上限：超限明确拒绝。"""
    a1 = await runtime.create("alice")
    a2 = await runtime.create("alice")
    with pytest.raises(QuotaExceeded):
        await runtime.create("alice")  # 每用户上限 2
    with pytest.raises(QuotaExceeded):
        await runtime.create("bob")  # 全局实例上限 2
    await runtime.close(a1)
    # 释放后可再创建
    b1 = await runtime.create("bob")
    assert b1.mcp_token.startswith("tok-bob")


@pytest.mark.asyncio
async def test_lease_semantics(runtime):
    """租约：持有者独占、过期释放、takeover 覆盖。"""
    s = await runtime.create("alice")
    assert s.hold_lease("h1", 45) is True
    assert s.hold_lease("h2", 45) is False  # 被 h1 持有
    assert s.has_lease("h1") is True
    # 过期后 h2 可接管
    s.lease_expires = time.time() - 1
    assert s.hold_lease("h2", 45) is True
    assert s.has_lease("h1") is False


@pytest.mark.asyncio
async def test_run_message_requires_lease_and_appends(runtime):
    """无租约拒绝；有租约执行并落盘有序事件。"""
    s = await runtime.create("alice")
    with pytest.raises(PermissionError):
        await runtime.run_message(s, "hi", holder_id="h1")
    s.hold_lease("h1", 45)
    await runtime.run_message(s, "请查工具列表", holder_id="h1")
    events = runtime._events.replay(s.id)
    types = [e["type"] for e in events]
    assert "session_started" in types
    assert "text_delta" in types
    assert "tool_call" in types
    assert "turn_done" in types
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)  # 单调无重


@pytest.mark.asyncio
async def test_close_revokes_and_frees(runtime):
    """结束会话：撤销凭据、句柄关闭、事件封存、配额释放。"""
    s = await runtime.create("alice")
    await runtime.close(s)
    assert s.closed is True
    assert s.mcp_token in runtime._revoke_log
    assert s.handle is None or s.handle.closed is True
    closed_types = [e["type"] for e in runtime._events.replay(s.id)]
    assert "session_closed" in closed_types
    # 配额已释放：可再创建
    s2 = await runtime.create("alice")
    assert s2.id != s.id


@pytest.mark.asyncio
async def test_confirm_grant_mints_and_close_clears(runtime):
    """confirm_grant 铸票后 handle 可验票；close 清理会话全部票据。"""
    s = await runtime.create("alice")
    s.hold_lease("h1", 45)
    # 未确认前写票据缺失
    assert runtime._grants.check(s.id, "plan-9") is False
    expires_at = runtime.confirm_grant(s, "plan-9")
    assert expires_at > time.time()
    assert runtime._grants.check(s.id, "plan-9") is True
    # run_message 构造的 handle 携带 gate（共享同一 GrantStore）
    await runtime.run_message(s, "hi", holder_id="h1")
    assert s.handle is not None and s.handle.gate is not None
    # 会话结束清理票据
    await runtime.close(s)
    assert runtime._grants.check(s.id, "plan-9") is False


@pytest.mark.asyncio
async def test_sweep_skips_creating_session(runtime):
    """初始化中的会话不被空闲回收（design D2）。"""
    s = await runtime.create("alice")
    s.last_activity = time.time() - 2000
    closed = await runtime.sweep_idle(1800)
    assert closed == 0 and s.closed is False
    assert s.status == "creating"


@pytest.mark.asyncio
async def test_idle_sweep_closes_and_keeps_workspace(runtime):
    """空闲超阈值 → close（释放槽位、留产物）；执行中/近期活跃不回收。"""
    s = await runtime.create("alice")
    await runtime.initialize_session(s)  # ready 后才受空闲回收约束
    s.last_activity = time.time() - 2000
    closed = await runtime.sweep_idle(1800)
    assert closed == 1 and s.closed is True
    assert s.workspace.exists()  # close 不删除工作区
    closed_events = [
        e for e in runtime._events.replay(s.id) if e["type"] == "session_closed"
    ]
    assert closed_events and closed_events[-1]["payload"]["reason"] == "idle"
    # 槽位已释放，可再建
    again = await runtime.create("alice")
    await runtime.initialize_session(again)
    assert again.closed is False

    # 执行中的轮次不回收
    running = await runtime.create("alice")
    await runtime.initialize_session(running)
    running.last_activity = time.time() - 2000
    running.turn_running = True
    assert await runtime.sweep_idle(1800) == 0

    # 近期活跃不回收
    running.turn_running = False
    running.last_activity = time.time()
    assert await runtime.sweep_idle(1800) == 0


@pytest.mark.asyncio
async def test_gate_blocked_target_records_archive_task(runtime, monkeypatch):
    """即使计划结果落盘不可解析，gate_blocked 的 target 也能补记 task_id。"""
    session = await runtime.create("alice")
    session.hold_lease("h1", 45)

    async def blocked_run(self, prompt, **kwargs):
        yield WEvent(
            type="gate_blocked",
            payload={
                "tool_name": "edge_upsert_device",
                "target": "xlpa_task_recorded",
            },
        )
        yield WEvent(type="turn_done", payload={})

    monkeypatch.setattr(FakeHandle, "run_turn", blocked_run)
    await runtime.run_message(session, "hi", holder_id="h1")
    assert "xlpa_task_recorded" in session.archive_task_ids


@pytest.mark.asyncio
async def test_abort_turn_uses_interrupt_and_skips_turn_done(runtime, monkeypatch):
    """interrupt 优雅收尾：句柄 abort 被调用，轮次无 turn_done，发 turn_aborted。"""
    session = await runtime.create("alice")
    session.hold_lease("h1", 45)
    interrupted: list[str] = []

    async def fake_abort(self):
        interrupted.append("interrupt")
        self.stop.set()

    async def interruptible_run(self, prompt, **kwargs):
        yield WEvent(type="text_delta", payload={"text": "部分"})
        await self.stop.wait()
        raise TurnAborted("turn interrupted")

    monkeypatch.setattr(FakeHandle, "abort", fake_abort, raising=False)
    monkeypatch.setattr(FakeHandle, "run_turn", interruptible_run)
    task = asyncio.create_task(
        runtime.run_message(session, "hi", holder_id="h1")
    )
    session.run_task = task
    await asyncio.sleep(0.2)
    assert session.turn_running is True

    aborted, cancelled = await runtime.abort_turn(session)
    assert interrupted == ["interrupt"]
    assert aborted is True
    assert cancelled == []
    assert task.done() and not task.cancelled()
    assert session.turn_running is False
    events = runtime._events.replay(session.id)
    types = [e["type"] for e in events]
    assert "turn_aborted" in types
    assert "turn_done" not in types


@pytest.mark.asyncio
async def test_abort_turn_cancels_task_as_fallback(runtime, monkeypatch):
    """中止当前轮次：任务取消、turn_running 复位、发 turn_aborted 事件。"""
    session = await runtime.create("alice")
    session.hold_lease("h1", 45)

    async def slow_run_turn(self, prompt, **kwargs):
        await asyncio.sleep(10)
        yield  # pragma: no cover

    monkeypatch.setattr(FakeHandle, "run_turn", slow_run_turn)
    task = asyncio.create_task(
        runtime.run_message(session, "hi", holder_id="h1")
    )
    session.run_task = task
    await asyncio.sleep(0.2)
    assert session.turn_running is True

    aborted, cancelled = await runtime.abort_turn(session)
    assert aborted is True
    assert cancelled == []
    assert task.cancelled() or task.done()
    assert session.turn_running is False
    assert session.run_task is None
    events = runtime._events.replay(session.id)
    assert any(e["type"] == "turn_aborted" for e in events)


@pytest.mark.asyncio
async def test_wait_pending_text_until_extraction_finished(runtime):
    """轮次开始前等待 PDF 文本提取完成；完成后 pending 清空。"""
    session = await runtime.create("alice")
    runtime.begin_text_extraction(session, "协议.pdf")

    async def finish_later():
        await asyncio.sleep(0.3)
        runtime.finish_text_extraction(session.id, "协议.pdf")

    task = asyncio.create_task(finish_later())
    started = time.monotonic()
    await runtime.wait_pending_text(session, timeout=3)
    elapsed = time.monotonic() - started
    assert elapsed >= 0.25
    assert session.pending_text == set()
    await task


@pytest.mark.asyncio
async def test_wait_pending_text_times_out(runtime):
    """异常文件不会永久阻塞轮次：超时返回且保留 pending 供诊断。"""
    session = await runtime.create("alice")
    runtime.begin_text_extraction(session, "stuck.pdf")
    started = time.monotonic()
    await runtime.wait_pending_text(session, timeout=0.6)
    assert time.monotonic() - started >= 0.5
    assert "stuck.pdf" in session.pending_text


@pytest.mark.asyncio
async def test_turn_concurrency_guard(runtime):
    """并发轮次名额：超限拒绝，释放后可再次占用。"""
    runtime._max_concurrent_turns = 1
    runtime._active_turns = 0
    assert runtime.try_begin_turn() is True
    assert runtime.try_begin_turn() is False
    runtime.end_turn()
    assert runtime.try_begin_turn() is True
    runtime.end_turn()
    # <=0 表示不限制
    runtime._max_concurrent_turns = 0
    assert runtime.try_begin_turn() is True


def test_event_store_replay_after_seq(tmp_path):
    """事件存储：seq 单调 + 按 after_seq 重放。"""
    store = EventStore(tmp_path / "ev")
    for i in range(5):
        store.append("s1", "text_delta", {"i": i})
    replay = store.replay("s1", after_seq=2)
    assert [e["seq"] for e in replay] == [3, 4, 5]
    assert store.last_seq("s1") == 5


class _LargeResultHandle:
    """伪造句柄：产出一条超大工具结果（list_mcp_tools）。"""

    def __init__(self, config, pat_env=None, gate=None):
        self.config = config
        self.gate = gate

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
        return None

    async def run_turn(self, prompt, **kwargs):
        yield WEvent(
            type="tool_call",
            payload={"id": "tu-1", "name": "mcp__xlpa__list_mcp_tools", "input": {}},
        )
        yield WEvent(
            type="tool_result",
            payload={
                "tool_use_id": "tu-1",
                "content": "{" + "a" * 9000 + "}",
                "is_error": False,
            },
        )
        yield WEvent(type="turn_done", payload={})


@pytest.mark.asyncio
async def test_large_tool_result_not_auto_exported(tmp_path, monkeypatch):
    """工具结果不自动落盘为产物（只在显式写入或 MCP file_id 时产生文件）。"""

    async def fake_mint(self, username, session_id):
        return "tok-x"

    async def fake_revoke(self, token):
        return None

    monkeypatch.setattr(SessionRuntime, "_mint", fake_mint)
    monkeypatch.setattr(SessionRuntime, "_revoke", fake_revoke)
    monkeypatch.setattr("webchat.runtime.AgentHandle", _LargeResultHandle)
    rt = SessionRuntime(
        mint_url="http://127.0.0.1:8765",
        mint_secret="x",
        workspaces_dir=tmp_path / "ws",
        events=EventStore(tmp_path / "ev"),
        artifacts=ArtifactRegistry(),
    )
    s = await rt.create("alice")
    s.hold_lease("h", 45)
    await rt.run_message(s, "查询工具", holder_id="h")
    out = list((s.workspace / "xlpa-output").iterdir())
    assert out == []
    assert [
        e for e in rt._events.replay(s.id) if e["type"] == "artifact"
    ] == []
