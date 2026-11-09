"""产物与上传：三通道落点分道、产物登记、一次性 grant 代理下载。

对应 design D1/D3/D4/D5：
- 上传以 ``channel`` 分道：``text`` 不进本模块（复用 send_message）、
  ``archive_table`` 代理转发 mcp_server 换 file_id（**不落会话工作区**）、
  ``document`` 落 ``workspace/xlpa-input/``（PDF 额外抽取
  ``<stem>.pdf.md`` 结构化 Markdown）、
  ``screenshot`` 经本地 OCR 转文本落位；
- 产物登记表是下载的**白名单**：artifact_id 是客户端可控输入，MUST NOT 直接
  拼接路径，未命中登记表一律拒绝（天然消除 ``../`` 逃逸）；
- 下载经后端代理 + 一次性 grant（请求头 ``X-Artifact-Grant``），
  URL/事件 payload 均不携带凭据或 grant。
"""

from __future__ import annotations

__all__ = [
    "ArtifactEntry",
    "ArtifactRegistry",
    "artifact_id_for",
    "build_artifacts_router",
    "scan_outputs",
    "unique_path",
]

import asyncio
import hashlib
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

import httpx
from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse

from .ocr import OcrFailed, OcrUnavailable
from .pdf_extract import extract_pdf_markdown
from .sessions_api import _require_user

if TYPE_CHECKING:
    from .api import AppState

_CHUNK = 64 * 1024
_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
# 建档表格通道只接受 Excel；PDF/图片必须走 document / screenshot 通道。
_ARCHIVE_TABLE_EXTENSIONS = frozenset({".xlsx", ".xls", ".xlsm"})

# 产物事件写回调：(event_type, payload) -> None。
EventWriter = Callable[[str, dict], None]


@dataclass
class ArtifactEntry:
    """服务端产物登记项（下载白名单事实源）。"""

    artifact_id: str
    session_id: str
    name: str
    path: Path
    size: int
    created_at: float


class ArtifactRegistry:
    """内存态产物登记表：artifact_id → 来源（一期仅会话工作区来源 A）。"""

    def __init__(self):
        self._entries: dict[tuple[str, str], ArtifactEntry] = {}

    def register(
        self, session_id: str, name: str, path: Path, *, size: int | None = None
    ) -> ArtifactEntry | None:
        """登记产物；已登记（幂等）返回 None，新登记返回条目。"""
        artifact_id = artifact_id_for(name)
        key = (session_id, artifact_id)
        if key in self._entries:
            return None
        entry = ArtifactEntry(
            artifact_id=artifact_id,
            session_id=session_id,
            name=name,
            path=Path(path),
            size=size if size is not None else Path(path).stat().st_size,
            created_at=time.time(),
        )
        self._entries[key] = entry
        return entry

    def get(self, session_id: str, artifact_id: str) -> ArtifactEntry | None:
        """按 (会话, 产物) 取登记项；未登记返回 None。"""
        return self._entries.get((session_id, artifact_id))

    def list(self, session_id: str) -> list[ArtifactEntry]:
        """列出会话的已登记产物。"""
        return [e for (sid, _), e in self._entries.items() if sid == session_id]

    def clear_session(self, session_id: str) -> None:
        """清理会话全部登记项（删除会话时调用）。"""
        for key in [k for k in self._entries if k[0] == session_id]:
            del self._entries[key]


def artifact_id_for(rel_name: str) -> str:
    """由产物相对名派生稳定 artifact_id（仅作登记表键，不参与路径拼接）。"""
    return hashlib.sha256(rel_name.encode("utf-8")).hexdigest()[:16]


def scan_outputs(
    session_id: str,
    workspace: Path | str,
    registry: ArtifactRegistry,
    event_writer: EventWriter | None = None,
) -> list[ArtifactEntry]:
    """扫描 ``workspace/xlpa-output/`` 新增产物并登记 + 产 artifact 事件。

    一期只检测来源 A（工作区扫描）；重复扫描幂等（已登记不重复产事件）。
    payload 不含凭据、不含一次性 grant。
    """
    output_dir = Path(workspace) / "xlpa-output"
    if not output_dir.exists():
        return []
    added: list[ArtifactEntry] = []
    for path in sorted(output_dir.rglob("*")):
        if not path.is_file():
            continue
        rel_name = path.relative_to(output_dir).as_posix()
        entry = registry.register(
            session_id, rel_name, path, size=path.stat().st_size
        )
        if entry is None:
            continue
        added.append(entry)
        if event_writer is not None:
            event_writer(
                "artifact",
                {
                    "artifact_id": entry.artifact_id,
                    "name": entry.name,
                    "size": entry.size,
                },
            )
    return added


class _TooLarge(Exception):
    """上传超过通道上限（转 413）。"""


def _safe_filename(raw: str | None, fallback: str = "upload.bin") -> str:
    """取安全文件名：仅保留 basename，防目录穿越。"""
    name = Path(raw or "").name.strip()
    return name or fallback


