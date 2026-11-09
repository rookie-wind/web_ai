"""端到端：三通道上传 → agent 产物 → artifact 事件 → 一次性 grant → 代理下载。"""

from __future__ import annotations

import asyncio

import pytest

from webchat.ocr import OcrResult
from webchat.sdk_runtime import WEvent


class _E2EHandle:
    """伪造句柄：首次 turn 在 xlpa-output/ 产出报告。"""

    wrote = False

    def __init__(self, config, pat_env=None, gate=None):
        self.config = config
        self.gate = gate

    async def close(self):
        return None

    async def run_turn(self, prompt, **kwargs):
        if not _E2EHandle.wrote:
            target = self.config.cwd / "xlpa-output" / "转换配置.json"
            target.write_text('{"ok": true}', encoding="utf-8")
            _E2EHandle.wrote = True
        yield WEvent(type="text_delta", payload={"text": "已生成产物"})
        yield WEvent(type="turn_done", payload={})


class _StubOcr:
    def recognize(self, image_bytes: bytes) -> OcrResult:
        return OcrResult(text="设备 10086", structure_ok=True, confidence=0.99)


class _FakeResponse:
    status_code = 200

    def json(self):
        return {"ok": True, "file_id": "fid-e2e", "sha256": "abc"}


class _FakeMCPClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, content=None, headers=None):
        return _FakeResponse()


def _upload(client, headers, session_id, channel, name, data, ctype):
    return client.post(
        f"/api/sessions/{session_id}/artifacts/upload",
        headers=headers,
        data={"channel": channel},
        files={"file": (name, data, ctype)},
    )


@pytest.fixture(autouse=True)
def _reset():
    _E2EHandle.wrote = False
    yield


def test_upload_artifact_download_end_to_end(
    client_factory, bootstrap, monkeypatch
):
    """三通道落点正确 + 产物事件 + grant 上传后下载成功 + 凭据不进 URL/事件。"""
    monkeypatch.setattr("webchat.artifacts.httpx.AsyncClient", _FakeMCPClient)
    client = client_factory(handle_cls=_E2EHandle)
    headers, session_id, state = bootstrap(client)
    state.ocr_provider = _StubOcr()
    session = state.runtime.get(session_id)

    # 1) 三通道上传
    table = _upload(
        client, headers, session_id, "archive_table", "建档表.xlsx", b"xlsx", "application/octet-stream"
    )
    assert table.status_code == 200 and table.json()["file_id"] == "fid-e2e"
    doc = _upload(
        client, headers, session_id, "document", "协议.pdf", b"pdf-bytes", "application/pdf"
    )
    assert doc.status_code == 200 and doc.json()["path"] == "xlpa-input/协议.pdf"
    shot = _upload(
        client, headers, session_id, "screenshot", "shot.png", b"png", "image/png"
    )
    assert shot.status_code == 200 and shot.json()["text"] == "设备 10086"
    assert (session.workspace / "xlpa-input" / "shot.ocr.txt").exists()

    # 2) agent 执行一轮 → artifact 事件
    asyncio.run(state.runtime.run_message(session, "生成转换配置", holder_id="holder-1"))
    artifact_events = [
        e for e in state.events.replay(session_id) if e["type"] == "artifact"
    ]
    assert len(artifact_events) == 1
    payload = artifact_events[0]["payload"]
    assert payload["name"] == "转换配置.json"
    # 事件 payload 不含凭据/grant
    assert session.mcp_token not in str(payload)
    assert "grant" not in payload

    # 3) 按需铸票 → 下载（grant 只经请求头）
    artifact_id = payload["artifact_id"]
    minted = client.post(
        f"/api/sessions/{session_id}/artifacts/{artifact_id}/grant", headers=headers
    )
    assert minted.status_code == 200
    grant = minted.json()["grant"]
    url = f"/api/sessions/{session_id}/artifacts/{artifact_id}/download"
    assert grant not in url and "token" not in url
    downloaded = client.get(url, headers={**headers, "X-Artifact-Grant": grant})
    assert downloaded.status_code == 200
    assert downloaded.content == b'{"ok": true}'
    # 重放同一 grant 被拒
    assert client.get(
        url, headers={**headers, "X-Artifact-Grant": grant}
    ).status_code == 403
