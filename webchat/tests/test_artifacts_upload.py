"""三通道上传分道 + 会话删除端点测试（fake mcp_server / fake OCR）。"""

from __future__ import annotations

import pytest

from webchat.ocr import OcrFailed, OcrResult, OcrUnavailable


class _StubOcr:
    """伪造 OCR provider。"""

    def __init__(self, *, text="识别文本", fail=None):
        self.text = text
        self.fail = fail
        self.calls = 0

    def recognize(self, image_bytes: bytes) -> OcrResult:
        self.calls += 1
        if self.fail is True:
            raise OcrFailed("OCR 未识别到文字，请改用文本或表格上传")
        if self.fail == "unavailable":
            raise OcrUnavailable("OCR 引擎不可用")
        return OcrResult(text=self.text, structure_ok=True, confidence=0.95)


class _FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FakeMCPClient:
    """伪造 httpx.AsyncClient：记录代理请求，返回 file_id。"""

    captured: dict = {}

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, content=None, headers=None):
        _FakeMCPClient.captured = {
            "url": url,
            "content": content,
            "headers": headers or {},
        }
        return _FakeResponse({"ok": True, "file_id": "fid-1", "sha256": "deadbeef"})


def _minimal_pdf(text: str) -> bytes:
    """构造最小可解析 PDF（含一行文本），用于验证文本提取。"""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objects[3] = (
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
        + stream + b"\nendstream"
    )
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer << /Root 1 0 R /Size {len(objects) + 1} >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    ).encode()
    return bytes(out)


def _upload(client, headers, session_id, channel, name, data, content_type):
    return client.post(
        f"/api/sessions/{session_id}/artifacts/upload",
        headers=headers,
        data={"channel": channel},
        files={"file": (name, data, content_type)},
    )