def unique_path(directory: Path, name: str) -> Path:
    """若同名文件已存在，追加 ``_1``/``_2`` 后缀避免覆盖。"""
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / name
    if not candidate.exists():
        return candidate
    stem, suffix = Path(name).stem, Path(name).suffix
    index = 1
    while True:
        candidate = directory / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


async def _stream_to(upload: UploadFile, dest: Path, limit: int) -> int:
    """流式落盘并按上限校验；超限删半成品并抛 ``_TooLarge``。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    try:
        with dest.open("wb") as fp:
            while True:
                chunk = await upload.read(_CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    raise _TooLarge
                fp.write(chunk)
    except _TooLarge:
        dest.unlink(missing_ok=True)
        raise
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    if size == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="上传文件为空")
    return size


def _build_pdf_text_result(workspace: Path, pdf_path: Path) -> dict:
    """把 PDF 结构化抽取结果写入同目录 ``<stem>.pdf.md``，返回完成/告警载荷。

    该函数只做文件与解析工作，不触碰请求对象；由上传端点在后台任务中
    经线程池调用，保证上传响应不被长解析阻塞。

    Returns:
        事件载荷：成功含 ``text_path``/``text_chars``；失败含 ``warning``。
    """
    payload: dict = {"name": pdf_path.name}
    text_dest = unique_path(workspace / "xlpa-input", f"{pdf_path.stem}.pdf.md")
    try:
        extracted = extract_pdf_markdown(pdf_path)
    except ImportError:
        payload["warning"] = (
            "PDF 文本提取组件未安装（PyMuPDF），已保留原文件；"
            "请安装依赖或手动提供文本"
        )
        return payload
    except Exception as exc:  # noqa: BLE001 - 解析失败显式降级，不静默成功
        payload["warning"] = (
            f"PDF 文本提取失败（{type(exc).__name__}），已保留原文件；"
            "请改用截图 OCR 或手动提供文本"
        )
        return payload
    if not extracted.strip():
        payload["warning"] = (
            "PDF 未提取到文本（可能为扫描件），已保留原文件；"
            "请改用截图 OCR 或手动提供文本"
        )
        return payload
    try:
        text_dest.write_text(extracted, encoding="utf-8")
    except OSError as exc:
        payload["warning"] = (
            f"PDF 文本写入失败（{type(exc).__name__}），已保留原文件"
        )
        return payload
    payload["text_path"] = f"xlpa-input/{text_dest.name}"
    payload["text_chars"] = len(extracted)
    return payload


def build_artifacts_router(state: "AppState") -> APIRouter:
    """构建产物上传/下载路由（闭合 AppState）。"""
    router = APIRouter(prefix="/api/sessions")
    runtime = state.runtime
    registry = state.artifacts
    grants = state.download_grants
    settings = state.settings

    def _owned_session(request: Request, session_id: str):
        """校验会话票据 + 归属，返回会话。"""
        username, _ = _require_user(state, request)
        session = runtime.get(session_id)
        if session is None or session.username != username:
            raise HTTPException(status_code=404, detail="会话不存在")
        return session

    @router.post("/{session_id}/artifacts/upload")
    async def upload(
        request: Request,
        session_id: str,
        background_tasks: BackgroundTasks,
        channel: str = Form(...),
        file: UploadFile = File(...),
    ) -> dict:
        """三通道上传落点分道（表格经代理换 file_id，不进工作区）。"""
        session = _owned_session(request, session_id)
        if session.closed:
            raise HTTPException(status_code=409, detail="会话已结束")
        runtime.touch(session)

        name = _safe_filename(file.filename)
        if channel == "text":
            raise HTTPException(
                status_code=400, detail="文本请经 /messages 直接发送"
            )

        if channel == "archive_table":
            # 渠道与文件类型不匹配时直接给出可操作提示，不把 PDF 代理到
            # 建档上传端点（上游只会返回难懂的 HTTP 400）。
            if Path(name).suffix.lower() not in _ARCHIVE_TABLE_EXTENSIONS:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "建档表格通道仅支持 .xlsx/.xls 文件；"
                        "PDF/图片等请将上传通道切换为「文档」或「截图(OCR)」"
                    ),
                )
            limit = settings.upload_max_table_bytes
            staging = (
                session.workspace
                / "xlpa-tmp"
                / f"upload-{secrets.token_hex(8)}.xlsx"
            )
            try:
                size = await _stream_to(file, staging, limit)
            except _TooLarge as exc:
                raise HTTPException(
                    status_code=413,
                    detail=f"表格超过上限 {limit} 字节",
                ) from exc
            try:
                data = staging.read_bytes()
                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.post(
                        f"{settings.mint_url}/api/archive/uploads",
                        content=data,
                        headers={
                            "Authorization": f"Bearer {session.mcp_token}",
                            "Content-Type": _XLSX_MIME,
                        },
                    )
            finally:
                # 不落会话工作区：临时副本用后即删
                staging.unlink(missing_ok=True)
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=502,
                    detail=f"建档上传代理失败（上游 HTTP {resp.status_code}）",
                )
            payload = resp.json()
            file_id = payload.get("file_id")
            if not file_id:
                raise HTTPException(
                    status_code=502, detail="建档上传代理未返回 file_id"
                )
            return {
                "channel": "archive_table",
                "file_id": file_id,
                "size": size,
                "sha256": payload.get("sha256", ""),
            }

        if channel == "document":
            limit = settings.upload_max_document_bytes
            dest = unique_path(session.workspace / "xlpa-input", name)
            try:
                size = await _stream_to(file, dest, limit)
            except _TooLarge as exc:
                raise HTTPException(
                    status_code=413,
                    detail=f"文档超过上限 {limit} 字节",
                ) from exc
            body = {
                "channel": "document",
                "name": dest.name,
                "path": f"xlpa-input/{dest.name}",
                "size": size,
                "category": "input",
            }
            # PDF 文本提取放后台：上传立即返回，解析完成后经 upload_text 事件
            # 通知前端（大 PDF 逐页提取可达数十秒，不得阻塞上传响应）。
            if dest.suffix.lower() == ".pdf":
                body["text_status"] = "pending"

                async def _run_pdf_extraction(
                    sid: str, workspace: Path, pdf_path: Path
                ) -> None:
                    try:
                        payload = await asyncio.to_thread(
                            _build_pdf_text_result, workspace, pdf_path
                        )
                        # 会话已被物理删除时不再写事件（文件随工作区一并删除）
                        if runtime.get(sid) is not None:
                            state.events.append(sid, "upload_text", payload)
                    finally:
                        runtime.finish_text_extraction(sid, pdf_path.name)

                # 先登记再排队：用户紧接着发消息时，轮次会等该任务完成再启动
                runtime.begin_text_extraction(session, dest.name)
                background_tasks.add_task(
                    _run_pdf_extraction, session.id, session.workspace, dest
                )
            return body

        if channel == "screenshot":
            limit = settings.upload_max_image_bytes
            provider = state.ocr_provider
            if provider is None:
                # 依赖缺失/关闭：截图通道明确降级，不影响其他通道与主服务
                raise HTTPException(
                    status_code=503, detail="OCR 不可用，请改用文本或表格上传"
                )
            staging = (
                session.workspace
                / "xlpa-tmp"
                / f"screenshot-{secrets.token_hex(8)}.png"
            )
            try:
                size = await _stream_to(file, staging, limit)
            except _TooLarge as exc:
                raise HTTPException(
                    status_code=413,
                    detail=f"图片超过上限 {limit} 字节",
                ) from exc
            try:
                try:
                    result = provider.recognize(staging.read_bytes())
                except OcrUnavailable as exc:
                    raise HTTPException(
                        status_code=503,
                        detail="OCR 不可用，请改用文本或表格上传",
                    ) from exc
                except OcrFailed as exc:
                    # 显式失败，绝不静默以猜测内容继续
                    raise HTTPException(status_code=422, detail=str(exc)) from exc
            finally:
                staging.unlink(missing_ok=True)
            text_name = f"{Path(name).stem}.ocr.txt"
            dest = unique_path(session.workspace / "xlpa-input", text_name)
            dest.write_text(result.text, encoding="utf-8")
            return {
                "channel": "screenshot",
                "name": dest.name,
                "path": f"xlpa-input/{dest.name}",
                "size": dest.stat().st_size,
                "category": "input",
                "text": result.text,
                "confidence": result.confidence,
            }

        raise HTTPException(status_code=400, detail=f"未知上传通道: {channel}")

    @router.post("/{session_id}/artifacts/{artifact_id}/grant")
    async def mint_download_grant(
        request: Request, session_id: str, artifact_id: str
    ) -> dict:
        """按需铸造一次性下载 grant（经响应体返回，绝不入事件 payload）。"""
        session = _owned_session(request, session_id)
        runtime.touch(session)
        entry = registry.get(session_id, artifact_id)
        if entry is None or not entry.path.exists():
            raise HTTPException(status_code=404, detail="产物不存在")
        token, expires_at = grants.mint(session_id, artifact_id)
        return {"grant": token, "expires_at": expires_at}

    @router.get("/{session_id}/artifacts/{artifact_id}/download")
    async def download(
        request: Request, session_id: str, artifact_id: str
    ):
        """代理下载：会话票据 + 归属 + 登记表命中 + 一次性 grant 消费。"""
        session = _owned_session(request, session_id)
        runtime.touch(session)
        entry = registry.get(session_id, artifact_id)
        if entry is None or not entry.path.exists():
            raise HTTPException(status_code=404, detail="产物不存在")
        grant = request.headers.get("x-artifact-grant", "")
        if not grants.consume(grant, session_id, artifact_id):
            # 未签发/已消费/过期/跨会话 → 一律拒绝（不泄漏他人产物信息）
            raise HTTPException(status_code=403, detail="下载授权无效或已使用")
        return FileResponse(entry.path, filename=entry.path.name)

    return router
