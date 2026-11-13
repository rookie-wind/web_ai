"""web-ui-content-security：全部响应必须携带 CSP 头且脚本仅同源。

行为契约（change: add-webchat-rich-rendering）：
- 单页入口、静态资源与 API 响应均含 Content-Security-Policy；
- script 指令仅允许同源（缺省回落 default-src 'self' 亦可），
  不得出现 unsafe-inline / unsafe-eval / data: / http: 脚本源；
- style-src 需放行内联样式（图形渲染库运行时注入）；
- img-src 允许同源与 data:；connect-src 仅同源（SSE/fetch）。
"""

from __future__ import annotations

import pytest

from webchat.api import create_app
from webchat.config import Settings

# CSP 指令解析：策略串 → {directive: [sources]}（source 保留引号原样）
CSP_HEADER = "content-security-policy"


def _parse_csp(policy: str) -> dict:
    """把 CSP 策略串解析为指令字典。"""
    directives: dict[str, list[str]] = {}
    for part in policy.split(";"):
        tokens = part.strip().split()
        if not tokens:
            continue
        directives[tokens[0]] = tokens[1:]
    return directives


def _script_sources(directives: dict) -> list[str]:
    """取脚本有效来源：显式 script-src 优先，否则回落 default-src。"""
    return directives.get("script-src") or directives.get("default-src") or []


@pytest.fixture
def csp_client(tmp_path):
    """仅用于静态与鉴权路由的最小应用（不登录）。"""
    accounts_path = tmp_path / "accounts.json"
    accounts_path.write_text('{"accounts": []}', encoding="utf-8")
    settings = Settings(
        session_ttl=3600,
        rate_window=60,
        rate_max_failures=1000,
        accounts_path=accounts_path,
        permissions_path=tmp_path / "permissions.json",
        platform_base_url="https://platform.test",
        host="127.0.0.1",
        port=8800,
        mint_secret="test-mint-secret",
        mint_url="http://127.0.0.1:8765",
        max_instances=8,
        max_sessions_per_user=3,
        max_turns=25,
        workspaces_dir=tmp_path / "workspaces",
        events_dir=tmp_path / "events",
        lease_ttl=45,
        grant_ttl=300,
        gate_audit_path=tmp_path / "gate_audit.jsonl",
    )

    async def fake_login(phone, code, base_url, transport=None):
        return {"userId": "1", "phone": phone, "token": "biz"}

    from fastapi.testclient import TestClient

    return TestClient(
        create_app(settings, platform_login_impl=fake_login),
        base_url="http://127.0.0.1:8800",
    )


@pytest.mark.parametrize(
    "path",
    ["/", "/static/app.css", "/static/js/app.js", "/static/js/api.js"],
)
def test_responses_carry_csp_header(csp_client, path):
    """页面、静态资源与 API 响应均必须携带 CSP 头。"""
    resp = csp_client.get(path)
    assert resp.status_code == 200, path
    assert CSP_HEADER in resp.headers, path


def test_api_error_response_carries_csp_header(csp_client):
    """鉴权失败等 API 响应（含异常响应）同样携带 CSP 头。"""
    resp = csp_client.post(
        "/api/auth/login",
        json={"username": "ghost", "password": "wrong"},
    )
    assert resp.status_code == 401
    assert CSP_HEADER in resp.headers


def test_csp_policy_shape(csp_client):
    """策略形态：脚本仅同源、样式放行内联、图片含 data:、连接仅同源。"""
    policy = csp_client.get("/").headers[CSP_HEADER]
    directives = _parse_csp(policy)

    # 脚本：仅同源，无任何放宽来源（inline/eval/data:/http 明令禁止）
    script_sources = _script_sources(directives)
    assert "'self'" in script_sources
    for forbidden in ("'unsafe-inline'", "'unsafe-eval'", "data:", "http:"):
        assert forbidden not in script_sources, forbidden

    # 样式：同源 + 内联（mermaid/highlight.js 运行时注入内联样式所必需）
    style_sources = directives.get("style-src", [])
    assert "'self'" in style_sources
    assert "'unsafe-inline'" in style_sources

    # 图片：同源 + data:（图形渲染产物）
    img_sources = directives.get("img-src", [])
    assert "'self'" in img_sources
    assert "data:" in img_sources

    # 连接：仅同源（SSE EventSource / fetch 上传下载）
    assert directives.get("connect-src") == ["'self'"]
