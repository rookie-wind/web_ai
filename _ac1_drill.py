"""AC-1 执行分支演练 · Phase B：浏览器走「确认→执行→回读→下载」。

本阶段会真实写入生产平台一条**可回退**的大类记录（add_classify），
脚本结束时由本进程（不依赖模型行为）经 /mcp 调 del_classify 删除并再回读确认。
选择大类作为写入对象：add_classify / del_classify 是唯一无外键依赖的成对写工具。

凭据经 _ac_local.env / mcp_server/.env 注入，本文件不落任何密钥。
"""

from __future__ import annotations

__all__ = ["main"]

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from _ac1_probe import (  # noqa: E402 - 复用配对实例与 HTTP 助手
    MCP_PORT,
    RUN_DIR,
    TABLE_FILE,
    WEBCHAT_PORT,
    http_json,
    load_env_file,
    start_servers,
    stop_servers,
    unwrap,
)

SHOTS = RUN_DIR / "shots"
REPORT_FILE = RUN_DIR / "phaseB.json"

AC_MARK = f"AC1可删{time.strftime('%m%d%H%M')}"
LOGIN_USER = os.environ.get("PCA_AC_WEBCHAT_USER", "admin")
LOGIN_PASS = os.environ.get("PCA_AC_WEBCHAT_PASS", "admin")
PHONE = os.environ.get("PCA_AC_PHONE", "13912986342")
CODE = os.environ.get("PCA_AC_CODE", "9413")

BASE_PROMPT = (
    f"请调用 mcp 工具 add_classify 新增一个大类，参数 sysName 必须精确等于"
    f"「{AC_MARK}」，这是本次验收用的临时数据，之后会删除。"
    "调用被门禁拦截时请停下来等待我在页面确认，确认成功后重试同一工具。"
    "完成后请再调用 get_classify_list 回读确认该大类已存在，并把结果告诉我。"
)

TIMEOUT_TURN = int(os.environ.get("PCA_AC_TURN_TIMEOUT", "600"))
TIMEOUT_CARD = int(os.environ.get("PCA_AC_CARD_TIMEOUT", "420"))
FOLLOWUP_TEXT = (
    "我已在页面确认刚才的写入，现在请在同一会话里重新调用一次 add_classify，"
    f"参数 sysName 严格等于「{AC_MARK}」（不要改写、不要自己判已存在），"
    "然后把工具返回的原始结果贴出来。"
)

ARTIFACT_TEXT = (
    "请务必使用内置的 Write 工具（绝对不要用 Bash 或 shell 重定向）把本次"
    "验收演练的过程与结论写成一份 Markdown 报告，file_path 必须落在会话"
    "工作区的 xlpa-output/ 目录下（如 xlpa-output/ac1_drill_report.md），"
    f"内容包含标记「{AC_MARK}」、add_classify 结果与 get_classify_list"
    "回读到的行，方便我在页面下载留证。"
)


def browser_exe() -> str | None:
    """定位可复用的 chromium（不触发下载）。"""
    override = os.environ.get("PCA_TEST_BROWSER", "").strip()
    if override and Path(override).exists():
        return override
    root = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    for name in ("chromium-1243", "chromium-1244", "chromium-1245"):
        exe = root / name / "chrome-win64" / "chrome.exe"
        if exe.exists():
            return str(exe)
    return None


def notice_text(page: Any) -> str:
    """读页面提示区（上传/发送的失败原因会写在这里）。"""
    try:
        return page.text_content("#compose-notice") or ""
    except Exception:  # noqa: BLE001 - 提示区不可读视为无提示
        return ""


def _card_heading(page: Any) -> str:
    """安全读取首张卡片标题（卡片可能已消失）。"""
    try:
        return page.locator(".card-gate").first.locator(
            "h3").inner_text(timeout=3000)
    except Exception:  # noqa: BLE001 - 卡片重建/已消失
        return ""


def shot(page: Any, tag: str, report: dict) -> str:
    """截图留证并登记相对路径。"""
    SHOTS.mkdir(parents=True, exist_ok=True)
    path = SHOTS / f"{tag}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
    except Exception as exc:  # noqa: BLE001 - 截图失败不阻断演练
        report.setdefault("shot_errors", []).append(f"{tag}: {exc}")
        return ""
    rel = str(path.relative_to(ROOT))
    report.setdefault("screenshots", []).append(rel)
    print(f"[B] 截图 {rel}", flush=True)
    return rel


