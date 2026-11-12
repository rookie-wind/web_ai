"""C7 组3 前端骨架验证：`/` 出登录页、静态资源可取、凭据不入 URL。

API 侧行为不变由既有 test_account_auth.py 等覆盖；本文件只验证静态
挂载与单页入口（3.1/3.2 的 pytest 部分），浏览器冒烟另行留证。
"""

from __future__ import annotations

from pathlib import Path

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
    """输入区提示可选路由前缀：失焦紧凑短文案，完整释义经聚焦展开。"""
    body = ui_client.get("/").text
    app_js = ui_client.get("/static/js/app.js").text
    # 紧凑形态：短文案含前缀关键字与可选语义
    assert "可选前缀 /web /xlpa" in body
    # 完整释义经聚焦展开可达（MODIFIED requirement：语义不丢失）
    assert "/web 强制网页检索" in app_js
    assert "/xlpa 强制协议助手" in app_js
    assert "默认自动判断" in app_js
    assert "必须使用前缀" not in body + app_js


def test_guard_notice_rendering_marker(ui_client):
    """内置写入路径护栏：前端按 guard 标识弱化展示（不渲染禁止卡）。"""
    app_js = ui_client.get("/static/js/app.js").text
    assert 'p.guard === "builtin_write_path"' in app_js
    assert "renderWriteGuardNotice" in app_js
    assert ".guard-line" in ui_client.get("/static/app.css").text


def test_upload_channel_auto_detect_and_default_document(ui_client):
    """通道按扩展名自动匹配（channelForFile），默认文档；无手动通道下拉。"""
    app_js = ui_client.get("/static/js/app.js").text
    assert "function channelForFile" in app_js
    assert '".xlsx": "archive_table"' in app_js
    body = ui_client.get("/").text
    assert 'id="upload-channel"' not in body
    assert 'id="btn-attach"' in body


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
    assert 'id="btn-send"' in ui_client.get("/").text
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


def test_new_session_dialog_account_choice(ui_client) -> None:
    """新建会话对话框：默认/自带账号单选 + PAT 掩码框 + 记住勾选。"""
    body = ui_client.get("/").text
    assert 'id="new-session-dialog"' in body
    assert 'name="account-source"' in body
    assert 'value="byo"' in body
    assert 'id="byo-pat"' in body
    assert 'id="remember-pat"' in body
    app_js = ui_client.get("/static/js/app.js").text
    assert "account_source" in app_js
    assert "new-session-dialog" in app_js


def test_compose_model_dropdown(ui_client) -> None:
    """输入区模型下拉：取自账号清单、含成本标记、消息级切换。"""
    body = ui_client.get("/").text
    assert 'id="model-select"' in body
    app_js = ui_client.get("/static/js/app.js").text
    assert "/models" in app_js
    assert "model-select" in app_js
    assert "price_factor" in app_js


def test_byo_pat_error_no_plaintext(ui_client) -> None:
    """校验失败有提示位、PAT 掩码、凭据经 POST body 不进 URL。"""
    body = ui_client.get("/").text
    assert 'id="new-session-error"' in body
    assert 'type="password"' in body
    app_js = ui_client.get("/static/js/app.js").text
    assert "new-session-error" in app_js
    assert "body: { account_source, pat, remember }" in app_js
    assert "?token=" not in app_js


def test_remembered_pat_prefill_and_clear_ui(ui_client) -> None:
    """自带 PAT 预填（取记账号库）与清除入口。"""
    body = ui_client.get("/").text
    assert 'id="btn-clear-pat"' in body
    app_js = ui_client.get("/static/js/app.js").text
    assert "/api/account/qoder-pat" in app_js
    assert "btn-clear-pat" in app_js


def test_brand_xlpa_zhiti(ui_client) -> None:
    """品牌统一为 XLPA 智体（title/登录/topbar），旧称移除。"""
    body = ui_client.get("/").text
    assert "XLPA 智体" in body
    assert "XLPA 助手" not in body
    assert "XLPA 协议转换助手" not in body


def test_design_tokens(ui_client) -> None:
    """形式化设计 token：spacing/type/radius/shadow scale。"""
    css = ui_client.get("/static/app.css").text
    assert "--space-" in css
    assert "--text-" in css
    assert "--radius-" in css
    assert "--shadow-" in css


def test_composer_card_structure(ui_client) -> None:
    """一体化 composer：附件 chip 行 + 工具栏（＋/模型/中止/发送），无手动通道下拉。"""
    body = ui_client.get("/").text
    assert 'id="attachment-chips"' in body
    assert 'class="compose-toolbar"' in body
    assert 'id="btn-attach"' in body
    assert 'id="upload-channel"' not in body
    assert 'id="btn-upload"' not in body


