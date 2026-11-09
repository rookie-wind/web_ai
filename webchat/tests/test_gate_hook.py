"""adapter PreToolUse 门禁 Hook 单测（fake SDK 捕获 options，不启动 CLI）。"""

from __future__ import annotations

import pytest

from webchat.grants import GrantStore, WriteGate
from webchat.sdk_runtime import AdapterConfig, AgentHandle


def _config(tmp_path) -> AdapterConfig:
    return AdapterConfig(
        cwd=tmp_path,
        mcp_url="http://127.0.0.1:8765/mcp",
        mcp_token="test-token",
    )


@pytest.fixture
def capture():
    """捕获 _build_options 的结果供断言（不启动客户端）。"""
    return {}


def _make_gate(
    events: list, audits: list, ttl: int = 300, workspace=None,
    read_roots=None,
) -> WriteGate:
    store = GrantStore(ttl_seconds=ttl)
    gate = WriteGate(
        "sess-1",
        store,
        event_writer=lambda t, p: events.append((t, p)),
        audit_writer=lambda e: audits.append(e),
        workspace_dir=workspace,
        read_roots=read_roots,
    )
    gate._store = store
    return gate


async def _run_and_grab_hook(handle: AgentHandle, captured: dict):
    """构造 options（不连客户端），返回注册进 options 的 Hook 回调。"""
    captured["options"] = handle._build_options()
    hooks = captured["options"].hooks
    return hooks


@pytest.mark.asyncio
async def test_hooks_registered_when_gate_present(tmp_path, capture):
    """注入 gate → options.hooks 挂接 PreToolUse（matcher=None 匹配全部）。"""
    gate = _make_gate([], [])
    handle = AgentHandle(_config(tmp_path), gate=gate)
    hooks = await _run_and_grab_hook(handle, capture)
    assert hooks is not None and "PreToolUse" in hooks
    matchers = hooks["PreToolUse"]
    assert len(matchers) == 1
    assert matchers[0].matcher is None
    assert matchers[0].hooks == [handle._pre_tool_use]


@pytest.mark.asyncio
async def test_hooks_absent_when_no_gate(tmp_path, capture):
    """未注入 gate → 不挂接 hooks（IDE 等无门禁场景行为不变）。"""
    handle = AgentHandle(_config(tmp_path))
    hooks = await _run_and_grab_hook(handle, capture)
    assert hooks is None


@pytest.mark.asyncio
async def test_hook_denies_write_without_grant(tmp_path, capture):
    """无 grant 调写入工具 → permissionDecision=deny。"""
    events: list = []
    gate = _make_gate(events, [])
    handle = AgentHandle(_config(tmp_path), gate=gate)
    await _run_and_grab_hook(handle, capture)
    out = await handle._pre_tool_use(
        {"tool_name": "mcp__xlpa__add_brand", "tool_input": {"brand": "X"}},
        "tu-1", {},
    )
    specific = out["hookSpecificOutput"]
    assert specific["permissionDecision"] == "deny"
    assert events and events[0][0] == "gate_blocked"


@pytest.mark.asyncio
async def test_hook_allows_write_with_grant(tmp_path, capture):
    """有效 grant → permissionDecision=allow。"""
    gate = _make_gate([], [])
    gate._store.mint("sess-1", "add_brand")
    handle = AgentHandle(_config(tmp_path), gate=gate)
    await _run_and_grab_hook(handle, capture)
    out = await handle._pre_tool_use(
        {"tool_name": "mcp__xlpa__add_brand", "tool_input": {}}, "tu-1", {},
    )
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"


@pytest.mark.asyncio
async def test_hook_denies_login_and_unknown_allows_read(tmp_path, capture):
    """登录绝对禁止 deny、edge_get_token 无票需确认 deny、未知 deny、只读/Skill allow。"""
    events: list = []
    gate = _make_gate(events, [])
    handle = AgentHandle(_config(tmp_path), gate=gate)
    await _run_and_grab_hook(handle, capture)

    async def decision(tool_name: str, tool_input: dict | None = None) -> str:
        out = await handle._pre_tool_use(
            {"tool_name": tool_name, "tool_input": tool_input or {}},
            "tu", {},
        )
        return out["hookSpecificOutput"]["permissionDecision"]

    assert await decision("mcp__xlpa__login") == "deny"
    assert await decision("mcp__xlpa__edge_get_token") == "deny"
    assert await decision("Bash") == "deny"
    assert await decision("mcp__xlpa__get_classify_list") == "allow"
    assert await decision("Skill", {"name": "xlpa"}) == "allow"
    # login 绝对禁止不可确认解除；edge_get_token 需确认、可解除
    blocked = {
        p["tool_name"]: p["confirmable"]
        for t, p in events if t == "gate_blocked"
    }
    assert blocked["login"] is False
    assert blocked["edge_get_token"] is True


