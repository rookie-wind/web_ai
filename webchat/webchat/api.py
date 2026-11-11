"""FastAPI 路由：login / logout / me。

依赖注入形态：``create_app(settings, *, platform_login_impl=None)``，
测试用 fake 实现替换平台登录，避免外网依赖。

错误语义（design D7）：
- 账号不存在 / 密码错误 / disabled → 同一 401 响应体（防枚举）；
- 账号库配置错误 → 503（运维问题，可区分）；
- 平台登录失败 → 401 + 脱敏尾号提示，不回显明文凭据。
"""

from __future__ import annotations

__all__ = ["create_app", "AppState"]

import asyncio
import os
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .accounts import AccountsStore
from .artifacts import ArtifactRegistry, build_artifacts_router
from .config import Settings
from .event_store import EventStore
from .gate_audit import GateAuditLog
from .grants import DownloadGrantStore, GrantStore
from .hashing import verify_password
from .ocr import OCRProvider, get_ocr_provider
from .platform_auth import (
    PlatformLoginError,
    is_super_account,
    load_super_accounts,
    platform_login as default_platform_login,
)
from .ratelimit import RateLimiter
from .retention import retention_sweep_loop
from .runtime import SessionRuntime, idle_sweep_loop
from .sessions import SessionStore
from .sessions_api import build_sessions_router
from .skills import load_catalog

PlatformLoginImpl = Callable[
    [str, str, str, httpx.AsyncBaseTransport | None], Awaitable[dict]
]

LOGIN_FAILED_DETAIL = "用户名或密码错误"
PLATFORM_FAILED_DETAIL = "平台凭据绑定失败（手机号尾号 {tail}）"


class LoginRequest(BaseModel):
    """登录请求体。"""

    username: str
    password: str


@dataclass
class AppState:
    """应用共享状态。"""

    settings: Settings
    accounts: AccountsStore
    sessions: SessionStore
    limiter: RateLimiter
    platform_login: PlatformLoginImpl
    super_accounts: dict[str, set[str]]
    events: EventStore
    runtime: SessionRuntime
    audit: GateAuditLog
    artifacts: ArtifactRegistry
    download_grants: DownloadGrantStore
    ocr_provider: OCRProvider | None


def _mask_phone(phone: str) -> str:
    """手机号脱敏为尾号四位。"""
    return phone[-4:] if len(phone) >= 4 else "****"


def _client_ip(request: Request, trusted_proxies: tuple[str, ...] = ()) -> str:
    """取客户端地址；测试环境无 client 时回退占位。

    仅当直连来源命中可信代理列表时才采信 X-Forwarded-For 最左值，
    与 mcp_server 的 _resolve_client_ip 语义对齐，防止伪造转发头
    污染限流分桶。

    Args:
        request: FastAPI 请求对象。
        trusted_proxies: 可信代理地址集合（为空时不采信任何转发头）。

    Returns:
        用于限流分桶的客户端 IP 字符串。
    """
    client = getattr(request, "client", None)
    direct_ip = (client.host if client is not None else "") or "0.0.0.0"
    if direct_ip not in trusted_proxies:
        return direct_ip
    forwarded = request.headers.get("x-forwarded-for", "")
    if not forwarded:
        return direct_ip
    first = forwarded.split(",", 1)[0].strip()
    return first or direct_ip


