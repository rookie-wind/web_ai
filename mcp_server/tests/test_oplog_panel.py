"""OPERATION TRACE 面板行为浏览器测试。

验证：客户端复判不被服务端 SUCCESS 掩盖、行标识为分路号、批次聚合与重试去重、
假成功（rtnCode≠0/ACCEPTED）判为 ✗，以及脚本无 JS 报错。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_HTML = (
    Path(__file__).resolve().parent.parent / "static" / "access.html"
).read_text(encoding="utf-8")


def _client() -> dict:
    return {
        "id": "qoder", "name": "Qoder", "ideName": "Qoder",
        "configPath": "x/config.json", "configLevel": "user",
        "rootKey": "mcpServers", "urlKey": "url", "transport": {},
    }


def _entry(road: int, device: str, rtn, ts, valid, state: str,
           dur: int, started: str, server_status: str = "SUCCESS") -> dict:
    """构造一条召测操作日志条目。"""
    return {
        "entry_id": "op" + str(road) + started[-6:-3],
        "seq": int(started[-6:-3] or road),
        "trace_id": "trc1", "tool": "edge_call_monitor_debug",
        "status": server_status, "code": state,
        "started_at": "2026-10-21T07:" + started + "+00:00",
        "duration_ms": dur,
        "result_summary": {
            "request_summary": {"deviceId": device, "roadNo": road, "itemId": "31800006"},
            "rtnCode": rtn, "transport_stage": ts, "monitor_valid": valid,
            "request_sent": True, "stage_state": state, "report_id": "rpt_test",
            "dispatches": [{"path": "/callDeviceParam", "state": "DISPATCHED",
                            "payload_digest": "abc", "payload": {"deviceId": device,
                            "dataItem": {"itemId": "31800006", "annexInfo": {"roadNo": road}}}}],
            "data": {"dataItem": {"itemBody": [{"roadNo": road, "dataTime": "2026-10-21 15:06:00", "item": 220.1}]}},
        },
    }


@pytest.fixture
def oplog_page() -> "tuple":
    """离线 Chromium，不触网、不用真实凭证。"""
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(
            headless=True, channel="chromium", executable_path=os.getenv("PCA_TEST_BROWSER"),
        )
        context = browser.new_context(viewport={"width": 1366, "height": 900})
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        yield page, errors
        context.close()
        browser.close()


def test_oplog_panel_judges_and_groups(oplog_page) -> None:
    """面板按业务标识展示、客户端复判状态、聚合与重试去重。"""
    page, errors = oplog_page
    logs = [
        _entry(6, "LV-04-E", 0, "COMPLETE", True, "SUCCEEDED", 2415, "06:00"),
        _entry(1, "ACB-206249", 0, "COMPLETE", True, "SUCCEEDED", 12872, "07:00"),
        # 分路6 重试：HTTP200 但 rtnCode=40000（ACCEPTED），服务端仍标 SUCCESS
        _entry(6, "LV-04-E", 40000, "ACCEPTED", False, "SUCCEEDED", 3000, "09:00"),
    ]

    def handler(route):
        url = route.request.url
        if url.endswith("/api/access-info"):
            route.fulfill(json={
                "token": "tk-panel", "baseUrl": "http://showcase.test",
                "source": "1.2.3.4", "clients": [_client()],
            })
        elif "/api/logs" in url:
            route.fulfill(json={
                "ok": True, "trace_id": "trc1", "next_cursor": "3",
                "count": len(logs), "logs": logs,
            })
        elif "api" not in url:
            route.fulfill(content_type="text/html", body=_HTML)
        else:
            route.abort()

    page.route("**/*", handler)
    page.goto("http://showcase.test/access")
    page.wait_for_selector(".oplog-group", timeout=5000)

    assert not errors, errors

    # 组默认折叠：展开后才逐行可见
    page.locator(".oplog-group > summary").first.click()
    rows_text = page.locator("#oplog-list").inner_text()

    kpi = page.locator("#oplog-kpi").inner_text()
    assert "2 路" in kpi and "1 次重试" in kpi
    assert rows_text.count("分路06") >= 1

    # 假成功必须被判为 ✗（fail），且与服务端 SUCCESS 冲突标记 ⚑
    fails = page.locator(".oplog-glyph.g-fail")
    assert fails.count() >= 1
    assert "⚑" in rows_text

    # 展开首行证据层含判据字段与报文
    page.locator(".oplog-entry > summary").first.click()
    detail = page.locator(".oplog-detail").first.inner_text()
    assert "transport_stage" in detail and "monitor_valid" in detail
    assert "请求报文" in detail and "响应报文" in detail