def wait_for(predicate, timeout: float, interval: float = 1.0) -> bool:
    """轮询直至条件成立或超时。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if predicate():
                return True
        except Exception:  # noqa: BLE001 - 页面瞬时状态异常继续轮询
            pass
        time.sleep(interval)
    return False


def _send_message(state: dict, text: str) -> None:
    """在页面输入框填文并发送。"""
    page = state["page"]
    page.fill("#msg-input", text)
    page.click("#btn-send")
    report = state["report"]
    report.setdefault("messages_sent", []).append(text[:120])
    print(f"[B] 发送 -> {text[:80]}…", flush=True)


def _handle_cards(state: dict) -> int:
    """处理当前待确认卡片，返回本次确认张数。"""
    page = state["page"]
    report = state["report"]
    done = 0
    while True:
        cards = page.locator(".card-gate:not(.done)")
        if cards.count() == 0:
            return done
        try:
            title = cards.first.locator("h3").inner_text(timeout=5000)
        except Exception:  # noqa: BLE001 - 卡片可能刚刚被重建
            title = "(读取卡片标题失败)"
        shot(page, f"B06_gate_card_{report.get('confirmations', 0) + 1}", report)
        report.setdefault("gate_cards", []).append(title)
        try:
            page.locator(".card-gate:not(.done)").first.get_by_role(
                "button", name="确认写入").click(timeout=10000)
        except Exception as exc:  # noqa: BLE001 - 按钮不可达则计错并返回
            report.setdefault("confirm_errors", []).append(str(exc)[:200])
            return done
        report["confirmations"] = report.get("confirmations", 0) + 1
        confirmed = wait_for(lambda: "已确认" in _card_heading(page), 60)
        report.setdefault("confirm_results", []).append(
            {"ok": confirmed, "heading": _card_heading(page)[:120]})
        shot(page, f"B07_confirmed_{report['confirmations']}", report)
        done += 1


def _watch(
    state: dict, budget: float, after: int, handle_cards: bool = True
) -> tuple[int, bool, int]:
    """轮询事件，可选地顺带处理确认卡片。

    Args:
        state: 演练上下文。
        budget: 本轮最长等待秒数。
        after: 只统计严格晚于该序号的 turn_done。
        handle_cards: 是否在等待期间处理确认卡片。

    Returns:
        ``(新游标, 本轮是否结束, 本次确认张数)``。
    """
    deadline = time.time() + budget
    cursor = after
    confirmed_total = 0
    while time.time() < deadline:
        code, body = http_json(
            "GET",
            f"{state['base']}/api/sessions/{state['session_id']}"
            f"/history?after_seq={cursor}",
            headers=state["auth"],
        )
        if code == 200 and isinstance(body, dict):
            for ev in body.get("events", []):
                cursor = max(cursor, ev.get("seq", 0))
                _record_event(state, ev, after)
                if handle_cards:
                    confirmed_total += _handle_cards(state)
            state["cursor"] = cursor
            if _turn_done_after(state, after):
                return cursor, True, confirmed_total
        if handle_cards:
            confirmed_total += _handle_cards(state)
        time.sleep(1.5)
    return cursor, False, confirmed_total


def _record_event(state: dict, ev: dict, after: int) -> None:
    """把一条事件计入报告（tool_call / artifact / gate 等）。"""
    report = state["report"]
    kind = ev.get("type", "unknown")
    seen = report.setdefault("events_seen", {})
    seen[kind] = seen.get(kind, 0) + 1
    payload = ev.get("payload") or {}
    if kind == "tool_call" and ev.get("seq", 0) > after:
        name = payload.get("name")
        report.setdefault("tool_calls", []).append(name)
        print(f"[B] tool_call -> {name}", flush=True)
    elif kind == "tool_result":
        report.setdefault("tool_results", []).append(
            json.dumps(payload, ensure_ascii=False)[:400])
    elif kind == "artifact":
        state.setdefault("artifacts", []).append(payload)
        print(f"[B] artifact -> {payload}", flush=True)
    elif kind == "turn_done":
        state.setdefault("turn_done_seqs", []).append(ev.get("seq", 0))
        print("[B] turn_done", flush=True)
    elif kind == "gate_blocked":
        print(f"[B] gate_blocked -> {payload.get('tool_name')}", flush=True)


def _turn_done_after(state: dict, after: int) -> bool:
    """判断是否已记录到晚于 after 的本轮结束事件。"""
    return any(
        seq > after
        for seq in state.setdefault("turn_done_seqs", [])
    )


def run_browser_flow(state: dict) -> None:
    """同步 playwright 流程：登录→进入已有会话→上传→驱动写入→确认→产物。"""
    from playwright.sync_api import sync_playwright  # noqa: F401 - 文档用

    page = state["page"]
    report = state["report"]
    base = state["base"]

    page.goto(f"{base}/", wait_until="domcontentloaded")
    page.wait_for_selector("#login-user", timeout=30000)
    page.fill("#login-user", LOGIN_USER)
    page.fill("#login-pass", LOGIN_PASS)
    page.click("#login-btn")
    if not wait_for(lambda: page.is_visible("#view-app"), 60):
        report["fatal"] = "登录后未进入主视图"
        shot(page, "B01_login_failed", report)
        return
    report["login_ok"] = True

    # 后端已建好会话（授权激活在其创建时完成），页面只需选中它
    if not wait_for(lambda: page.locator("#session-list .session-item").count() > 0,
                    60):
        page.click("#btn-new-session")
        if not wait_for(
            lambda: page.locator("#session-list .session-item").count() > 0, 120
        ):
            report["fatal"] = "会话列表为空"
            shot(page, "B03_no_session", report)
            return
    state["session_id"] = state.get("api_session_id") or ""
    if not state["session_id"]:
        report["fatal"] = "无法确定页面会话 id，事件轮无从进行"
        return
    target = f"#session-list .session-item[data-id='{state['session_id']}']"
    if not wait_for(lambda: page.locator(target).count() > 0, 60):
        report["fatal"] = f"页面上找不到会话 {state['session_id']}"
        shot(page, "B03_no_session", report)
        return
    # 会话是由后端预先建的，页面需点「打开」才把它置为活动会话
    page.locator(target).get_by_role("button", name="打开").click()
    if not wait_for(lambda: page.evaluate(
        "() => !!document.querySelector('.session-item.active')"), 30):
        report["session_open_warning"] = "点开后未见 active 标记，继续尝试"
    report["session_id"] = state["session_id"]

    # 写租约：复用页面自己的 holder（app.js 为 ES 模块，holderId 不在 window 上，
    # 因此直接读写它使用的 sessionStorage 键）
    holder = page.evaluate(
        "() => sessionStorage.getItem('webchat_holder') || ''") or ""
    if not holder:
        holder = f"drill-{int(time.time())}"
    page.evaluate(
        "(h) => sessionStorage.setItem('webchat_holder', h)", holder)
    state["holder_id"] = holder
    lcode, lbody = http_json(
        "POST", f"{base}/api/sessions/{state['session_id']}/lease",
        body={"holder_id": holder}, headers=state["auth"],
    )
    report["lease"] = {"http": lcode, "body": lbody}
    print(f"[B] 写租约 HTTP {lcode} -> {lbody}", flush=True)
    shot(page, "B04_session_ready", report)

    page.select_option("#upload-channel", "archive_table")
    page.set_input_files("#upload-file", str(TABLE_FILE))
    page.click("#btn-upload")
    # 上传成功后前端会把「建档表格已上传 file_id=…」写进输入框（提示 6s 自消）
    wait_for(lambda: "file_id" in (page.input_value("#msg-input") or ""), 180)
    captured = page.input_value("#msg-input") or ""
    report["upload_echo"] = captured[:300]
    report["upload_notice"] = notice_text(page)[:300]
    report["upload_ok"] = "file_id" in captured
    print(f"[B] 上传回执 -> {captured[:200] or '(空)'}", flush=True)
    print(f"[B] 上传提示 -> {report['upload_notice'][:200] or '(空)'}", flush=True)
    shot(page, "B05_uploaded", report)

    prompt = BASE_PROMPT
    if report["upload_ok"]:
        prompt = f"{captured}\n{BASE_PROMPT}"  # 把 file_id 引用一并交给模型
    _send_message(state, prompt)
    report["send_notice"] = notice_text(page)[:300]

    # 驱动「确认 → 重试执行」：门禁在 deny 后模型会收尾本轮，
    # 因此确认后必须再发一条消息驱动它重试，否则只有卡片没有执行。
    cursor = state.get("cursor", 0)
    for attempt in range(4):
        cursor, done, _ = _watch(state, TIMEOUT_CARD, cursor)
        _handle_cards(state)
        cursor, done, _ = _watch(state, 30, cursor)
        if report.get("confirmations", 0) > 0 and not _wrote_executed(state):
            print(f"[B] 第 {attempt + 1} 次追发消息驱动重试执行", flush=True)
            _send_message(state, FOLLOWUP_TEXT)
            cursor, done, _ = _watch(state, TIMEOUT_TURN, cursor)
        if _wrote_executed(state):
            break
        if done and report.get("confirmations", 0) == 0:
            report.setdefault("stall", []).append(
                f"第 {attempt + 1} 轮无任何确认卡片且本轮已结束")
            break

    # 产物驱动：要求模型把报告写进 xlpa-output/，turn 收尾时被登记为
    # artifact 事件，页面出现下载按钮后由 _try_download_artifact 点击验证
    print("[B] 追发产物驱动消息（报告写入 xlpa-output）", flush=True)
    _send_message(state, ARTIFACT_TEXT)
    cursor, _, _ = _watch(state, TIMEOUT_TURN, cursor)

    shot(page, "B08_final_messages", report)
    _capture_history(state)
    _try_download_artifact(state)


def _wrote_executed(state: dict) -> bool:
    """从事件流判断写入是否已真正执行（出现 tool_result 或回读查询）。

    实测：grant 放行轮不会产生 tool_result 事件（adapter 未把 SDK UserMessage
    工具结果归一化进事件流），因此把「回读工具已被调用」视为执行完成的
    次级信号；最终写入事实以 /mcp 独立回读为准。
    """
    report = state["report"]
    if report.get("events_seen", {}).get("tool_result", 0) > 0:
        return True
    return any(
        name and name.endswith("get_classify_list")
        for name in report.get("tool_calls", [])
    )


def _capture_history(state: dict) -> None:
    """把最终文本与事件计数落进报告（脱敏后由调用方统一 scrub）。"""
    report = state["report"]
    base = state["base"]
    auth = state["auth"]
    sid = state["session_id"]
    code, body = http_json(
        "GET", f"{base}/api/sessions/{sid}/history?after_seq=0", headers=auth,
    )
    if code != 200 or not isinstance(body, dict):
        report["history_error"] = body
        return
    texts = []
    for ev in body.get("events", []):
        payload = ev.get("payload") or {}
        # 助手文本不带 role；带 role=user 的是我方消息回显
        if ev.get("type") == "text_delta" and payload.get("role") != "user":
            texts.append(payload.get("text", ""))
    report["assistant_text"] = "".join(texts)[-4000:]
    report["event_total"] = len(body.get("events", []))


def _try_download_artifact(state: dict) -> None:
    """若会话产生了登记产物，走一次性 grant 代理下载并校验 URL 无凭据。"""
    report = state["report"]
    page = state["page"]
    buttons = page.locator("button:has-text('下载'), a:has-text('下载')")
    report["artifact_buttons"] = buttons.count()
    if buttons.count() == 0:
        report["artifact_download"] = "本轮无产物下载按钮"
        return
    with page.expect_download(timeout=60000) as dl:
        buttons.first.click()
    item = dl.value
    path = SHOTS / f"artifact_{item.suggested_filename}"
    path.parent.mkdir(parents=True, exist_ok=True)
    item.save_as(path)
    report["artifact_download"] = {
        "name": item.suggested_filename,
        "saved_to": str(path.relative_to(ROOT)),
        "size": path.stat().st_size,
        "url_has_token": bool(
            [t for t in ("token", "grant", "Authorization")
             if t in (item.url or "")]),
    }
    shot(state["page"], "B09_artifact_downloaded", report)


async def platform_readback(report: dict) -> dict | None:
    """独立 /mcp 回读：确认 AC 标记大类是否真的写入，并返回其 id。"""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    token = os.environ.get("MCP_AUTH_TOKEN", "")
    url = f"http://127.0.0.1:{MCP_PORT}/mcp"
    async with streamablehttp_client(
        url, headers={"Authorization": f"Bearer {token}"}
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await session.call_tool("login", {"phoneNum": PHONE, "code": CODE})
            found = await _find_classify(session, report)
            if found is not None:
                return found
            await asyncio.sleep(5)
            return await _find_classify(session, report)


async def _find_classify(session: Any, report: dict) -> dict | None:
    """按标记名精确查找大类行。"""
    listing = unwrap(await session.call_tool(
        "get_classify_list", {"sysName": AC_MARK}))
    report["readback"] = listing
    rows = ((listing or {}).get("data") or {}).get("rows") or []
    for row in rows:
        if row.get("sysName") == AC_MARK:
            return row
    return None


async def platform_cleanup(row: dict | None, report: dict) -> None:
    """收尾删除：由脚本执行，不依赖模型行为；删后再回读确认。"""
    if row is None:
        report["cleanup"] = "未写入成功，无需删除"
        return
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    token = os.environ.get("MCP_AUTH_TOKEN", "")
    url = f"http://127.0.0.1:{MCP_PORT}/mcp"
    async with streamablehttp_client(
        url, headers={"Authorization": f"Bearer {token}"}
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await session.call_tool("login", {"phoneNum": PHONE, "code": CODE})
            deleted = unwrap(await session.call_tool("del_classify", {
                "classify_id": int(row["id"]), "sysName": AC_MARK,
            }))
            report["cleanup_delete_result"] = deleted
            remain = await _find_classify(session, {})
            report["cleanup_verified"] = remain is None
            print(f"[B] 删除回读校验 -> {report['cleanup_verified']}", flush=True)


def phase_b() -> int:
    """执行 Phase B 浏览器演练（同步主流程，/mcp 阶段单独跑事件循环）。"""
    report: dict[str, Any] = {"ac_mark": AC_MARK}
    load_env_file(ROOT / "_ac_local.env")
    load_env_file(ROOT / "mcp_server" / ".env")
    RUN_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[B] 目标可删大类名 = {AC_MARK}", flush=True)
    procs = start_servers()
    base = f"http://127.0.0.1:{WEBCHAT_PORT}"
    state: dict[str, Any] = {"report": report, "base": base, "cursor": 0}
    exe = browser_exe()
    if not exe:
        report["fatal"] = "未找到可复用 chromium（PCA_TEST_BROWSER 也未设置）"
        stop_servers(procs)
        _dump(report)
        return 1

    # 先走后端拿票据与会话，供事件轮询与产物下载复用
    code, login_resp = http_json(
        "POST", f"{base}/api/auth/login",
        body={"username": LOGIN_USER, "password": LOGIN_PASS},
    )
    if code != 200 or not isinstance(login_resp, dict):
        report["fatal"] = f"后端登录失败 HTTP {code}: {login_resp}"
        stop_servers(procs)
        _dump(report)
        return 1
    auth = {"Authorization": f"Bearer {login_resp['session_token']}"}
    code, sess = http_json("POST", f"{base}/api/sessions", headers=auth)
    if code != 200 or not isinstance(sess, dict):
        report["fatal"] = f"建会话失败 HTTP {code}: {sess}"
        stop_servers(procs)
        _dump(report)
        return 1
    state["api_session_id"] = sess["session_id"]
    state["session_id"] = sess["session_id"]
    state["auth"] = auth
    print(f"[B] 会话 {sess['session_id']} 就绪（授权激活已通过）", flush=True)

    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                executable_path=exe, headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            try:
                context = browser.new_context(
                    viewport={"width": 1280, "height": 900}, locale="zh-CN",
                )
                page = context.new_page()
                page.on(
                    "pageerror",
                    lambda exc: state["report"].setdefault(
                        "page_errors", []).append(str(exc)[:300]),
                )
                state["page"] = page
                run_browser_flow(state)
            finally:
                try:
                    browser.close()
                except Exception:  # noqa: BLE001 - 收尾关闭失败不掩盖原因
                    pass
    except Exception as exc:  # noqa: BLE001 - 保留已采集证据
        report.setdefault("browser_errors", []).append(str(exc))

    # 浏览器已关，此处可以干净地起独立事件循环跑 /mcp
    row = asyncio.run(platform_readback(report))
    report["write_executed"] = row is not None
    report["written_row"] = row
    asyncio.run(platform_cleanup(row, report))

    stop_servers(procs)
    ok = bool(report.get("write_executed")) and bool(
        report.get("cleanup_verified"))
    report["pass"] = ok
    _dump(report)
    print(f"[B] {'PASS' if ok else 'FAIL'} -> {REPORT_FILE}", flush=True)
    return 0 if ok else 1


def _dump(report: dict) -> None:
    """落盘报告（递归剔除凭据字段）。"""
    from _ac1_probe import scrub

    REPORT_FILE.write_text(
        json.dumps(scrub(report), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def main() -> int:
    """入口：运行 Phase B 演练。"""
    return phase_b()


if __name__ == "__main__":
    sys.exit(main())
