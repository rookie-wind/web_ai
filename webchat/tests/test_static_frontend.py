"""C7 组3 前端骨架验证：`/` 出登录页、静态资源可取、凭据不入 URL。

API 侧行为不变由既有 test_account_auth.py 等覆盖；本文件只验证静态
挂载与单页入口（3.1/3.2 的 pytest 部分），浏览器冒烟另行留证。
"""

from __future__ import annotations

import pytest

from webchat.api import create_app
from webchat.config import Settings


@pytest.fixture
def ui_client(tmp_path):
    """仅用于静态路由的最小应用（不登录）。"""
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


def test_root_serves_login_page(ui_client):
    """/ 返回单页 HTML，含登录表单与模块脚本入口。"""
    resp = ui_client.get("/")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    body = resp.text
    assert 'id="login-form"' in body
    assert 'type="module" src="/static/js/app.js"' in body


def test_static_assets_available(ui_client):
    """css/js 原生 ES 模块经 /static 可取，无凭据参数。"""
    for path, marker in (
        ("/static/app.css", ".login-card"),
        ("/static/js/app.js", 'from "./api.js"'),
        ("/static/js/api.js", "Authorization"),
        ("/static/js/sse.js", "Last-Event-ID"),
    ):
        resp = ui_client.get(path)
        assert resp.status_code == 200, path
        assert marker in resp.text, path


def test_prefix_hint_in_composer(ui_client):
    """输入区提示可选路由前缀（不强制、不拦截输入）。"""
    body = ui_client.get("/").text
    assert "/web 强制网页检索" in body
    assert "/xlpa 强制协议助手" in body
    assert "可选前缀" in body


def test_guard_notice_rendering_marker(ui_client):
    """内置写入路径护栏：前端按 guard 标识弱化展示（不渲染禁止卡）。"""
    app_js = ui_client.get("/static/js/app.js").text
    assert 'p.guard === "builtin_write_path"' in app_js
    assert "renderWriteGuardNotice" in app_js
    assert ".guard-line" in ui_client.get("/static/app.css").text


def test_upload_channel_auto_detect_and_default_document(ui_client):
    """默认通道为文档；选文件后按扩展名自动切换（PDF 不再误走建档表格）。"""
    app_js = ui_client.get("/static/js/app.js").text
    assert "function channelForFile" in app_js
    assert '".xlsx": "archive_table"' in app_js
    body = ui_client.get("/").text
    assert '<option value="document">文档</option>' in body
    assert body.index('value="document"') < body.index('value="archive_table"')


def test_frontend_turn_serial_and_pdf_warning_markers(ui_client):
    """确认续跑按 turn_running 串行；PDF 后台提取与上传忙碌态。"""
    app_js = ui_client.get("/static/js/app.js").text
    assert "r.turn_running" in app_js
    # 4.2 竞态修复：本轮仍忙时续跑登记为待办、turn_done 补发（不再仅提示在当前轮重试）
    assert "已排队，本轮结束后自动继续" in app_js
    assert 'res.text_status === "pending"' in app_js
    assert 'case "upload_text"' in app_js
    assert "PDF 文本提取在后台进行" in app_js
    # C：上传期间禁用按钮并显示“上传中…”，防重复提交
    assert "btn.disabled = true" in app_js
    assert "上传中…" in app_js
    # PDF 旁路路径随上传消息转达；直接读 PDF 被拦截时弱提示
    assert "PDF 内容自动结构化提取到" in app_js
    assert 'p.guard === "pdf_binary"' in app_js
    assert "请助手改读同名 .pdf.md" in app_js
    assert ".pdf.txt" not in app_js
    # 中止当前任务：停止按钮 + /abort + turn_aborted 渲染
    assert 'id="btn-abort"' in ui_client.get("/").text
    assert "function setTurnActive" in app_js
    assert "/abort" in app_js
    assert 'case "turn_aborted"' in app_js
    assert "服务端尚未加载中止接口" in app_js


def test_static_no_credentials_in_urls(ui_client):
    """前端源码约定凭据仅经 Authorization 头（静态检查不含查询串票据）。"""
    body = (
        ui_client.get("/static/js/app.js").text
        + ui_client.get("/static/js/api.js").text
    )
    assert "?token=" not in body
    assert "access_token=" not in body


def test_gate_card_confirm_kind_dispatch(ui_client):
    """3.1 卡片触发面收窄：仅参数卡弹模态卡，无参写走会话口令弱提示。"""
    app_js = ui_client.get("/static/js/app.js").text
    # 按后端 confirm_kind 分流：无参写不再渲染模态确认卡
    assert 'p.confirm_kind === "chat_confirm"' in app_js
    assert "function renderChatConfirmPrompt" in app_js
    # 会话口令弱提示文案（请回复行首 /确认，拒绝则不回复）
    assert "行首 /确认" in app_js
    assert "拒绝则无需回复" in app_js


def test_chat_confirm_command_mints_unique_pending(ui_client):
    """3.2 行首 /确认：对唯一 pending 铸票并转新一轮；非行首/无 pending 不触发。"""
    app_js = ui_client.get("/static/js/app.js").text
    assert "function isChatConfirmCommand" in app_js
    assert "function handleChatConfirm" in app_js
    # 会话侧唯一 pending 注册表
    assert "state.pendingConfirmations" in app_js
    # 只认行首：正则锚定 ^/确认（后面是空白或行尾）
    assert "/^\\/确认" in app_js
    # 收到口令复用 /confirm 铸票后转新一轮带票重跑
    assert "/confirm" in app_js


def test_pending_continuation_captured_and_flushed(ui_client):
    """4.1/4.2 竞态修复：turn_running 时续跑登记为待办，turn_done 补发，turn_aborted 清空。"""
    app_js = ui_client.get("/static/js/app.js").text
    assert "state.pendingContinuations" in app_js
    # 补发经独立函数在 finishTurn（turn_done）调用
    assert "function flushPendingContinuation" in app_js
    assert "flushPendingContinuation(ev.session_id)" in app_js
    # turn_aborted 清空待办
    assert "delete state.pendingContinuations[ev.session_id]" in app_js
    # 旧「直接丢弃续跑、仅提示在当前轮重试」的行为已移除
    assert "助手将在当前轮重试" not in app_js