def test_attach_button_auto_channel(ui_client) -> None:
    """［＋］触发选文件并按扩展名自动定通道，无手动通道读取。"""
    app_js = ui_client.get("/static/js/app.js").text
    assert "btn-attach" in app_js
    assert "channelForFile" in app_js
    assert "upload-channel" not in app_js


def test_attachment_chip_delete(ui_client) -> None:
    """附件以 chip 呈现，pending 列表可逐个删除。"""
    app_js = ui_client.get("/static/js/app.js").text
    assert "pendingAttachments" in app_js
    assert "renderAttachments" in app_js
    assert "removeAttachment" in app_js


def test_send_merges_attachments(ui_client) -> None:
    """发送时上传暂存附件并合并文本与引用。"""
    app_js = ui_client.get("/static/js/app.js").text
    assert "uploadStagedAttachments" in app_js
    assert "[text, ...refs]" in app_js


def test_mobile_full_viewport(ui_client) -> None:
    """移动端全视口 app-like 布局：fixed 沉浸 + safe-area 适配。"""
    css = ui_client.get("/static/app.css").text
    assert "position: fixed" in css
    assert "inset: 0" in css
    assert "safe-area-inset" in css


def test_component_states_focus(ui_client) -> None:
    """组件焦点可见性与禁用态覆盖（WCAG AA）。"""
    css = ui_client.get("/static/app.css").text
    assert "focus-visible" in css
    assert ":disabled" in css


def test_textarea_auto_grow(ui_client) -> None:
    """文本输入自适应增高（D1）。"""
    app_js = ui_client.get("/static/js/app.js").text
    assert 'ta.style.height = "auto"' in app_js


def test_view_app_fixed_immersive(ui_client) -> None:
    """主视图 fixed 沉浸：脱离文档流，顶栏不可被文档滚动推出（iOS 键盘残留）。"""
    css = ui_client.get("/static/app.css").text
    block = css.split("/* 全视口沉浸", 1)[1].split("}", 1)[0]
    assert "position: fixed" in block
    assert "inset: 0" in block
    # 文档流高度手段移除（100vh/100dvh 不再用于主视图布局）
    assert "100vh" not in css
    assert "100dvh" not in css


def test_view_switch_resets_scroll(ui_client) -> None:
    """切视图复位文档滚动并失焦（iOS 键盘收起残留兜底）。"""
    app_js = ui_client.get("/static/js/app.js").text
    enter_block = app_js.split("function enterAppView", 1)[1].split(
        "function handleErr", 1
    )[0]
    assert "window.scrollTo(0, 0)" in enter_block
    assert "blur()" in enter_block
    logout_block = app_js.split("async function doLogout", 1)[1].split(
        "function enterAppView", 1
    )[0]
    assert "window.scrollTo(0, 0)" in logout_block
    assert "blur()" in logout_block


def test_session_ready_unlocks_composer(ui_client) -> None:
    """session_ready 事件：解锁输入区并重拉模型清单。"""
    app_js = ui_client.get("/static/js/app.js").text
    assert 'case "session_ready"' in app_js
    assert "loadModels(ev.session_id)" in app_js


def test_session_failed_shows_banner(ui_client) -> None:
    """session_failed 事件：错误横幅展示原因并刷新列表。"""
    app_js = ui_client.get("/static/js/app.js").text
    assert 'case "session_failed"' in app_js
    assert "初始化失败" in app_js
    # 失败后刷新会话列表（呈失败态）
    block = app_js.split('case "session_failed"', 1)[1].split("break;", 1)[0]
    assert "refreshSessions()" in block


def test_creating_state_locks_composer(ui_client) -> None:
    """初始化中：输入区禁用 + sticky 提示；openSession 按列表 status 设态。"""
    app_js = ui_client.get("/static/js/app.js").text
    assert "function setSessionInit" in app_js
    assert "正在初始化" in app_js
    # openSession 依据列表 meta.status 设初始态
    assert "setSessionInit(meta ? meta.status : " in app_js
    # 会话列表呈现初始化中/创建失败
    assert "初始化中…" in app_js
    assert "创建失败" in app_js


def test_failed_byo_reopens_dialog(ui_client) -> None:
    """自带 PAT 失败：自动重开创建弹窗并回填原因与输入（不丢已输内容）。"""
    app_js = ui_client.get("/static/js/app.js").text
    assert "function openNewSessionDialog" in app_js
    assert "state.lastCreate" in app_js
    # 回填账号来源/PAT/记住勾选（模板串拼接源值）
    assert 'input[name="account-source"][value="${source}"]' in app_js
    # 创建成功即记录本次创建上下文（session_id/来源/PAT/记住勾选）
    assert (
        "state.lastCreate = { session_id: r.session_id, "
        "account_source, pat, remember }"
    ) in app_js


