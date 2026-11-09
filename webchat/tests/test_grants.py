"""写入门禁单测：GrantStore 窗口语义、WriteGate 验票全分支、防漂移比对。"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from webchat import grants as grants_mod
from webchat.grants import (
    CLOUD_WRITE_TOOL_NAMES,
    EDGE_WRITE_TOOL_NAMES,
    LOGIN_TOOL_NAMES,
    PROVISION_TOOL_NAMES,
    WRITE_TOOL_NAMES,
    GrantStore,
    WriteGate,
    bare_tool_name,
    build_param_schema,
    classify_tool,
    resolve_target,
)

SERVER_PY = Path(__file__).resolve().parents[2] / "mcp_server" / "server.py"


# ── 辅助 ──

def _collect(events: list, audits: list, workspace=None) -> WriteGate:
    """构造带事件/审计回调观察点的 WriteGate（共享 GrantStore）。"""
    store = GrantStore(ttl_seconds=300)
    gate = WriteGate(
        "sess-1",
        store,
        event_writer=lambda t, p: events.append((t, p)),
        audit_writer=lambda e: audits.append(e),
        workspace_dir=workspace,
    )
    gate._store = store  # 测试观察/铸票用
    return gate


def _mcp(name: str) -> str:
    return f"mcp__xlpa__{name}"


# ── 内置 Read 白名单 ──

def test_read_only_within_workspace_and_skills_root(tmp_path):
    """Read 仅允许会话工作区与 canonical 技能目录；越界/缺参一律拒绝。"""
    workspace = tmp_path / "ws"
    (workspace / "xlpa-input").mkdir(parents=True)
    skills = tmp_path / "skills"
    (skills / "xlpa").mkdir(parents=True)
    (skills / "xlpa" / "SKILL.md").write_text("doc", encoding="utf-8")

    gate = WriteGate(
        "s1",
        GrantStore(),
        workspace_dir=workspace,
        read_roots=[workspace, skills],
    )
    assert gate.check_read(
        {"file_path": str(workspace / "xlpa-input" / "a.txt")}
    )[0] is True
    # 相对路径按会话工作区解析（与 CLI cwd 一致）
    assert gate.check_read({"file_path": "xlpa-input/a.txt"})[0] is True
    assert gate.check_read(
        {"file_path": str(skills / "xlpa" / "SKILL.md")}
    )[0] is True
    # 仓库内其他文件/目录穿越一律拒绝
    assert gate.check_read({"file_path": str(tmp_path / "permissions.json")})[0] is False
    assert gate.check_read({"file_path": "../secret.txt"})[0] is False
    assert gate.check_read({})[0] is False


def _gate_for_pdf_read(workspace, events):
    """构造只读会话工作区的门禁（附 gate_blocked 事件采集）。"""
    return WriteGate(
        "s1",
        GrantStore(),
        event_writer=lambda t, p: events.append((t, p)),
        workspace_dir=workspace,
        read_roots=[workspace],
    )


def test_read_pdf_denied_and_redirected_to_markdown_sidecar(tmp_path):
    """工作区内 PDF 拒读，优先提示同名 .pdf.md（guard=pdf_binary）。"""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    pdf = workspace / "协议.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    (workspace / "协议.pdf.md").write_text("md", encoding="utf-8")
    (workspace / "协议.pdf.txt").write_text("old", encoding="utf-8")
    events: list = []
    gate = _gate_for_pdf_read(workspace, events)
    ok, reason = gate.check_read({"file_path": str(pdf)})
    assert ok is False
    assert "PDF 是二进制文件" in reason and "协议.pdf.md" in reason
    assert "尚未完成" not in reason
    allow, _ = gate.decide("Read", {"file_path": str(pdf)})
    assert allow is False
    blocked = [p for t, p in events if t == "gate_blocked"]
    assert blocked and blocked[0]["guard"] == "pdf_binary"
    # 旁路 Markdown 可正常读取
    assert gate.check_read(
        {"file_path": str(workspace / "协议.pdf.md")}
    )[0] is True


def test_read_pdf_falls_back_to_legacy_txt_sidecar(tmp_path):
    """历史会话只有 .pdf.txt 时，重定向指向旧旁路而不是不存在的新名。"""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    pdf = workspace / "协议.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    sidecar = workspace / "协议.pdf.txt"
    sidecar.write_text("text", encoding="utf-8")
    events: list = []
    gate = _gate_for_pdf_read(workspace, events)
    ok, reason = gate.check_read({"file_path": str(pdf)})
    assert ok is False
    assert "协议.pdf.txt" in reason and "协议.pdf.md" not in reason
    assert gate.check_read({"file_path": str(sidecar)})[0] is True


def test_read_pdf_hints_pending_when_no_sidecar(tmp_path):
    """两个旁路都不存在：提示 .pdf.md 并说明可能未完成/已失败。"""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    pdf = workspace / "协议.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    events: list = []
    gate = _gate_for_pdf_read(workspace, events)
    ok, reason = gate.check_read({"file_path": str(pdf)})
    assert ok is False
    assert "协议.pdf.md" in reason and "尚未完成或已失败" in reason


def test_read_denied_without_roots_and_emits_guard_event(tmp_path):
    """未注入根目录时 Read Fail-Closed；decide 拒绝标记 guard=read_path。"""
    events: list = []
    gate = WriteGate(
        "s1", GrantStore(), event_writer=lambda t, p: events.append((t, p))
    )
    assert gate.check_read({"file_path": str(tmp_path / "a.txt")})[0] is False
    allow, _reason = gate.decide("Read", {"file_path": str(tmp_path / "a.txt")})
    assert allow is False
    blocked = [p for t, p in events if t == "gate_blocked"]
    assert blocked and blocked[0]["guard"] == "read_path"
    assert blocked[0]["confirmable"] is False


# ── GrantStore 窗口语义 ──

def test_mint_then_check_within_window():
    """铸造后窗口内 check 通过。"""
    store = GrantStore(ttl_seconds=300)
    store.mint("s1", "plan-9")
    assert store.check("s1", "plan-9") is True


def test_check_reusable_within_window():
    """窗口语义：同目标多次 check 均通过（不销毁）。"""
    store = GrantStore(ttl_seconds=300)
    store.mint("s1", "task-1")
    assert [store.check("s1", "task-1") for _ in range(5)] == [True] * 5


def test_check_unknown_or_other_session_denied():
    """未铸票目标 / 他会话票据不放行。"""
    store = GrantStore(ttl_seconds=300)
    store.mint("s1", "plan-9")
    assert store.check("s1", "plan-10") is False
    assert store.check("s2", "plan-9") is False


def test_check_expired_denied(monkeypatch):
    """窗口过期后 check 失败并惰性清理。"""
    clock = {"t": 1000.0}
    monkeypatch.setattr(grants_mod.time, "time", lambda: clock["t"])
    store = GrantStore(ttl_seconds=300)
    store.mint("s1", "plan-9")
    clock["t"] = 1301.0  # 越过 300s 窗口
    assert store.check("s1", "plan-9") is False
    assert ("s1", "plan-9") not in store._grants


def test_execution_failure_does_not_refund_or_extend(monkeypatch):
    """无二次放行则不延长：单次消费后停手，到期照常失效。"""
    clock = {"t": 1000.0}
    monkeypatch.setattr(grants_mod.time, "time", lambda: clock["t"])
    store = GrantStore(ttl_seconds=300)
    store.mint("s1", "plan-9")
    assert store.check("s1", "plan-9") is True  # 第一次放行（滑动至 1300，同一时刻不变）
    # 之后无新放行（模拟工具失败后不再重试）——窗口不延长，到期失效
    clock["t"] = 1301.0
    assert store.check("s1", "plan-9") is False


def test_check_slides_window_on_each_allow(monkeypatch):
    """滑动消费：窗口内每次放行都把到期时间顺延 TTL，持续写入不过期。"""
    clock = {"t": 1000.0}
    monkeypatch.setattr(grants_mod.time, "time", lambda: clock["t"])
    store = GrantStore(ttl_seconds=300)
    store.mint("s1", "plan-9")        # expires 1300
    clock["t"] = 1200.0
    assert store.check("s1", "plan-9") is True  # 放行→顺延至 1500
    clock["t"] = 1400.0               # 越过原始 1300，但在滑动后的 1500 内
    assert store.check("s1", "plan-9") is True  # 再放行→顺延至 1700
    clock["t"] = 1701.0               # 停手超过一个 TTL
    assert store.check("s1", "plan-9") is False


def test_clear_session(monkeypatch):
    """会话清理移除该会话全部票据，不影响他会话。"""
    store = GrantStore(ttl_seconds=300)
    store.mint("s1", "a")
    store.mint("s1", "b")
    store.mint("s2", "a")
    store.clear_session("s1")
    assert store.check("s1", "a") is False
    assert store.check("s1", "b") is False
    assert store.check("s2", "a") is True


def test_mint_empty_raises():
    """空 session_id / target 拒绝铸造。"""
    store = GrantStore()
    with pytest.raises(ValueError):
        store.mint("", "plan-9")
    with pytest.raises(ValueError):
        store.mint("s1", "")


# ── WriteGate 验票全分支 ──

def test_write_without_grant_denied_and_emits_event():
    """无 grant 调云端写工具 → deny + gate_blocked 事件 + 审计。"""
    events: list = []
    audits: list = []
    gate = _collect(events, audits)
    allow, reason = gate.decide(_mcp("add_brand"), {"brand": "X"})
    assert allow is False
    assert events and events[0][0] == "gate_blocked"
    assert events[0][1]["tool_name"] == "add_brand"
    assert audits[-1]["decision"] == "deny"


def test_write_with_grant_allowed_and_audited():
    """有效 grant → allow + 审计 allow，无 gate_blocked。"""
    events: list = []
    audits: list = []
    gate = _collect(events, audits)
    gate._store.mint("sess-1", "add_brand")
    allow, _ = gate.decide(_mcp("add_brand"), {"brand": "X"})
    assert allow is True
    assert events == []
    assert audits[-1]["decision"] == "allow"


def test_write_grant_reused_across_calls():
    """窗口内同目标多次写入均放行（修确认风暴）。"""
    gate = _collect([], [])
    gate._store.mint("sess-1", "add_brand")
    results = [gate.decide(_mcp("add_brand"), {})[0] for _ in range(4)]
    assert results == [True] * 4


def test_edge_write_uses_plan_id_as_target():
    """边缘写按 plan_id 验票：铸 plan_id 票据即放行整条序列。"""
    gate = _collect([], [])
    gate._store.mint("sess-1", "plan-77")
    for tool in ("edge_upsert_device", "edge_mount_device",
                 "edge_save_device_parameters"):
        allow, _ = gate.decide(_mcp(tool), {"plan_id": "plan-77"})
        assert allow is True, tool


def test_build_param_schema_edge_get_token():
    """edge_get_token 返回全部登记参数；敏感项不回显 prefilled。"""
    fields = build_param_schema("edge_get_token", {"ip": "20.2.96.2"})
    by_name = {f["name"]: f for f in fields}
    assert set(by_name) >= {"ip", "username", "password", "phone", "captcha"}
    assert by_name["ip"]["required"] is True
    assert by_name["ip"]["prefilled"] == "20.2.96.2"
    assert by_name["username"]["prefilled"] == ""
    assert by_name["password"]["sensitive"] is True
    assert by_name["captcha"]["sensitive"] is True
    assert by_name["phone"]["required"] is False


def test_build_param_schema_unregistered_empty():
    """未登记工具返回空表单（前端回落通用确认卡）。"""
    assert build_param_schema("add_brand", {"brand": "X"}) == []


def test_provision_deny_carries_param_schema():
    """edge_get_token 无票 deny → gate_blocked 事件带 param_schema。"""
    events: list = []
    gate = _collect(events, [])
    allow, _ = gate.decide(_mcp("edge_get_token"), {"ip": "20.2.96.2"})
    assert allow is False
    assert events[0][0] == "gate_blocked"
    schema = events[0][1]["param_schema"]
    assert {f["name"] for f in schema} >= {"ip", "username", "password"}


def test_execute_archive_task_uses_task_id_as_target():
    """execute_archive_task 按 task_id 验票（batch/cursor 续跑复用）。"""
    gate = _collect([], [])
    gate._store.mint("sess-1", "task-5")
    allow, _ = gate.decide(
        _mcp("execute_archive_task"), {"task_id": "task-5", "stages": "all"}
    )
    assert allow is True
    # 续跑第二次仍放行（同 task_id 窗口）
    assert gate.decide(
        _mcp("execute_archive_task"), {"task_id": "task-5", "cursor": "c1"}
    )[0] is True


def test_login_tool_denied_absolute():
    """云平台业务登录 login 绝对禁止：deny 且 confirmable=False。"""
    events: list = []
    gate = _collect(events, [])
    allow, _ = gate.decide(_mcp("login"), {})
    assert allow is False
    assert events[0][0] == "gate_blocked"
    assert events[0][1]["confirmable"] is False


def test_provision_tool_denied_without_grant():
    """edge_get_token 无 grant → deny 且 confirmable=True（可经确认解除）。"""
    events: list = []
    gate = _collect(events, [])
    allow, _ = gate.decide(_mcp("edge_get_token"), {"ip": "10.0.17.23"})
    assert allow is False
    assert events[0][0] == "gate_blocked"
    assert events[0][1]["confirmable"] is True
    assert events[0][1]["tool_name"] == "edge_get_token"


def test_provision_with_grant_allowed():
    """edge_get_token 经确认铸票（目标=工具名）后窗口内放行。"""
    gate = _collect([], [])
    gate._store.mint("sess-1", "edge_get_token")
    allow, _ = gate.decide(_mcp("edge_get_token"), {"ip": "10.0.17.23"})
    assert allow is True
    # 同窗口内再次调用仍放行（不退票）
    assert gate.decide(_mcp("edge_get_token"), {"ip": "10.0.17.23"})[0] is True


def test_provision_grant_expired_requires_reconfirm(monkeypatch):
    """edge_get_token 窗口过期后同目标再次调用需重新确认（deny）。"""
    clock = {"t": 1000.0}
    monkeypatch.setattr(grants_mod.time, "time", lambda: clock["t"])
    events: list = []
    gate = _collect(events, [])
    gate._store.mint("sess-1", "edge_get_token")
    assert gate.decide(_mcp("edge_get_token"), {"ip": "10.0.17.23"})[0] is True
    clock["t"] = 1301.0  # 越过 300s 窗口
    assert gate.decide(_mcp("edge_get_token"), {"ip": "10.0.17.23"})[0] is False
    assert events[-1][0] == "gate_blocked"
    assert events[-1][1]["confirmable"] is True


def test_read_and_plan_tools_allowed_without_grant():
    """只读/探测/规划工具无需 grant 放行。"""
    gate = _collect([], [])
    for tool in ("get_classify_list", "list_mcp_tools",
                 "plan_device_archive", "convert_comm_address_tool"):
        assert gate.decide(_mcp(tool), {})[0] is True, tool


def test_skill_tool_allowed():
    """Skill 调用放行（非 MCP 工具面但属已知）。"""
    gate = _collect([], [])
    assert gate.decide("Skill", {"name": "xlpa"})[0] is True


def test_command_and_unknown_builtin_tool_denied():
    """命令类/未知内置工具仍防御性 deny；未注入工作区时内置写入也 deny。"""
    events: list = []
    gate = _collect(events, [])
    for tool in ("Bash", "Glob", "Grep", "WebFetch"):
        assert gate.decide(tool, {})[0] is False, tool
    # 未注入工作区：内置写入保持关闭（Fail-Closed）
    assert gate.decide(
        "Write", {"file_path": "xlpa-output/a.md"}
    )[0] is False
    assert gate.decide("Edit", {})[0] is False
    assert all(e[0] == "gate_blocked" for e in events)


def test_builtin_write_confined_to_output_dir(tmp_path):
    """内置写入仅在 xlpa-output/ 内且文本扩展名放行；越界/非法扩展名拒绝。"""
    events: list = []
    audits: list = []
    gate = _collect(events, audits, workspace=tmp_path)
    # 相对/绝对路径均以会话工作区解析
    assert gate.decide(
        "Write", {"file_path": "xlpa-output/report.md"}
    )[0] is True
    assert gate.decide(
        "Edit", {"file_path": str(tmp_path / "xlpa-output" / "cfg.json")}
    )[0] is True
    # 越界：目录逃逸、工作区外绝对路径、同级其他目录
    for bad in (
        "xlpa-output/../secret.md",
        str(tmp_path / "secret.md"),
        "xlpa-input/a.md",
    ):
        assert gate.decide("Write", {"file_path": bad})[0] is False, bad
    # 非文本扩展名 / 缺参
    assert gate.decide(
        "Write", {"file_path": "xlpa-output/a.docx"}
    )[0] is False
    assert gate.decide("Write", {})[0] is False
    # 拒绝均不可经确认解除，且带路径护栏标识（供前端弱化展示）
    denied = [p for t, p in events if t == "gate_blocked"]
    assert denied and all(p["confirmable"] is False for p in denied)
    assert all(p["guard"] == "builtin_write_path" for p in denied)
    assert any(a["decision"] == "allow" for a in audits)


def test_web_search_allowed_and_web_fetch_denied():
    """内置检索：WebSearch 放行并记审计；WebFetch 保持 deny。"""
    events: list = []
    audits: list = []
    gate = _collect(events, audits)
    assert gate.decide("WebSearch", {"query": "Modbus TCP 默认端口"})[0] is True
    assert any(
        a["decision"] == "allow" and a["tool_name"] == "WebSearch"
        for a in audits
    )
    assert gate.decide("WebFetch", {"url": "http://example.com"})[0] is False
    denied = [p for t, p in events if t == "gate_blocked"]
    assert denied and denied[-1]["tool_name"] == "WebFetch"


def test_builtin_write_does_not_require_grant(tmp_path):
    """产物目录内写入不依赖计划域票据（不属于平台写入门禁）。"""
    gate = _collect([], [], workspace=tmp_path)
    assert gate._store.check("sess-1", "Write") is False
    assert gate.decide(
        "Write", {"file_path": "xlpa-output/a.md"}
    )[0] is True


def test_fail_closed_on_internal_error(monkeypatch):
    """验票内部异常 → Fail-Closed deny。"""
    gate = _collect([], [])

    def boom(*_a, **_k):
        raise RuntimeError("store down")

    monkeypatch.setattr(gate._store, "check", boom)
    allow, reason = gate.decide(_mcp("add_brand"), {})
    assert allow is False
    assert "gate error" in reason


# ── 纯函数辅助 ──

def test_bare_tool_name_strips_prefix():
    assert bare_tool_name("mcp__xlpa__add_brand") == "add_brand"
    assert bare_tool_name("mcp__other__add_brand", "other") == "add_brand"
    assert bare_tool_name("Skill") == "Skill"


def test_resolve_target_priority():
    assert resolve_target("execute_archive_task", {"task_id": "t1"}) == "t1"
    assert resolve_target("edge_upsert_device", {"plan_id": "p1"}) == "p1"
    assert resolve_target("add_brand", {"brand": "X"}) == "add_brand"


def test_classify_tool():
    assert classify_tool("login") == "login"
    assert classify_tool("edge_get_token") == "provision"
    assert classify_tool("add_brand") == "write"
    assert classify_tool("edge_upsert_device") == "write"
    assert classify_tool("get_classify_list") == "read"


def _scoped_gate(scope, events, audits):
    """构造挂接活动 task 作用域的 WriteGate（共享 GrantStore）。"""
    store = GrantStore(ttl_seconds=300)
    gate = WriteGate(
        "sess-1",
        store,
        task_scope=scope,
        event_writer=lambda t, p: events.append((t, p)),
        audit_writer=lambda e: audits.append(e),
    )
    gate._store = store
    return gate


# ── 活动 task 作用域（task 级确认归并）──

def test_task_scope_merges_no_task_writes():
    """会话持活动 task 作用域时，不带 task_id 的写归并到该作用域目标。"""
    task_scope = grants_mod.TaskScope(ttl_seconds=300)
    task_scope.note("sess-1", "xlpa_task_9")
    events: list = []
    audits: list = []
    gate = _scoped_gate(task_scope, events, audits)
    allow, _ = gate.decide(_mcp("edge_upsert_device"), {"device_name": "D1"})
    assert allow is False
    # 目标归并到活动作用域（当前应回退成 tool_name 而此处不一致 → 红）
    assert events[-1][1]["target"] == "xlpa_task_9"
    # 一次确认（对该作用域铸票）后，另一无 task 写工具在窗口内放行
    gate._store.mint("sess-1", "xlpa_task_9")
    assert gate.decide(_mcp("edge_save_device_parameters"), {})[0] is True


def test_no_scope_falls_back_to_tool_name_granularity():
    """无活动作用域时写回退 tool_name 粒度：一次确认不覆盖另一写工具。"""
    task_scope = grants_mod.TaskScope(ttl_seconds=300)  # 未 note
    events: list = []
    gate = _scoped_gate(task_scope, events, [])
    assert gate.decide(_mcp("edge_upsert_device"), {"device_name": "D"})[0] is False
    assert events[-1][1]["target"] == "edge_upsert_device"
    gate._store.mint("sess-1", "edge_upsert_device")
    # 同工具续跑放行
    assert gate.decide(_mcp("edge_upsert_device"), {"device_name": "D2"})[0] is True
    # 另一写工具未被覆盖，仍需确认
    assert gate.decide(_mcp("edge_save_device_parameters"), {})[0] is False


def test_scope_batch_one_confirm_covers_all_writes(monkeypatch):
    """带同一 task_id：一次确认覆盖该任务下不同写工具（含无 task 的续跑写）。"""
    clock = {"t": 1000.0}
    monkeypatch.setattr(grants_mod.time, "time", lambda: clock["t"])
    task_scope = grants_mod.TaskScope(ttl_seconds=300)
    events: list = []
    gate = _scoped_gate(task_scope, events, [])
    assert gate.decide(
        _mcp("edge_upsert_device"), {"task_id": "xlpa_task_7"}
    )[0] is False
    assert events[-1][1]["target"] == "xlpa_task_7"
    gate._store.mint("sess-1", "xlpa_task_7")
    # 无 task 的后续写归并到同一作用域，一次确认全覆盖
    assert gate.decide(_mcp("edge_save_device_parameters"), {})[0] is True
    assert gate.decide(_mcp("edge_mount_device"), {})[0] is True
    # 停止超过 TTL → 作用域回收，需重新确认
    clock["t"] = 1301.0
    assert gate.decide(_mcp("edge_set_device_param"), {})[0] is False


def test_new_task_id_overrides_active_scope():
    """新 task_id 覆盖旧作用域，无 task 写归并到最新作用域。"""
    task_scope = grants_mod.TaskScope(ttl_seconds=300)
    task_scope.note("sess-1", "xlpa_task_1")
    events: list = []
    gate = _scoped_gate(task_scope, events, [])
    gate.decide(_mcp("edge_upsert_device"), {"task_id": "xlpa_task_2"})
    assert task_scope.active("sess-1") == "xlpa_task_2"
    gate.decide(_mcp("edge_save_device_parameters"), {})
    assert events[-1][1]["target"] == "xlpa_task_2"


# ── deny 语义分流（参数卡 / 会话口令 / 绝对禁止）──

def test_deny_kind_distinguishes_param_card_and_chat_confirm():
    """deny 结论区分“走参数卡”（登记入参）与“走会话口令”（无参写）。"""
    events: list = []
    gate = _collect(events, [])
    # 登记入参的 provision → 参数卡
    gate.decide(_mcp("edge_get_token"), {"ip": "1.1.1.1"})
    assert events[-1][1]["confirm_kind"] == "param_card"
    # 无参 write → 会话口令确认
    gate.decide(_mcp("add_brand"), {"brand": "X"})
    assert events[-1][1]["confirm_kind"] == "chat_confirm"
    # 绝对禁止 login → forbidden（确认无法解除）
    gate.decide(_mcp("login"), {})
    assert events[-1][1]["confirm_kind"] == "forbidden"


def test_chat_confirm_write_reason_directs_session_confirm():
    """无参写被拦时回喂模型的拒绝理由须指示：会话播报摘要并请求 /确认，不得自授权。"""
    gate = _collect([], [])
    allow, reason = gate.decide(_mcp("add_brand"), {"brand": "X"})
    assert allow is False
    assert "/确认" in reason
    assert "摘要" in reason
    assert "不得自行假定已授权" in reason


def test_provision_reason_directs_param_card():
    """登记入参的 provision 被拦：理由指向卡片填凭据，不引导会话口令。"""
    gate = _collect([], [])
    allow, reason = gate.decide(_mcp("edge_get_token"), {"ip": "1.1.1.1"})
    assert allow is False
    assert "/确认" not in reason
    assert "卡片" in reason


# ── 防漂移：按 type 解析 server.py 注册表比对（覆盖云端 + 边缘 + 登录）──

def _registry_pairs() -> list[tuple[str, str]]:
    text = SERVER_PY.read_text(encoding="utf-8")
    return re.findall(r'"name":\s*"([^"]+)",\s*"type":\s*"([^"]+)"', text)


def test_write_tool_names_match_registry():
    """WRITE_TOOL_NAMES 必须等于注册表 type∈{write,edge_write} 全集。"""
    pairs = _registry_pairs()
    assert pairs, "未解析到任何工具注册项（正则或路径失效）"
    registry_writes = {n for n, t in pairs if t in {"write", "edge_write"}}
    assert set(WRITE_TOOL_NAMES) == registry_writes


def test_cloud_and_edge_subsets_disjoint_and_typed():
    """云端/边缘子集分别对应 type==write / type==edge_write 且不相交。"""
    pairs = _registry_pairs()
    by_type = {}
    for name, typ in pairs:
        by_type.setdefault(typ, set()).add(name)
    assert CLOUD_WRITE_TOOL_NAMES == by_type.get("write", set())
    assert EDGE_WRITE_TOOL_NAMES == by_type.get("edge_write", set())
    assert not (CLOUD_WRITE_TOOL_NAMES & EDGE_WRITE_TOOL_NAMES)


def test_login_tool_names_match_registry():
    """LOGIN_TOOL_NAMES = 注册表 type==login 全集（仅业务登录）。"""
    pairs = _registry_pairs()
    registry_logins = {n for n, t in pairs if t == "login"}
    assert LOGIN_TOOL_NAMES == registry_logins
    assert "edge_get_token" not in LOGIN_TOOL_NAMES


def test_provision_tool_names_match_registry():
    """PROVISION_TOOL_NAMES = {edge_get_token}，其注册 type==edge_util。"""
    pairs = _registry_pairs()
    by_name = dict(pairs)
    assert PROVISION_TOOL_NAMES == {"edge_get_token"}
    assert by_name.get("edge_get_token") == "edge_util"
    # 开辟类不得与登录/写入类重叠
    assert not (PROVISION_TOOL_NAMES & LOGIN_TOOL_NAMES)
    assert not (PROVISION_TOOL_NAMES & WRITE_TOOL_NAMES)
