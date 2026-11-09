"""会话运行时测试（fake mint/revoke 与 fake agent 句柄）。"""

from __future__ import annotations

import asyncio
import time

import pytest

from webchat.artifacts import ArtifactRegistry
from webchat.event_store import EventStore
from webchat.runtime import (
    QuotaExceeded,
    SessionRuntime,
    WebSession,
)
from webchat.sdk_runtime import TurnAborted, WEvent


class FakeHandle:
    """伪造 agent 句柄：产出两段固定事件后结束。"""

    def __init__(self, config, pat_env=None, gate=None):
        self.config = config
        self.gate = gate
        self.closed = False
        self.stop = asyncio.Event()

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
async def test_idle_sweep_closes_and_keeps_workspace(runtime):
    """空闲超阈值 → close（释放槽位、留产物）；执行中/近期活跃不回收。"""
    s = await runtime.create("alice")
    s.last_activity = time.time() - 2000
    closed = await runtime.sweep_idle(1800)
    assert closed == 1 and s.closed is True
    assert s.workspace.exists()  # close 不删除工作区
    closed_events = [
        e for e in runtime._events.replay(s.id) if e["type"] == "session_closed"
    ]
    assert closed_events and closed_events[-1]["payload"]["reason"] == "idle"
    # 槽位已释放，可再建
    assert (await runtime.create("alice")).closed is False

    # 执行中的轮次不回收
    running = await runtime.create("alice")
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