def test_failed_session_row_delete_only(ui_client) -> None:
    """失败会话列表行：仅保留删除入口（打开/结束不渲染）。"""
    app_js = ui_client.get("/static/js/app.js").text
    assert 's.status !== "failed"' in app_js
    assert "创建失败" in app_js


def test_model_cost_price_factor_first(ui_client) -> None:
    """模型成本标记：price_factor 优先显示 ×N，is_free 仅兜底。"""
    app_js = ui_client.get("/static/js/app.js").text
    assert "m.price_factor != null ? `×${m.price_factor}`" in app_js
    assert 'm.is_free ? "免费" : ""' in app_js
    # 旧口径（is_free 直接渲染「免费」）已移除
    assert 'm.is_free ? "免费" : (m.price_factor != null' not in app_js


def test_upload_ref_mentions_original_and_ocr(ui_client) -> None:
    """图片上传引用文案：原图路径 + OCR 兜底路径（或 OCR 失败说明）。"""
    app_js = ui_client.get("/static/js/app.js").text
    assert "已上传图片 ${res.path}（助手可直接查看）" in app_js
    assert "OCR 文本 ${res.ocr_path}（读不了图时用）" in app_js
    assert "OCR 识别失败" in app_js


def test_no_auto_fullscreen(ui_client) -> None:
    """移除登录自动全屏（文件 picker 会退出全屏）。"""
    app_js = ui_client.get("/static/js/app.js").text
    assert "requestFullscreen" not in app_js
    assert "tryImmersiveFullscreen" not in app_js


def test_stage_before_upload(ui_client) -> None:
    """附件先暂存（不立即上传），发送时才上传。"""
    app_js = ui_client.get("/static/js/app.js").text
    assert "uploadStagedAttachments" in app_js
    assert "{ name: file.name, file }" in app_js
    # change 处理器内不得出现 uploadFile（选文件仅暂存）
    change_block = app_js.split('$("#upload-file").addEventListener("change"', 1)[1]
    change_block = change_block.split("function renderAttachments", 1)[0]
    assert "uploadFile" not in change_block


def test_chip_delete_visible(ui_client) -> None:
    """chip 文件名独立 span 截断，✕ flex-shrink:0 始终可见。"""
    app_js = ui_client.get("/static/js/app.js").text
    css = ui_client.get("/static/app.css").text
    assert 'el("span", "chip-name", att.name)' in app_js
    name_block = css.split(".chip-name {", 1)[1].split("}", 1)[0]
    assert "flex: 1" in name_block
    assert "min-width: 0" in name_block
    assert "text-overflow: ellipsis" in name_block
    delete_block = css.split(".chip-delete {", 1)[1].split("}", 1)[0]
    assert "flex-shrink: 0" in delete_block


def test_send_uploads_staged(ui_client) -> None:
    """发送时上传暂存附件并合并引用。"""
    app_js = ui_client.get("/static/js/app.js").text
    assert "await uploadStagedAttachments()" in app_js


def test_send_keeps_failed_upload_chips(ui_client) -> None:
    """发送成功只清已送出 chip；上传失败（无 ref）保留以便重试或移除。"""
    app_js = ui_client.get("/static/js/app.js").text
    marker = "state.pendingAttachments = state.pendingAttachments.filter((a) => !a.ref)"
    assert marker in app_js


def test_upload_busy_notice_sticky(ui_client) -> None:
    """上传期间忙碌提示常驻（不自清），上传结束由结果提示替换。"""
    app_js = ui_client.get("/static/js/app.js").text
    assert "function notify(msg, isError = false, sticky = false)" in app_js
    assert "notify(`上传中… ${att.name}`, false, true)" in app_js


def test_send_stop_toggle(ui_client) -> None:
    """发送/停止合一为切换按钮（无独立 btn-abort）。"""
    body = ui_client.get("/").text
    app_js = ui_client.get("/static/js/app.js").text
    assert 'id="btn-abort"' not in body
    assert "abortTurn" in app_js
    assert "is-stop" in app_js


def test_vendor_assets_available(ui_client) -> None:
    """第三方渲染库经 /static/vendor 同源分发，文件头记录来源与版本。"""
    for path in (
        "/static/vendor/marked.esm.js",
        "/static/vendor/purify.es.mjs",
        "/static/vendor/highlight.min.js",
        "/static/vendor/mermaid.min.js",
    ):
        resp = ui_client.get(path)
        assert resp.status_code == 200, path
        # vendored 头注释：来源 URL + 版本号（web-ui-content-security 要求）
        assert "vendored from" in resp.text[:500], path


def test_index_references_vendor_and_no_cdn(ui_client) -> None:
    """index.html 引用同源 vendor；页面与前端脚本无外部 CDN 引用。"""
    body = ui_client.get("/").text
    assert "/static/vendor/highlight.min.js" in body
    app_js = ui_client.get("/static/js/app.js").text
    render_js = ui_client.get("/static/js/render.js").text
    for text, label in ((body, "index.html"), (app_js, "app.js"),
                        (render_js, "render.js")):
        for cdn in ("cdn.jsdelivr.net", "unpkg.com", "cdnjs.cloudflare.com",
                    "registry.npmmirror.com"):
            assert cdn not in text, f"{label}: {cdn}"