def create_app(
    settings: Settings,
    *,
    platform_login_impl: PlatformLoginImpl | None = None,
) -> FastAPI:
    """创建 FastAPI 应用。

    Args:
        settings: 配置（load_settings 输出）。
        platform_login_impl: 平台登录实现；默认走 platform_auth.platform_login。
    """
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        """服务生命周期：启动保留期与空闲会话扫描，退出时取消。"""
        tasks = [
            asyncio.create_task(retention_sweep_loop(settings)),
            asyncio.create_task(
                idle_sweep_loop(
                    _app.state.auth.runtime,
                    settings.session_idle_ttl,
                    settings.idle_sweep_interval,
                )
            ),
        ]
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(title="xlpa-webchat", version="0.1.0", lifespan=lifespan)
    events = EventStore(settings.events_dir)
    audit = GateAuditLog(settings.gate_audit_path)
    grants = GrantStore(ttl_seconds=settings.grant_ttl)
    artifacts = ArtifactRegistry()
    download_grants = DownloadGrantStore(ttl_seconds=settings.download_grant_ttl)
    ocr_provider = get_ocr_provider(settings.ocr_enabled, settings.ocr_provider)
    # 技能来源锁定 canonical agent_assets/skills（启动时读索引与全文）
    skill_catalog = load_catalog(settings.skills_root)
    runtime = SessionRuntime(
        mint_url=settings.mint_url,
        # 实例接入与授权激活的 /mcp 与 mint 同属一台 MCP Server，
        # 统一取 mint_url（WEBCHAT_MINT_URL 即其基址）；否则会用
        # 默认 8765 去校验另一台签发的凭据。
        mcp_url=settings.mint_url,
        mint_secret=settings.mint_secret,
        workspaces_dir=settings.workspaces_dir,
        events=events,
        max_instances=settings.max_instances,
        max_sessions_per_user=settings.max_sessions_per_user,
        max_turns=settings.max_turns,
        lease_ttl=settings.lease_ttl,
        # V10 已验范式：PAT 仅经环境变量注入，不出现在子进程命令行
        pat=os.environ.get("QODERCN_PERSONAL_ACCESS_TOKEN", ""),
        grants=grants,
        audit=audit,
        artifacts=artifacts,
        agent_model=settings.agent_model,
        max_concurrent_turns=settings.max_concurrent_turns,
        init_timeout=settings.init_timeout,
        skill_catalog=skill_catalog,
        read_extra_roots=settings.read_extra_roots,
    )
    state = AppState(
        settings=settings,
        accounts=AccountsStore(settings.accounts_path),
        sessions=SessionStore(settings.session_ttl),
        limiter=RateLimiter(
            settings.rate_window,
            settings.rate_max_failures,
            settings.rate_source_max_failures,
        ),
        platform_login=platform_login_impl or default_platform_login,
        super_accounts=load_super_accounts(settings.permissions_path),
        events=events,
        runtime=runtime,
        audit=audit,
        artifacts=artifacts,
        download_grants=download_grants,
        ocr_provider=ocr_provider,
    )
    app.state.auth = state
    app.include_router(build_sessions_router(state))
    app.include_router(build_artifacts_router(state))

    # C7 组3：零构建单页前端（静态挂载 + `/` 出登录页）
    static_dir = Path(__file__).resolve().parent / "static"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

        @app.get("/", include_in_schema=False)
        async def index() -> FileResponse:
            """前端入口：登录页单页应用。"""
            return FileResponse(static_dir / "index.html")

    @app.post("/api/auth/login")
    async def login(request: Request, body: LoginRequest) -> dict:
        """账号密码登录，签发会话票据。"""
        ip = _client_ip(request, state.settings.trusted_proxies)
        hit = state.limiter.check(ip, body.username)
        if hit is not None:
            raise HTTPException(
                status_code=429,
                detail="登录尝试过于频繁，请稍后再试",
                headers={"Retry-After": str(hit.retry_after)},
            )
        if state.accounts.config_error is not None:
            raise HTTPException(status_code=503, detail="服务端账号库配置错误")
        account = state.accounts.find(body.username)
        if account is None:
            state.limiter.record_failure(ip, body.username)
            raise HTTPException(status_code=401, detail=LOGIN_FAILED_DETAIL)
        if not account.enabled:
            state.limiter.record_failure(ip, body.username)
            raise HTTPException(status_code=401, detail=LOGIN_FAILED_DETAIL)
        if not verify_password(body.password, account.password_hash):
            state.limiter.record_failure(ip, body.username)
            raise HTTPException(status_code=401, detail=LOGIN_FAILED_DETAIL)
        try:
            identity = await state.platform_login(
                account.phone,
                account.code,
                state.settings.platform_base_url,
                None,
            )
        except PlatformLoginError:
            raise HTTPException(
                status_code=401,
                detail=PLATFORM_FAILED_DETAIL.format(tail=_mask_phone(account.phone)),
            )
        token, session = state.sessions.create(account.username)
        session.business_token = identity.get("token")
        session.business_user_id = identity.get("userId")
        session.business_phone = identity.get("phone")
        session.is_super = is_super_account(identity, state.super_accounts)
        return {
            "session_token": token,
            "expires_at": session.expires_at,
            "username": session.username,
            "is_super": session.is_super,
        }

    @app.post("/api/auth/logout")
    async def logout(authorization: str = Header(default="")) -> dict:
        """登出，票据立即作废。"""
        token = _bearer_token(authorization)
        if token:
            state.sessions.revoke(token)
        return {"ok": True}

    @app.get("/api/auth/me")
    async def me(authorization: str = Header(default="")) -> dict:
        """票据校验与会话信息。"""
        token = _bearer_token(authorization)
        session = state.sessions.get(token) if token else None
        if session is None:
            raise HTTPException(status_code=401, detail="会话无效或已过期")
        return {
            "username": session.username,
            "expires_at": session.expires_at,
            "is_super": session.is_super,
            "phone_tail": _mask_phone(session.business_phone or ""),
        }

    @app.get("/api/account/qoder-pat")
    async def get_qoder_pat(authorization: str = Header(default="")) -> dict:
        """返回当前用户记住的自带 Qoder PAT（供新建会话预填）。"""
        token = _bearer_token(authorization)
        session = state.sessions.get(token) if token else None
        if session is None:
            raise HTTPException(status_code=401, detail="会话无效或已过期")
        account = state.accounts.find(session.username)
        return {"pat": account.qoder_pat if account else ""}

    @app.delete("/api/account/qoder-pat")
    async def delete_qoder_pat(authorization: str = Header(default="")) -> dict:
        """清除当前用户记住的自带 Qoder PAT（下次需重新输入）。"""
        token = _bearer_token(authorization)
        session = state.sessions.get(token) if token else None
        if session is None:
            raise HTTPException(status_code=401, detail="会话无效或已过期")
        state.accounts.clear_qoder_pat(session.username)
        return {"ok": True}

    return app


def _bearer_token(authorization: str) -> str:
    """解析 Authorization: Bearer 头。"""
    if not authorization.startswith("Bearer "):
        return ""
    return authorization[len("Bearer "):].strip()