def test_document_channel_lands_in_xlpa_input(
    client_factory, bootstrap
):
    """文档通道：落 xlpa-input/（input 分类），运行时可读取。"""
    client = client_factory()
    headers, session_id, state = bootstrap(client)
    resp = _upload(
        client, headers, session_id, "document", "协议文档.txt",
        b"protocol-body", "text/plain",
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["channel"] == "document"
    assert body["path"] == "xlpa-input/协议文档.txt"
    assert body["category"] == "input"
    workspace = state.runtime.get(session_id).workspace
    target = workspace / "xlpa-input" / "协议文档.txt"
    assert target.exists() and target.read_text(encoding="utf-8") == "protocol-body"


def test_archive_table_proxies_and_keeps_no_workspace_copy(
    client_factory, bootstrap, monkeypatch
):
    """表格通道：代理 mcp_server 换 file_id，工作区不残留副本。"""
    monkeypatch.setattr("webchat.artifacts.httpx.AsyncClient", _FakeMCPClient)
    client = client_factory()
    headers, session_id, state = bootstrap(client)
    resp = _upload(
        client, headers, session_id, "archive_table", "表格.xlsx",
        b"fake-xlsx-bytes", "application/vnd.ms-excel",
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["file_id"] == "fid-1"
    session = state.runtime.get(session_id)
    assert _FakeMCPClient.captured["url"].endswith("/api/archive/uploads")
    assert _FakeMCPClient.captured["headers"]["Authorization"] == (
        f"Bearer {session.mcp_token}"
    )
    # 不落会话工作区：临时副本用后即删
    assert list((session.workspace / "xlpa-tmp").iterdir()) == []
    assert list((session.workspace / "xlpa-input").iterdir()) == []


def test_upload_over_limit_returns_413(client_factory, bootstrap):
    """超限一律 413，且不残留半成品文件。"""
    client = client_factory(settings_kwargs={"upload_max_document_bytes": 8})
    headers, session_id, state = bootstrap(client)
    resp = _upload(
        client, headers, session_id, "document", "big.txt", b"x" * 64, "text/plain"
    )
    assert resp.status_code == 413
    assert list((state.runtime.get(session_id).workspace / "xlpa-input").iterdir()) == []


def test_text_channel_rejected_and_unknown_channel_rejected(
    client_factory, bootstrap
):
    """文本通道走 /messages（400）；未知通道 400。"""
    client = client_factory()
    headers, session_id, _ = bootstrap(client)
    text_resp = _upload(
        client, headers, session_id, "text", "a.txt", b"hello", "text/plain"
    )
    assert text_resp.status_code == 400
    unknown = _upload(
        client, headers, session_id, "photo", "a.png", b"png", "image/png"
    )
    assert unknown.status_code == 400


def test_screenshot_saves_original_and_ocr(client_factory, bootstrap):
    """截图通道双落盘：原图按原扩展名保留 + .ocr.txt 兕底（design D3）。"""
    client = client_factory()
    headers, session_id, state = bootstrap(client)
    state.ocr_provider = _StubOcr(text="设备编号 12345")
    resp = _upload(
        client, headers, session_id, "screenshot", "screen.png", b"png-bytes", "image/png"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["path"] == "xlpa-input/screen.png"
    assert body["ocr_path"] == "xlpa-input/screen.ocr.txt"
    assert body["text"] == "设备编号 12345"
    assert state.ocr_provider.calls == 1
    workspace = state.runtime.get(session_id).workspace
    # 原图字节与上传一致；OCR 文本兜底同目录
    assert (workspace / "xlpa-input" / "screen.png").read_bytes() == b"png-bytes"
    assert (workspace / "xlpa-input" / "screen.ocr.txt").read_text(
        encoding="utf-8"
    ) == "设备编号 12345"
    assert list((workspace / "xlpa-tmp").iterdir()) == []


@pytest.mark.parametrize(
    "provider,fail_mode",
    [
        (_StubOcr(fail=True), "structure"),
        (_StubOcr(fail="unavailable"), "unavailable"),
        (None, "disabled"),
    ],
)
def test_screenshot_ocr_failure_degrades_to_original(
    client_factory, bootstrap, provider, fail_mode
):
    """OCR 失败/依赖缺失 → 200 + 原图保留 + ocr_error 显式告警，不生成 OCR 文件。"""
    client = client_factory()
    headers, session_id, state = bootstrap(client)
    state.ocr_provider = provider
    resp = _upload(
        client, headers, session_id, "screenshot", "screen.png", b"png", "image/png"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["path"] == "xlpa-input/screen.png"
    assert body.get("ocr_error"), body
    assert "ocr_path" not in body
    workspace = state.runtime.get(session_id).workspace
    assert (workspace / "xlpa-input" / "screen.png").read_bytes() == b"png"
    names = [p.name for p in (workspace / "xlpa-input").iterdir()]
    assert names == ["screen.png"]  # 不生成 OCR 文本文件


def test_screenshot_same_name_not_overwritten(client_factory, bootstrap):
    """同名图片两次上传：追加序号后缀，两份原图与各自 OCR 均保留。"""
    client = client_factory()
    headers, session_id, state = bootstrap(client)
    state.ocr_provider = _StubOcr(text="第一张")
    r1 = _upload(
        client, headers, session_id, "screenshot", "pic.jpg", b"one", "image/jpeg"
    )
    state.ocr_provider = _StubOcr(text="第二张")
    r2 = _upload(
        client, headers, session_id, "screenshot", "pic.jpg", b"two", "image/jpeg"
    )
    assert r1.json()["path"] == "xlpa-input/pic.jpg"
    assert r2.json()["path"] == "xlpa-input/pic_1.jpg"
    assert r2.json()["ocr_path"] == "xlpa-input/pic_1.ocr.txt"
    workspace = state.runtime.get(session_id).workspace
    inp = workspace / "xlpa-input"
    assert (inp / "pic.jpg").read_bytes() == b"one"
    assert (inp / "pic_1.jpg").read_bytes() == b"two"
    assert (inp / "pic.ocr.txt").read_text(encoding="utf-8") == "第一张"
    assert (inp / "pic_1.ocr.txt").read_text(encoding="utf-8") == "第二张"


def test_cross_user_upload_and_delete_denied(client_factory, bootstrap):
    """越权上传/删除一律 404（不泄漏他人会话存在性）。"""
    client = client_factory()
    alice_headers, alice_session, _ = bootstrap(client, "alice")
    bob_headers = client.post(
        "/api/auth/login",
        json={"username": "bob", "password": "test-password-1"},
    ).json()
    bob = {"Authorization": f"Bearer {bob_headers['session_token']}"}
    assert _upload(
        client, bob, alice_session, "document", "x.txt", b"x", "text/plain"
    ).status_code == 404
    assert client.delete(f"/api/sessions/{alice_session}", headers=bob).status_code == 404
    # 归属本人可删
    assert client.delete(
        f"/api/sessions/{alice_session}", headers=alice_headers
    ).status_code == 200


def test_delete_session_removes_workspace_and_artifacts(
    client_factory, bootstrap
):
    """删除会话：工作区物理删除，产物下载/铸票一律 404（close 则留存）。"""
    client = client_factory()
    headers, session_id, state = bootstrap(client)
    session = state.runtime.get(session_id)
    output = session.workspace / "xlpa-output" / "report.txt"
    output.write_text("report", encoding="utf-8")
    entry = state.artifacts.register(session_id, "report.txt", output)
    assert entry is not None
    grant = client.post(
        f"/api/sessions/{session_id}/artifacts/{entry.artifact_id}/grant",
        headers=headers,
    )
    assert grant.status_code == 200

    deleted = client.delete(f"/api/sessions/{session_id}", headers=headers)
    assert deleted.status_code == 200
    assert not session.workspace.exists()
    assert state.artifacts.list(session_id) == []
    # 会话记录已移除 → 后续铸票/下载 404
    assert client.post(
        f"/api/sessions/{session_id}/artifacts/{entry.artifact_id}/grant",
        headers=headers,
    ).status_code == 404
    assert client.get(
        f"/api/sessions/{session_id}/artifacts/{entry.artifact_id}/download",
        headers={**headers, "X-Artifact-Grant": grant.json()["grant"]},
    ).status_code == 404


def test_archive_table_rejects_pdf_with_actionable_hint(
    client_factory, bootstrap, monkeypatch
):
    """渠道与类型不符：PDF 走建档表格 → 400 明确提示改选文档，不代理上游。"""
    monkeypatch.setattr("webchat.artifacts.httpx.AsyncClient", _FakeMCPClient)
    _FakeMCPClient.captured = {}
    client = client_factory()
    headers, session_id, state = bootstrap(client)
    resp = _upload(
        client, headers, session_id, "archive_table", "协议.pdf",
        b"%PDF-1.4 invalid", "application/pdf",
    )
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert "建档表格通道仅支持" in detail
    assert "文档" in detail
    assert _FakeMCPClient.captured == {}
    assert list((state.runtime.get(session_id).workspace / "xlpa-tmp").iterdir()) == []


def test_pdf_document_extracts_markdown_sidecar(client_factory, bootstrap,
                                                tmp_path):
    """PDF 文档：原文件落盘，同时生成 <stem>.pdf.md（表格转 GFM）供 agent 读取。"""
    from tests.test_pdf_extract import make_table_pdf

    sample = tmp_path / "sample.pdf"
    make_table_pdf(sample)
    client = client_factory()
    headers, session_id, state = bootstrap(client)
    resp = _upload(
        client, headers, session_id, "document", "协议文档.pdf",
        sample.read_bytes(), "application/pdf",
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["path"] == "xlpa-input/协议文档.pdf"
    # A：上传立即返回，文本提取在后台进行；响应不再等待解析
    assert body["text_status"] == "pending"
    assert "text_path" not in body and "text_chars" not in body
    session = state.runtime.get(session_id)
    workspace = session.workspace
    text = (workspace / "xlpa-input" / "协议文档.pdf.md").read_text(
        encoding="utf-8"
    )
    # 表格以 GFM 保留列结构，不再退化为串列纯文本
    assert "| 地址 | 名称 | 类型 |" in text
    assert "| 0025H | 相电压UA\\|B | Uint16 |" in text
    assert "## 第 1 页" in text
    # 后台任务结束后 pending 标记必须清理（否则后续轮次会白等）
    assert session.pending_text == set()
    # 后台完成后经 upload_text 事件通知前端
    events = client.get(
        f"/api/sessions/{session_id}/history", headers=headers
    ).json()["events"]
    done = [e for e in events if e["type"] == "upload_text"]
    assert done and done[-1]["payload"]["text_path"] == (
        "xlpa-input/协议文档.pdf.md"
    )
    assert done[-1]["payload"]["text_chars"] > 0


def test_invalid_pdf_returns_explicit_warning_without_blocking(
    client_factory, bootstrap
):
    """损坏 PDF：上传成功保留原文件，后台提取失败经事件显式告警。"""
    client = client_factory()
    headers, session_id, state = bootstrap(client)
    resp = _upload(
        client, headers, session_id, "document", "broken.pdf",
        b"not-a-pdf", "application/pdf",
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["text_status"] == "pending"
    session = state.runtime.get(session_id)
    workspace = session.workspace
    assert (workspace / "xlpa-input" / "broken.pdf").exists()
    assert not (workspace / "xlpa-input" / "broken.pdf.md").exists()
    assert session.pending_text == set()
    events = client.get(
        f"/api/sessions/{session_id}/history", headers=headers
    ).json()["events"]
    done = [e for e in events if e["type"] == "upload_text"]
    assert done and "warning" in done[-1]["payload"]
    assert "PDF 文本提取失败" in done[-1]["payload"]["warning"]