@pytest.mark.asyncio
async def test_builtin_tool_surface_includes_read(tmp_path, capture):
    """SDK 工具面：Write/Edit/Read + WebSearch；Skill/命令工具不暴露。"""
    gate = _make_gate([], [], workspace=tmp_path, read_roots=[tmp_path])
    handle = AgentHandle(_config(tmp_path), gate=gate)
    await _run_and_grab_hook(handle, capture)
    options = capture["options"]
    assert options.tools == ["Write", "Edit", "Read", "WebSearch"]
    assert options.allowed_tools == ["Write", "Edit", "Read"]
    assert options.skills is None
    # 非交互会话无权限弹窗通道：文件编辑必须免交互确认
    assert options.permission_mode == "acceptEdits"
    assert "Bash" in options.disallowed_tools
    # Web 交互约定：凭据走参数卡片，不在聊天索要；无参写经会话口令 /确认
    append = options.system_prompt["append"]
    assert "参数卡片" in append
    assert "不要在聊天中索要" in append
    assert "/确认" in append
    # 路由与数据边界约定
    assert "只用 xlpa MCP 工具" in append
    assert "内置 WebSearch" in append
    assert "/web" in append and "/xlpa" in append
    # 技能不再走 Skill 工具；PDF 必须读自动抽取的 .pdf.md
    assert "不要调用 Skill 工具" in append
    assert ".pdf.md" in append
    # Web 会话平台登录由服务端预激活，模型不得调用 login/索要验证码
    assert "已由服务端用内置账号完成 login 授权激活" in append
    assert "不要调用 login" in append
    assert "不要向用户索要手机号" in append
    assert "access_level=user 仅表示 MCP 接入级别" in append


@pytest.mark.asyncio
async def test_permission_callback_answers_without_prompt(tmp_path, capture):
    """权限请求回调直接答复：产物目录写入/工作区读取 allow，越界/命令工具 deny。"""
    gate = _make_gate(
        [], [], workspace=tmp_path, read_roots=[tmp_path]
    )
    handle = AgentHandle(_config(tmp_path), gate=gate)

    allow = await handle._can_use_tool(
        "Write", {"file_path": "xlpa-output/a.md"}, {}
    )
    assert allow.behavior == "allow"
    deny = await handle._can_use_tool(
        "Write", {"file_path": "../a.md"}, {}
    )
    assert deny.behavior == "deny" and "越界" in deny.message
    read_allow = await handle._can_use_tool(
        "Read", {"file_path": "xlpa-output/a.md"}, {}
    )
    assert read_allow.behavior == "allow"
    read_deny = await handle._can_use_tool(
        "Read", {"file_path": "../a.md"}, {}
    )
    assert read_deny.behavior == "deny" and "越界" in read_deny.message
    assert (
        await handle._can_use_tool("mcp__xlpa__get_classify_list", {}, {})
    ).behavior == "allow"
    assert (await handle._can_use_tool("WebSearch", {}, {})).behavior == "allow"
    assert (await handle._can_use_tool("WebFetch", {}, {})).behavior == "deny"
    assert (await handle._can_use_tool("Bash", {}, {})).behavior == "deny"


@pytest.mark.asyncio
async def test_hook_confines_builtin_write_to_output(tmp_path, capture):
    """注入工作区后：Write 落 xlpa-output 放行，目录外/命令工具仍 deny。"""
    events: list = []
    gate = _make_gate(events, [], workspace=tmp_path)
    handle = AgentHandle(_config(tmp_path), gate=gate)
    await _run_and_grab_hook(handle, capture)

    async def decision(tool_name: str, tool_input: dict) -> str:
        out = await handle._pre_tool_use(
            {"tool_name": tool_name, "tool_input": tool_input}, "tu", {},
        )
        return out["hookSpecificOutput"]["permissionDecision"]

    assert await decision(
        "Write", {"file_path": "xlpa-output/report.md"}
    ) == "allow"
    assert await decision(
        "Write", {"file_path": "../escape.md"}
    ) == "deny"
    assert await decision("Bash", {}) == "deny"
    denied = [p for t, p in events if t == "gate_blocked"]
    assert all(p["confirmable"] is False for p in denied)


@pytest.mark.asyncio
async def test_hook_allows_provision_with_grant(tmp_path, capture):
    """edge_get_token 经确认铸票（目标=工具名）→ permissionDecision=allow。"""
    gate = _make_gate([], [])
    gate._store.mint("sess-1", "edge_get_token")
    handle = AgentHandle(_config(tmp_path), gate=gate)
    await _run_and_grab_hook(handle, capture)
    out = await handle._pre_tool_use(
        {
            "tool_name": "mcp__xlpa__edge_get_token",
            "tool_input": {"ip": "10.0.17.23"},
        },
        "tu-1", {},
    )
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"


@pytest.mark.asyncio
async def test_hook_fail_closed_when_gate_raises(tmp_path, capture, monkeypatch):
    """gate.decide 抛异常 → Fail-Closed deny（不泄露异常给模型）。"""
    gate = _make_gate([], [])
    handle = AgentHandle(_config(tmp_path), gate=gate)
    await _run_and_grab_hook(handle, capture)

    def boom(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(gate, "decide", boom)
    # _pre_tool_use 直接调 gate.decide；WriteGate.decide 本身已兜底，
    # 此处验证即便 decide 被替换为抛异常，回调仍安全返回 deny 结构。
    out = await handle._pre_tool_use(
        {"tool_name": "mcp__xlpa__add_brand", "tool_input": {}}, "tu", {},
    )
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
