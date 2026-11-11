"""来源 B：白名单工具 file_id 回源落盘、登记产物与失败显式提示。"""

from __future__ import annotations

import hashlib
import json

import pytest

from webchat.artifacts import ArtifactRegistry
from webchat.event_store import EventStore
from webchat.runtime import SessionRuntime
from webchat.sdk_runtime import WEvent

TOKEN = "tok-sess"


def _patch_client(monkeypatch, *, status: int = 200, body: bytes = b"tpl-bytes"):
    """替换 runtime 的 httpx 客户端，记录请求并返回固定响应。"""
    calls: list[tuple[str, dict]] = []

    class _Resp:
        status_code = status
        content = body

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, headers=None):
            calls.append((url, dict(headers or {})))
            return _Resp()

    monkeypatch.setattr("webchat.runtime.httpx.AsyncClient", _Client)
    return calls


async def _make_runtime(tmp_path, monkeypatch) -> SessionRuntime:
    async def fake_mint(self, username, session_id):
        return TOKEN

    async def fake_revoke(self, token):
        return None

    monkeypatch.setattr(SessionRuntime, "_mint", fake_mint)
    monkeypatch.setattr(SessionRuntime, "_revoke", fake_revoke)
    # 本文件只测产物回源，不测 SDK 层：fake 句柄隔离 eager 连接
    monkeypatch.setattr("webchat.runtime.AgentHandle", _ToolResultHandle)
    return SessionRuntime(
        mint_url="http://mcp.test",
        mint_secret="x",
        workspaces_dir=tmp_path / "ws",
        events=EventStore(tmp_path / "ev"),
        artifacts=ArtifactRegistry(),
    )


def _payload(tool_use_id: str, data: dict) -> dict:
    return {
        "tool_use_id": tool_use_id,
        "content": json.dumps(data, ensure_ascii=False),
        "is_error": False,
    }


@pytest.mark.asyncio
async def test_template_file_id_fetched_and_registered(tmp_path, monkeypatch):
    """生成模板返回 file_id → 回源落盘、登记并产 artifact 事件。"""
    calls = _patch_client(monkeypatch)
    rt = await _make_runtime(tmp_path, monkeypatch)
    s = await rt.create("alice")
    rt._tool_names["tu-1"] = "generate_device_archive_template"
    await rt._harvest_remote_artifact(
        s,
        _payload("tu-1", {
            "ok": True,
            "file_id": "fid-1",
            "file_name": "设备建档模板_20261031.xlsx",
            "size_bytes": 9,
        }),
    )
    saved = list((s.workspace / "xlpa-output").iterdir())
    assert len(saved) == 1
    assert saved[0].name == "设备建档模板_20261031.xlsx"
    assert saved[0].read_bytes() == b"tpl-bytes"

    arts = [e for e in rt._events.replay(s.id) if e["type"] == "artifact"]
    assert len(arts) == 1
    payload = arts[0]["payload"]
    assert payload["name"] == "设备建档模板_20261031.xlsx"
    serialized = json.dumps(payload, ensure_ascii=False)
    assert TOKEN not in serialized
    assert "owner" not in serialized
    assert "grant" not in serialized

    owner = hashlib.sha256(TOKEN.encode("utf-8")).hexdigest()
    assert calls == [(
        f"http://mcp.test/api/archive/templates/fid-1?owner={owner}",
        {"Authorization": f"Bearer {TOKEN}"},
    )]
    assert s.remote_files["fid-1"] == payload["artifact_id"]


@pytest.mark.asyncio
async def test_same_file_id_registered_once(tmp_path, monkeypatch):
    """同一 file_id 重复出现（如再查下载信息）不再回源、不重复登记。"""
    calls = _patch_client(monkeypatch)
    rt = await _make_runtime(tmp_path, monkeypatch)
    s = await rt.create("alice")
    rt._tool_names["tu-1"] = "get_device_archive_template_download"
    data = {"file_id": "fid-1", "file_name": "tpl.xlsx",
            "download_url": "/api/archive/templates/fid-1?owner=abc"}
    await rt._harvest_remote_artifact(s, _payload("tu-1", data))
    await rt._harvest_remote_artifact(s, _payload("tu-1", data))
    assert len(calls) == 1
    assert calls[0][0] == "http://mcp.test/api/archive/templates/fid-1?owner=abc"
    arts = [e for e in rt._events.replay(s.id) if e["type"] == "artifact"]
    assert len(arts) == 1


@pytest.mark.asyncio
async def test_upstream_failure_emits_error_without_leaking(tmp_path, monkeypatch):
    """回源失败 → error 事件显式提示，不落半成品、不泄露 URL/owner/Token。"""
    _patch_client(monkeypatch, status=500, body=b"")
    rt = await _make_runtime(tmp_path, monkeypatch)
    s = await rt.create("alice")
    rt._tool_names["tu-1"] = "save_conversion_config"
    await rt._harvest_remote_artifact(
        s,
        _payload("tu-1", {"file_id": "fid-2", "file_name": "config.json"}),
    )
    assert not list((s.workspace / "xlpa-output").iterdir())
    assert "fid-2" not in s.remote_files
    errors = [e for e in rt._events.replay(s.id) if e["type"] == "error"]
    assert len(errors) == 1
    text = errors[0]["payload"]["message"]
    assert "config.json" in text
    assert "mcp.test" not in text and TOKEN not in text and "owner" not in text


@pytest.mark.asyncio
async def test_non_whitelisted_tool_ignored(tmp_path, monkeypatch):
    """白名单外工具结果即使含 file_id 也不触发回源。"""
    calls = _patch_client(monkeypatch)
    rt = await _make_runtime(tmp_path, monkeypatch)
    s = await rt.create("alice")
    rt._tool_names["tu-1"] = "edge_get_device_tree"
    await rt._harvest_remote_artifact(
        s, _payload("tu-1", {"file_id": "fid-3", "file_name": "x.json"})
    )
    assert calls == []
    assert [e for e in rt._events.replay(s.id) if e["type"] == "artifact"] == []


class _ToolResultHandle:
    """伪造句柄：先 tool_call 再 tool_result，验证事件循环内自动回源。"""

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
        yield WEvent(type="tool_call", payload={
            "id": "tu-1",
            "name": "mcp__xlpa__generate_device_archive_template",
            "input": {},
        })
        yield WEvent(type="tool_result", payload=_payload("tu-1", {
            "ok": True, "file_id": "fid-loop", "file_name": "模板.xlsx",
        }))
        yield WEvent(type="text_delta", payload={"text": "模板已生成"})
        yield WEvent(type="turn_done", payload={})


@pytest.mark.asyncio
async def test_run_message_bridges_artifact_event(tmp_path, monkeypatch):
    """run_message 事件循环内完成回源，artifact 事件在 tool_result 之后。"""
    _patch_client(monkeypatch)
    rt = await _make_runtime(tmp_path, monkeypatch)
    monkeypatch.setattr("webchat.runtime.AgentHandle", _ToolResultHandle)
    s = await rt.create("alice")
    s.hold_lease("h", 45)
    await rt.run_message(s, "生成建档模板", holder_id="h")
    events = rt._events.replay(s.id)
    types = [e["type"] for e in events]
    assert types.index("tool_result") < types.index("artifact")
    assert types.index("artifact") < types.index("turn_done")
    assert len([t for t in types if t == "artifact"]) == 1
