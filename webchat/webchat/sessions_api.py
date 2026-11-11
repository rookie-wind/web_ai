"""会话 API：创建/列表/事件流(SSE)/发送消息/租约/关闭/历史。

全部路由要求携带 C2 会话票据（Authorization: Bearer <webchat 票据>）。
"""

from __future__ import annotations

__all__ = ["build_sessions_router"]

import asyncio
import json
import logging
import shutil
import time
from typing import TYPE_CHECKING, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

if TYPE_CHECKING:
    from .api import AppState

_HEARTBEAT = b":ping\n\n"
# SSE 增量轮询周期与心跳间隔（秒）；轮询只读新增字节，不重读历史。
_SSE_POLL_INTERVAL = 0.5
_SSE_HEARTBEAT_INTERVAL = 15.0

logger = logging.getLogger(__name__)


class MessageRequest(BaseModel):
    """发送消息请求体。"""

    text: str


class CreateSessionRequest(BaseModel):
    """创建会话请求体（Qoder 云账号选择；缺省默认账号）。"""

    account_source: Literal["default", "byo"] = "default"
    pat: str = ""
    remember: bool = False


class ModelRequest(BaseModel):
    """模型切换请求体（消息级）。"""

    model: str


class LeaseRequest(BaseModel):
    """租约请求体。"""

    holder_id: str
    takeover: bool = False


class ConfirmRequest(BaseModel):
    """写入确认请求体（铸造计划域写票据）。"""

    target: str
    tool_name: str = ""


class AbortRequest(BaseModel):
    """中止任务请求体；task_id 为空时中止本会话记录过的全部建档任务。"""

    task_id: str = ""


def _require_user(state: "AppState", request: Request) -> tuple[str, str]:
    """校验 C2 票据，返回 (username, bearer_token)。"""
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="会话无效或已过期")
    token = auth[len("Bearer "):].strip()
    session = state.sessions.get(token)
    if session is None:
        raise HTTPException(status_code=401, detail="会话无效或已过期")
    return session.username, token


