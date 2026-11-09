"""技能目录索引与前缀注入测试（canonical agent_assets 形态）。"""

from __future__ import annotations

import pytest

import qodercn_agent_sdk as q

from webchat.event_store import EventStore
from webchat.runtime import SessionRuntime
from webchat.sdk_runtime import AdapterConfig, AgentHandle, WEvent
from webchat.skills import load_catalog


def _write_skill(root, name: str, description: str, when: str, body: str = "") -> None:
    """写入一个最小 SKILL.md（frontmatter + 正文）。"""
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(
        "---\n"
        f"name: {name}\n"
        "description: >\n"
        f"  {description}\n"
        "when_to_use: >\n"
        f"  {when}\n"
        "---\n\n"
        f"# {name}\n\n{body}\n",
        encoding="utf-8",
    )


def _result(session_id: str = "sid-1") -> q.ResultMessage:
    return q.ResultMessage(
        subtype="success", session_id=session_id, is_error=False,
        num_turns=1, duration_ms=1, duration_api_ms=1,
    )


def test_catalog_index_and_prefix_match(tmp_path):
    """索引含 name/description/适用场景/SKILL.md 路径；前缀大小写不敏感。"""
    root = tmp_path / "skills"
    _write_skill(root, "xlpa", "协议转换入口", "用户提到协议转换")
    _write_skill(root, "modbus-conversion", "Modbus 转换", "寄存器/RTU")
    catalog = load_catalog(root)
    assert [s.name for s in catalog.skills] == ["modbus-conversion", "xlpa"]
    index = catalog.render_index()
    assert "xlpa" in index and "modbus-conversion" in index
    assert "SKILL.md" in index
    assert "先按上面的路径用 Read 读取" in index
    assert set(catalog.texts) == {"xlpa", "modbus-conversion"}


def test_empty_or_missing_root_is_safe(tmp_path):
    """目录缺失时不抛异常（服务可继续启动），索引给出明确说明。"""
    catalog = load_catalog(tmp_path / "missing")
    assert catalog.skills == ()
    assert "未发现技能目录" in catalog.render_index()


@pytest.mark.asyncio
async def test_adapter_index_in_system_prompt_and_prefix_injects(tmp_path, monkeypatch):
    """技能索引进系统提示；/xlpa 前缀当轮注入全文，普通消息不注入。"""
    from tests.fake_sdk_client import install

    clients = install(monkeypatch, [[_result()], [_result()], [_result()]])
    config = AdapterConfig(
        cwd=tmp_path,
        mcp_url="http://127.0.0.1:8765/mcp",
        mcp_token="test-token",
        skill_index="【技能索引】xlpa → /agent_assets/skills/xlpa/SKILL.md",
        skill_texts={"xlpa": "SKILL-FULL-TEXT"},
    )
    handle = AgentHandle(config)

    async for _event in handle.run_turn("/xlpa 帮我生成脚本"):
        pass
    assert "【技能索引】" in clients[0].options.system_prompt["append"]
    assert "SKILL-FULL-TEXT" in clients[0].queries[0]

    async for _event in handle.run_turn("你好"):
        pass
    assert "SKILL-FULL-TEXT" not in clients[0].queries[1]

    async for _event in handle.run_turn("/unknown 随便聊聊"):
        pass
    assert "SKILL-FULL-TEXT" not in clients[0].queries[2]
    await handle.close()


class _CaptureHandle:
    """伪造句柄：记录注入的配置与门禁，供运行时装配断言。"""

    last: "_CaptureHandle | None" = None

    def __init__(self, config, pat_env=None, gate=None):
        self.config = config
        self.gate = gate
        _CaptureHandle.last = self

    async def close(self):
        pass

    async def run_turn(self, prompt, **kwargs):
        yield WEvent(type="turn_done", payload={})


@pytest.mark.asyncio
async def test_runtime_wires_catalog_into_handle_and_read_gate(
    tmp_path, monkeypatch
):
    """运行时把索引/全文传给句柄，并把技能目录纳入 Read 白名单。"""
    root = tmp_path / "skills"
    _write_skill(root, "xlpa", "协议转换入口", "用户提到协议转换", body="BODY")
    catalog = load_catalog(root)

    async def fake_mint(self, username, session_id):
        return "tok"

    async def fake_revoke(self, token):
        return None

    monkeypatch.setattr(SessionRuntime, "_mint", fake_mint)
    monkeypatch.setattr(SessionRuntime, "_revoke", fake_revoke)
    monkeypatch.setattr("webchat.runtime.AgentHandle", _CaptureHandle)
    extra_root = tmp_path / "qoder-mcp-outputs"
    extra_root.mkdir()
    (extra_root / "tool-result.txt").write_text("result", encoding="utf-8")
    runtime = SessionRuntime(
        mint_url="http://127.0.0.1:8765",
        mint_secret="x",
        workspaces_dir=tmp_path / "ws",
        events=EventStore(tmp_path / "events"),
        max_instances=2,
        max_sessions_per_user=2,
        max_turns=5,
        lease_ttl=45,
        skill_catalog=catalog,
        read_extra_roots=(extra_root,),
    )
    session = await runtime.create("alice")
    session.hold_lease("h1", 45)
    await runtime.run_message(session, "hi", holder_id="h1")

    handle = _CaptureHandle.last
    assert handle is not None
    assert "xlpa" in handle.config.skill_index
    assert handle.config.skill_texts["xlpa"] == catalog.texts["xlpa"]
    assert handle.gate.check_read(
        {"file_path": str(root / "xlpa" / "SKILL.md")}
    )[0] is True
    assert handle.gate.check_read(
        {"file_path": str(extra_root / "tool-result.txt")}
    )[0] is True
    assert handle.gate.check_read(
        {"file_path": str(tmp_path / "secret.txt")}
    )[0] is False
