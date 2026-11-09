"""SDK 适配层单元测试（用真实 SDK 消息类型构造，不启动真实 CLI）。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

import qodercn_agent_sdk as q

from tests.fake_sdk_client import install
from webchat.sdk_runtime import AgentHandle, AdapterConfig, TurnAborted, WEvent


def _config(tmp_path):
    return AdapterConfig(
        cwd=tmp_path,
        mcp_url="http://127.0.0.1:8765/mcp",
        mcp_token="test-token",
    )


def _assistant(uuid: str, blocks: list, session_id: str = "sid-1") -> q.AssistantMessage:
    return q.AssistantMessage(model="m", content=blocks, session_id=session_id, uuid=uuid)


def _result(subtype: str = "success", session_id: str = "sid-1") -> q.ResultMessage:
    return q.ResultMessage(
        subtype=subtype, session_id=session_id, is_error=subtype != "success",
        num_turns=1, duration_ms=1, duration_api_ms=1,
    )


@pytest.mark.asyncio
async def test_normalize_assistant_blocks(tmp_path, monkeypatch):
    """AssistantMessage → text_delta / tool_call；UserMessage → tool_result。"""
    fake_msgs = [
        _assistant(
            "m1",
            [
                {"type": "text", "text": "查询结果如下"},
                {"type": "tool_use", "id": "t1", "name": "list_mcp_tools", "input": {}},
            ],
        ),
        q.UserMessage(
            content=[{"tool_use_id": "t1", "content": [{"type": "text", "text": "total=71"}], "is_error": None}]
        ),
        _result(),
    ]
    install(monkeypatch, [fake_msgs])
    handle = AgentHandle(_config(tmp_path))
    events = [e async for e in handle.run_turn("查工具", elapsed_ms=0)]
    types = [e.type for e in events]
    assert "text_delta" in types
    assert "tool_call" in types
    assert "tool_result" in types
    assert "turn_done" in types
    assert handle.session_id == "sid-1"
    tool_result = next(e for e in events if e.type == "tool_result")
    assert tool_result.payload["tool_use_id"] == "t1"
    await handle.close()


@pytest.mark.asyncio
async def test_normalize_real_sdk_block_objects(tmp_path, monkeypatch):
    """真实 SDK 形态（ToolUseBlock/ToolResultBlock 为 dataclass）也必须归一化。"""
    fake_msgs = [
        _assistant(
            "m1",
            [
                q.TextBlock(text="查询结果如下"),
                q.ToolUseBlock(id="t1", name="list_mcp_tools", input={}),
            ],
        ),
        q.UserMessage(
            content=[
                q.ToolResultBlock(
                    tool_use_id="t1",
                    content=[{"type": "text", "text": "total=77"}],
                    is_error=False,
                )
            ]
        ),
        _result(),
    ]
    install(monkeypatch, [fake_msgs])
    handle = AgentHandle(_config(tmp_path))
    events = [e async for e in handle.run_turn("查工具", elapsed_ms=0)]
    types = [e.type for e in events]
    assert "text_delta" in types and "tool_call" in types
    assert "tool_result" in types
    result = next(e for e in events if e.type == "tool_result")
    assert result.payload["tool_use_id"] == "t1"
    assert result.payload["content"] == [{"type": "text", "text": "total=77"}]
    assert result.payload["is_error"] is False
    await handle.close()


@pytest.mark.asyncio
async def test_partial_dedup(tmp_path, monkeypatch):
    """partial 已覆盖的消息不再产出完整 text_delta（去重）。"""
    fake_msgs = [
        q.StreamEvent(
            uuid="m9", session_id="s",
            event={"type": "content_block_delta", "delta": {"text": "你"}},
        ),
        q.StreamEvent(
            uuid="m9", session_id="s",
            event={"type": "content_block_delta", "delta": {"text": "好"}},
        ),
        _assistant("m9", [{"type": "text", "text": "你好（完整）"}], session_id="s"),
        _result(session_id="s"),
    ]
    install(monkeypatch, [fake_msgs])
    handle = AgentHandle(_config(tmp_path))
    events = [e async for e in handle.run_turn("hi", elapsed_ms=0)]
    text_deltas = [e for e in events if e.type == "text_delta"]
    # 只有两段 partial，完整 TextBlock 被去重
    assert [e.payload["text"] for e in text_deltas] == ["你", "好"]
    await handle.close()


@pytest.mark.asyncio
async def test_partial_dedup_by_content_when_uuid_differs(tmp_path, monkeypatch):
    """uuid 不一致但内容与增量累积完全相同 → 仍只产出增量。"""
    fake_msgs = [
        q.StreamEvent(
            uuid="delta-u", session_id="s",
            event={"type": "content_block_delta", "delta": {"text": "A"}},
        ),
        _assistant("full-u", [{"type": "text", "text": "A"}], session_id="s"),
        _result(session_id="s"),
    ]
    install(monkeypatch, [fake_msgs])
    handle = AgentHandle(_config(tmp_path))
    events = [e async for e in handle.run_turn("hi", elapsed_ms=0)]
    assert [e.payload["text"] for e in events if e.type == "text_delta"] == ["A"]
    await handle.close()


@pytest.mark.asyncio
async def test_two_turns_reuse_one_client_and_receiver(tmp_path, monkeypatch):
    """单客户端 + 单接收循环跨两轮：session_id 不变，两轮均有 turn_done。"""
    turn1 = [
        q.StreamEvent(
            uuid="a", session_id="sid-1",
            event={"type": "content_block_delta", "delta": {"text": "A"}},
        ),
        _assistant("a", [{"type": "text", "text": "A"}]),
        _result(),
    ]
    turn2 = [
        q.StreamEvent(
            uuid="b", session_id="sid-1",
            event={"type": "content_block_delta", "delta": {"text": "B"}},
        ),
        _assistant("b", [{"type": "text", "text": "B"}]),
        _result(),
    ]
    clients = install(monkeypatch, [turn1, turn2])
    handle = AgentHandle(_config(tmp_path))
    first = [e async for e in handle.run_turn("只回复 A", elapsed_ms=0)]
    second = [e async for e in handle.run_turn("只回复 B", elapsed_ms=0)]
    assert len(clients) == 1
    assert clients[0].queries == ["只回复 A", "只回复 B"]
    assert clients[0].connected is True
    assert handle.session_id == "sid-1"
    assert sum(e.type == "turn_done" for e in first) == 1
    assert sum(e.type == "turn_done" for e in second) == 1
    assert [e.payload["text"] for e in first if e.type == "text_delta"] == ["A"]
    assert [e.payload["text"] for e in second if e.type == "text_delta"] == ["B"]
    await handle.close()
    assert clients[0].disconnected is True


@pytest.mark.asyncio
async def test_interrupt_raises_turn_aborted_and_can_continue(
    tmp_path, monkeypatch
):
    """中断映射为 TurnAborted；同一客户端继续下一轮，session_id 不变。"""
    turn1 = [
        q.StreamEvent(
            uuid="a", session_id="sid-1",
            event={"type": "content_block_delta", "delta": {"text": "开始"}},
        ),
    ]
    turn2 = [_assistant("b", [{"type": "text", "text": "继续"}]), _result()]
    clients = install(monkeypatch, [turn1, turn2])
    handle = AgentHandle(_config(tmp_path))

    async def consume() -> list[WEvent]:
        events: list[WEvent] = []
        with pytest.raises(TurnAborted):
            async for event in handle.run_turn("hi", elapsed_ms=0):
                events.append(event)
        return events

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    await handle.abort()
    events = await task
    assert [e.payload["text"] for e in events if e.type == "text_delta"] == ["开始"]
    assert clients[0].interrupted == 1
    assert handle.session_id == "sid-1"

    resumed = [e async for e in handle.run_turn("继续", elapsed_ms=0)]
    assert sum(e.type == "turn_done" for e in resumed) == 1
    assert clients[0].queries == ["hi", "继续"]
    await handle.close()


@pytest.mark.asyncio
async def test_elicitation_bridge(tmp_path, monkeypatch):
    """on_elicitation → elicit_handler 收到问题载荷，回答被回传。"""
    received: list[dict] = []

    async def handler(payload: dict) -> dict:
        received.append(payload)
        return {"action": "accept", "content": {"answer": "补充内容"}}

    clients = install(monkeypatch, [[_result(session_id="s")]])
    handle = AgentHandle(_config(tmp_path), elicit_handler=handler)
    async for _e in handle.run_turn("hi", elapsed_ms=0):
        pass
    callback = clients[0].options.on_elicitation
    result = await callback(
        SimpleNamespace(
            serverName="xlpa", message="请补充点表", mode="form", title="补充信息"
        )
    )
    assert received[0]["message"] == "请补充点表"
    assert result == {"action": "accept", "content": {"answer": "补充内容"}}
    await handle.close()


def test_sdk_types_not_leaked(tmp_path):
    """契约模块不含 SDK 类型名。"""
    import webchat.sdk_runtime.events as events_mod

    source = events_mod.__file__
    text = Path(source).read_text(encoding="utf-8")
    for banned in ("qodercn_agent_sdk", "AssistantMessage", "StreamEvent"):
        assert banned not in text


def test_system_prompt_routes_no_param_write_to_chat_confirm():
    """系统提示含“无参写被拦→会话播报摘要并请求 /确认、不得自授权、
    不得用口令索要凭据”的路由段，且保留敏感凭据走卡片。”"""
    from webchat.sdk_runtime.adapter import WEBCHAT_SYSTEM_APPEND

    text = WEBCHAT_SYSTEM_APPEND
    assert "/确认" in text
    assert "摘要" in text
    assert "不得自行" in text or "不要自行" in text or "禁止自行" in text