def build_sessions_router(state: "AppState") -> APIRouter:
    """构建会话路由（闭合 AppState）。"""
    router = APIRouter(prefix="/api/sessions")
    runtime = state.runtime

    @router.post("")
    async def create_session(
        request: Request, body: CreateSessionRequest | None = None
    ) -> dict:
        """创建会话：快路秒回；慢路（激活/连接/清单）后台执行（design D2）。

        慢路由 finalize_session 包装：失败/超时转 failed 并保留会话记录
        （经 session_failed 事件与列表 status 呈现）；"记住 PAT" 仅在就绪
        后持久化。初始化期间写路径返回 409（会话初始化中）。
        """
        username, _ = _require_user(state, request)
        account = state.accounts.find(username)
        creds = {"phone": account.phone, "code": account.code} if account else None
        source = body.account_source if body else "default"
        pat = body.pat if body else ""
        remember = bool(body.remember) if body else False
        try:
            session = await runtime.create(username)
        except Exception as exc:  # noqa: BLE001 - 配额/凭据快路失败统一 409
            raise HTTPException(status_code=409, detail=str(exc))

        async def _finalize() -> None:
            await runtime.finalize_session(
                session, account=creds, account_source=source, qoder_pat=pat
            )
            # 记住自带 PAT：仅 byo 且勾选且就绪时明文落账号库（ADR-0004）
            if session.status == "ready" and remember and source == "byo" and pat:
                try:
                    state.accounts.set_qoder_pat(username, pat)
                except Exception:  # noqa: BLE001 - 持久化失败不影响已就绪会话
                    logger.warning("记住 PAT 落盘失败", exc_info=True)

        session.init_task = asyncio.create_task(_finalize())
        return {"session_id": session.id, "username": username}

    @router.get("")
    async def list_sessions(request: Request) -> dict:
        """列出当前用户的会话。"""
        username, _ = _require_user(state, request)
        items = [
            {
                "session_id": s.id,
                "closed": s.closed,
                "created_at": s.created_at,
                "turn_running": s.turn_running,
                "last_seq": state.events.last_seq(s.id),
                "status": s.status,
                "status_error": s.status_error,
            }
            for s in runtime.list_for(username)
        ]
        return {"sessions": items}

    @router.get("/{session_id}/models")
    async def session_models(request: Request, session_id: str) -> dict:
        """当前会话账号的可用模型清单（只列启用）与当前选中模型。"""
        username, _ = _require_user(state, request)
        session = runtime.get(session_id)
        if session is None or session.username != username:
            raise HTTPException(status_code=404, detail="会话不存在")
        return {
            "models": session.models,
            "current_model": session.current_model,
        }

    @router.post("/{session_id}/model")
    async def set_model(
        request: Request, session_id: str, body: ModelRequest
    ) -> dict:
        """消息级切换模型（需租约）：清单内放行，越清单/执行中拒绝。"""
        username, _ = _require_user(state, request)
        session = runtime.get(session_id)
        if session is None or session.username != username:
            raise HTTPException(status_code=404, detail="会话不存在")
        if session.closed:
            raise HTTPException(status_code=409, detail="会话已结束")
        if session.status != "ready":
            raise HTTPException(status_code=409, detail="会话初始化中，请稍候")
        holder_id = request.headers.get("x-holder-id", "")
        if not holder_id or not session.has_lease(holder_id):
            raise HTTPException(status_code=409, detail="当前连接不持有写租约")
        try:
            current = await runtime.set_model(session, body.model.strip())
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        runtime.touch(session)
        return {"ok": True, "current_model": current}

    @router.get("/{session_id}/events")
    async def stream_events(request: Request, session_id: str) -> StreamingResponse:
        """SSE 事件流：Last-Event-ID 重放 + 实时续传。"""
        username, _ = _require_user(state, request)
        session = runtime.get(session_id)
        if session is None or session.username != username:
            raise HTTPException(status_code=404, detail="会话不存在")
        last_event_id = request.headers.get("last-event-id", "0")
        try:
            after_seq = int(last_event_id)
        except ValueError:
            after_seq = 0

        async def gen():
            # 建连：一次历史重放，同时拿到当前文件字节偏移（锁内原子完成）
            events, offset = state.events.replay_with_offset(
                session_id, after_seq=after_seq
            )
            for event in events:
                data = json.dumps(event, ensure_ascii=False)
                yield f"id: {event['seq']}\ndata: {data}\n\n"
            runtime.touch(session)
            last_ping = time.time()
            try:
                while True:
                    await asyncio.sleep(_SSE_POLL_INTERVAL)
                    # 会话被物理删除（delete）→ 结束该流
                    if runtime.get(session_id) is None:
                        return
                    runtime.touch(session)
                    # 只读上次偏移之后的新增完整行（O(新增)，不重读历史）
                    events, offset = state.events.read_after_offset(
                        session_id, offset
                    )
                    for event in events:
                        data = json.dumps(event, ensure_ascii=False)
                        yield f"id: {event['seq']}\ndata: {data}\n\n"
                    if time.time() - last_ping >= _SSE_HEARTBEAT_INTERVAL:
                        yield _HEARTBEAT
                        last_ping = time.time()
            except asyncio.CancelledError:
                return

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    @router.post("/{session_id}/messages")
    async def send_message(
        request: Request, session_id: str, body: MessageRequest
    ) -> dict:
        """发送消息（需租约）；执行在后台任务中继续。"""
        username, _ = _require_user(state, request)
        session = runtime.get(session_id)
        if session is None or session.username != username:
            raise HTTPException(status_code=404, detail="会话不存在")
        if session.closed:
            raise HTTPException(status_code=409, detail="会话已结束")
        if session.status != "ready":
            raise HTTPException(status_code=409, detail="会话初始化中，请稍候")
        holder_id = request.headers.get("x-holder-id", "")
        if not holder_id or not session.has_lease(holder_id):
            raise HTTPException(status_code=409, detail="当前连接不持有写租约")
        text = body.text.strip()
        if not text:
            raise HTTPException(status_code=400, detail="消息为空")
        # 同会话串行化：上一轮仍在执行时拒绝新消息，避免同一实例并发轮次
        # 造成事件乱序（turn 重复/缺失）与模型重复执行。
        if session.turn_running:
            raise HTTPException(
                status_code=409, detail="上一轮仍在执行，请稍候"
            )
        # 并发轮次护栏：超限直接拒绝，不拉起新的 CLI 子进程、不排队
        if not runtime.try_begin_turn():
            raise HTTPException(
                status_code=409, detail="系统繁忙，请稍后重试"
            )
        runtime.touch(session)
        state.events.append(session_id, "text_delta", {"role": "user", "text": text})

        async def _run() -> None:
            try:
                await runtime.run_message(session, text, holder_id=holder_id)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - 后台轮次失败不拖垮服务
                logger.exception("run_message failed: session=%s", session_id)
            finally:
                runtime.end_turn()
                if session.run_task is asyncio.current_task():
                    session.run_task = None

        # 保留任务句柄，供 /abort 中止当前轮次
        session.run_task = asyncio.create_task(_run())
        return {"accepted": True, "session_id": session_id}

    @router.post("/{session_id}/abort")
    async def abort(
        request: Request,
        session_id: str,
        body: AbortRequest | None = None,
    ) -> dict:
        """中止当前任务：取消 Web 轮次，并请求 MCP 中止建档批次。"""
        username, _ = _require_user(state, request)
        session = runtime.get(session_id)
        if session is None or session.username != username:
            raise HTTPException(status_code=404, detail="会话不存在")
        if session.closed:
            raise HTTPException(status_code=409, detail="会话已结束")
        holder_id = request.headers.get("x-holder-id", "")
        if not holder_id or not session.has_lease(holder_id):
            raise HTTPException(status_code=409, detail="当前连接不持有写租约")
        task_id = (body.task_id.strip() if body else "")
        aborted, cancelled_tasks = await runtime.abort_turn(
            session, task_id=task_id
        )
        return {
            "ok": True,
            "aborted": aborted,
            "tasks_cancelled": cancelled_tasks,
        }

    @router.post("/{session_id}/lease")
    async def lease(request: Request, session_id: str, body: LeaseRequest) -> dict:
        """获取/续期写租约；takeover 时先释放旧租约。"""
        username, _ = _require_user(state, request)
        session = runtime.get(session_id)
        if session is None or session.username != username:
            raise HTTPException(status_code=404, detail="会话不存在")
        if session.closed:
            raise HTTPException(status_code=409, detail="会话已结束")
        if body.takeover:
            session.lease_holder = ""
        ok = session.hold_lease(body.holder_id, state.settings.lease_ttl)
        if not ok:
            raise HTTPException(status_code=409, detail="租约被其他连接持有")
        runtime.touch(session)
        return {"ok": True, "lease_expires": session.lease_expires}

    @router.post("/{session_id}/confirm")
    async def confirm(request: Request, session_id: str, body: ConfirmRequest) -> dict:
        """确认写入：为会话铸造计划域写票据（需租约）。

        票据 target 为 plan_id/task_id（边缘写）或 tool_name（云端写/开辟），
        铸造后 TTL 窗口内同目标多次工具调用均放行（修确认风暴）。对绝对
        禁止类目标（如 login）拒绝铸票，返回 403。
        """
        username, _ = _require_user(state, request)
        session = runtime.get(session_id)
        if session is None or session.username != username:
            raise HTTPException(status_code=404, detail="会话不存在")
        if session.closed:
            raise HTTPException(status_code=409, detail="会话已结束")
        holder_id = request.headers.get("x-holder-id", "")
        if not holder_id or not session.has_lease(holder_id):
            raise HTTPException(status_code=409, detail="当前连接不持有写租约")
        target = body.target.strip()
        if not target:
            raise HTTPException(status_code=400, detail="确认目标为空")
        try:
            expires_at = runtime.confirm_grant(
                session, target, tool_name=body.tool_name.strip()
            )
        except ValueError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        runtime.touch(session)
        # turn_running 供前端判断：本轮仍在跑时不自动发续跑消息（同会话串行）
        return {
            "ok": True,
            "expires_at": expires_at,
            "turn_running": session.turn_running,
        }

    @router.post("/{session_id}/close")
    async def close_session(request: Request, session_id: str) -> dict:
        """结束会话：撤销凭据、终止实例、封存事件。"""
        username, _ = _require_user(state, request)
        session = runtime.get(session_id)
        if session is None or session.username != username:
            raise HTTPException(status_code=404, detail="会话不存在")
        await runtime.close(session)
        return {"ok": True}

    @router.delete("/{session_id}")
    async def delete_session(request: Request, session_id: str) -> dict:
        """删除会话：立即物理删除工作区与全部产物（区别于 close 的按保留期留存）。"""
        username, _ = _require_user(state, request)
        session = runtime.get(session_id)
        if session is None or session.username != username:
            raise HTTPException(status_code=404, detail="会话不存在")
        await runtime.close(session)
        state.artifacts.clear_session(session.id)
        state.download_grants.clear_session(session.id)
        shutil.rmtree(session.workspace, ignore_errors=True)
        runtime.forget(session.id)
        return {"ok": True}

    @router.get("/{session_id}/history")
    async def history(
        request: Request, session_id: str, after_seq: int = 0, limit: int = 500
    ) -> dict:
        """历史事件分页回看。"""
        username, _ = _require_user(state, request)
        session = runtime.get(session_id)
        if session is None or session.username != username:
            raise HTTPException(status_code=404, detail="会话不存在")
        events = state.events.replay(session_id, after_seq=after_seq)[:limit]
        return {"events": events, "count": len(events)}

    return router