def test_rich_render_pipeline_markers(ui_client) -> None:
    """富渲染管线 marker：消毒链、mermaid strict+懒加载、节流与最终渲染、锚定。"""
    app_js = ui_client.get("/static/js/app.js").text
    render_js = ui_client.get("/static/js/render.js").text
    # 消毒链（render.js）：marked 产出 → DOMPurify 白名单 → 注入
    assert "marked.parse" in render_js
    assert "DOMPurify.sanitize" in render_js
    assert "SANITIZE_OPTIONS" in render_js
    # mermaid：strict 安全模式 + 懒加载（动态注入同源 vendor script）
    assert 'securityLevel: "strict"' in render_js
    assert "/static/vendor/mermaid.min.js" in render_js
    assert 'createElement("script")' in render_js
    # 代码块复制按钮（白名单保留标签，事件委托处理点击）
    assert "btn-code-copy" in render_js
    # app.js：节流重渲染 + 最终精确渲染 + 滚动锚定；用户消息仍纯文本
    assert "RENDER_THROTTLE_MS" in app_js
    assert "function flushAgentRender" in app_js
    assert "function nearBottom" in app_js
    assert 'el("div", "bubble user", text)' in app_js


ADAPTER_PATH = (Path(__file__).resolve().parents[1]
                / "webchat" / "sdk_runtime" / "adapter.py")


def test_system_append_output_convention() -> None:
    """系统提示追加段包含输出格式约定（表格 markdown / 流程 mermaid）。"""
    src = ADAPTER_PATH.read_text(encoding="utf-8")
    assert "markdown 表格" in src
    assert "mermaid" in src


def test_sanitize_whitelist_svg_markers(ui_client) -> None:
    """消毒白名单补全 marker：dy/dx 定位属性与 foreignObject 边标签容器。"""
    render_js = ui_client.get("/static/js/render.js").text
    # SVG 定位属性（多行标签逐行定位）与基线类防御性补充
    for attr in ('"dy"', '"dx"', '"dominant-baseline"', '"startoffset"'):
        assert attr in render_js, attr
    # 边标签容器：mermaid v11.4.1 边标签唯一产出路径，内部递归消毒
    assert '"foreignObject"' in render_js


def test_figure_threshold_fit_markers(ui_client) -> None:
    """图阈值混合适配 marker：常量、归一化、可发现性提示。"""
    render_js = ui_client.get("/static/js/render.js").text
    assert "FIGURE_FIT_MAX_WIDTH" in render_js
    assert "is-scrollable" in render_js
    assert "左右滑动查看" in render_js
    css = ui_client.get("/static/app.css").text
    assert ".is-scrollable" in css
    assert "figure-scroll-hint" in css


def test_composer_compact_markers(ui_client) -> None:
    """composer 紧凑 marker：占位符双态、1 行初始、间距收紧、16px 底线。"""
    body = ui_client.get("/").text
    app_js = ui_client.get("/static/js/app.js").text
    css = ui_client.get("/static/app.css").text
    # 失焦短文案与单行初始
    assert 'rows="1"' in body
    assert "PLACEHOLDER_COMPACT" in app_js
    # 自适应增高上限收紧
    assert "ta.scrollHeight, 120" in app_js
    # 间距收紧
    attach_block = css.split(".attach-btn {", 1)[1].split("}", 1)[0]
    assert "width: 30px" in attach_block
    assert "height: 30px" in attach_block
    select_block = css.split(".compose-toolbar select {", 1)[1].split("}", 1)[0]
    assert "max-width: 150px" in select_block
    # 16px 反缩放契约保留
    media = css.split("@media (max-width: 640px) {", 1)[1]
    assert "font-size: 16px" in media


def test_system_append_figure_layout_convention() -> None:
    """系统提示含图布局紧凑规则（TB 方向 / 泳道 / 节点文案精简）。"""
    src = ADAPTER_PATH.read_text(encoding="utf-8")
    assert "TB" in src
    assert "泳道" in src
    assert "10 字" in src


def test_mobile_16px_antizoom(ui_client) -> None:
    """移动端媒体查询内表单控件 16px；不以 maximum-scale 禁用缩放；select 占位。"""
    css = ui_client.get("/static/app.css").text
    body = ui_client.get("/").text
    media = css.split("@media (max-width: 640px) {", 1)[1]
    assert ".compose textarea" in media
    assert ".compose-toolbar select" in media
    assert "font-size: 16px" in media
    assert "maximum-scale" not in body
    assert 'value="" disabled' in body
