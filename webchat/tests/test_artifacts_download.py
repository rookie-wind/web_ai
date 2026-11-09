"""artifactId 事件 + 一次性 grant + 代理下载测试。"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest

from webchat.grants import DownloadGrantStore
from webchat.sdk_runtime import EVENT_TYPES, WEvent


class _ArtifactHandle:
    """伪造句柄：首次 turn 往 xlpa-output/ 写产物，之后不再写。"""

    wrote = False

    def __init__(self, config, pat_env=None, gate=None):
        self.config = config
        self.gate = gate

    async def close(self):
        return None

    async def run_turn(self, prompt, **kwargs):
        if not _ArtifactHandle.wrote:
            target = self.config.cwd / "xlpa-output" / "建档报告.txt"
            target.write_text("report-body", encoding="utf-8")
            _ArtifactHandle.wrote = True
        yield WEvent(type="text_delta", payload={"text": prompt})
        yield WEvent(type="turn_done", payload={})


@pytest.fixture(autouse=True)
def _reset_handle_state():
    _ArtifactHandle.wrote = False
    yield


def _run_turn(client, state, session_id):
    session = state.runtime.get(session_id)
    session.hold_lease("holder-1", 45)
    asyncio.run(state.runtime.run_message(session, "开始建档", holder_id="holder-1"))
    return session


def test_artifact_in_event_types():
    """artifact/upload_text 必须在封闭 EVENT_TYPES 中（否则被当 unknown 透传）。"""
    assert "artifact" in EVENT_TYPES
    assert "upload_text" in EVENT_TYPES
    assert "turn_aborted" in EVENT_TYPES


def test_turn_scans_outputs_and_emits_artifact_event(client_factory, bootstrap):
    """turn 收尾扫描 xlpa-output → artifact 事件，payload 不含凭据/grant。"""
    client = client_factory(handle_cls=_ArtifactHandle)
    headers, session_id, state = bootstrap(client)
    session = _run_turn(client, state, session_id)

    events = state.events.replay(session_id)
    artifacts = [e for e in events if e["type"] == "artifact"]
    assert len(artifacts) == 1
    payload = artifacts[0]["payload"]
    assert set(payload) == {"artifact_id", "name", "size"}
    assert payload["name"] == "建档报告.txt"
    assert payload["size"] == len("report-body")
    assert session.mcp_token not in str(payload)
    assert "grant" not in payload and "token" not in payload

    entry = state.artifacts.get(session_id, payload["artifact_id"])
    assert entry is not None and entry.path.exists()


def test_repeated_scan_is_idempotent(client_factory, bootstrap):
    """重复扫描不重复登记、不重复产 artifact 事件。"""
    client = client_factory(handle_cls=_ArtifactHandle)
    headers, session_id, state = bootstrap(client)
    session = _run_turn(client, state, session_id)
    asyncio.run(state.runtime.run_message(session, "继续", holder_id="holder-1"))

    artifacts = [
        e for e in state.events.replay(session_id) if e["type"] == "artifact"
    ]
    assert len(artifacts) == 1
    assert len(state.artifacts.list(session_id)) == 1


def test_download_requires_registry_hit(client_factory, bootstrap):
    """未登记/traversal 形态 artifact_id 一律 404（白名单防路径逃逸）。"""
    client = client_factory()
    headers, session_id, _ = bootstrap(client)
    for artifact_id in ("nope", "../../etc/passwd", "..%2F..%2Fetc"):
        resp = client.post(
            f"/api/sessions/{session_id}/artifacts/{artifact_id}/grant",
            headers=headers,
        )
        assert resp.status_code == 404


def test_download_consumes_grant_once(client_factory, bootstrap):
    """合法下载成功；同一 grant 重放被拒（消费即作废）。"""
    client = client_factory()
    headers, session_id, state = bootstrap(client)
    session = state.runtime.get(session_id)
    output = session.workspace / "xlpa-output" / "report.txt"
    output.write_text("download-body", encoding="utf-8")
    entry = state.artifacts.register(session_id, "report.txt", output)
    assert entry is not None

    minted = client.post(
        f"/api/sessions/{session_id}/artifacts/{entry.artifact_id}/grant",
        headers=headers,
    )
    assert minted.status_code == 200
    grant = minted.json()["grant"]
    # URL 不含凭据/grant（grant 只经请求头）
    download_url = f"/api/sessions/{session_id}/artifacts/{entry.artifact_id}/download"
    assert grant not in download_url
    assert "token" not in download_url

    first = client.get(
        download_url, headers={**headers, "X-Artifact-Grant": grant}
    )
    assert first.status_code == 200
    assert first.content == b"download-body"

    replay = client.get(
        download_url, headers={**headers, "X-Artifact-Grant": grant}
    )
    assert replay.status_code == 403


def test_download_without_grant_denied(client_factory, bootstrap):
    """未携带 grant → 403；grant 不属于该会话 → 403。"""
    client = client_factory()
    headers, session_id, state = bootstrap(client)
    session = state.runtime.get(session_id)
    output = session.workspace / "xlpa-output" / "r.txt"
    output.write_text("x", encoding="utf-8")
    entry = state.artifacts.register(session_id, "r.txt", output)
    url = f"/api/sessions/{session_id}/artifacts/{entry.artifact_id}/download"
    assert client.get(url, headers=headers).status_code == 403


def test_grant_is_bound_to_session_and_artifact(client_factory, bootstrap):
    """跨会话/跨产物使用 grant 一律无效（绑定 session_id + artifact_id）。"""
    client = client_factory()
    headers, session_a, state = bootstrap(client)
    created = client.post("/api/sessions", headers=headers)
    session_b = created.json()["session_id"]
    for sid in (session_a, session_b):
        out = state.runtime.get(sid).workspace / "xlpa-output" / "same.txt"
        out.write_text(sid, encoding="utf-8")
        state.artifacts.register(sid, "same.txt", out)
    artifact_id = state.artifacts.list(session_a)[0].artifact_id
    # 两个会话同名产物 → artifact_id 相同（由名字派生），但会话绑定不同
    assert state.artifacts.list(session_b)[0].artifact_id == artifact_id

    grant = client.post(
        f"/api/sessions/{session_a}/artifacts/{artifact_id}/grant", headers=headers
    ).json()["grant"]
    crossed = client.get(
        f"/api/sessions/{session_b}/artifacts/{artifact_id}/download",
        headers={**headers, "X-Artifact-Grant": grant},
    )
    assert crossed.status_code == 403


def test_download_store_consume_semantics():
    """一次性语义：消费即作废、跨会话无效、并发仅一次成功、过期失效。"""
    store = DownloadGrantStore(ttl_seconds=60)
    token, _ = store.mint("s1", "a1")
    assert store.consume(token, "s1", "a1") is True
    assert store.consume(token, "s1", "a1") is False  # 重放
    assert store.consume(token, "s2", "a1") is False  # 跨会话（已被消费）

    other, _ = store.mint("s1", "a2")
    assert store.consume(other, "s2", "a2") is False  # 跨会话
    assert store.consume(other, "s1", "a2") is True

    token3, _ = store.mint("s3", "a3")
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(lambda _: store.consume(token3, "s3", "a3"), range(8))
        )
    assert results.count(True) == 1  # 并发仅一次成功

    expired = DownloadGrantStore(ttl_seconds=0)
    token4, _ = expired.mint("s4", "a4")
    assert expired.consume(token4, "s4", "a4") is False
    assert expired.consume("", "s4", "a4") is False
