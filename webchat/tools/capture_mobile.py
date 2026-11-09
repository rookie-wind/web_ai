"""移动端 375px 确认闭环截图（AC 演练取证脚本）。

用无头 Chromium 复现 375×812 窄屏，走通「登录 → 新建会话 →
发『请写入移动测试』→ 确认卡片出现 → 点确认写入」并落两张截图。
复用已有浏览器：优先读环境变量 PCA_TEST_BROWSER 指定的可执行文件，
缺省回落到 Playwright 自带 chromium（不做浏览器下载）。

用法（webchat venv，需已 pip install -r requirements-dev.txt）：
    set PCA_TEST_BROWSER=<chrome.exe 绝对路径>
    set PCA_TEST_USER=<登录用户名>
    set PCA_TEST_PASS=<登录口令>
    python webchat/tools/capture_mobile.py --base http://127.0.0.1:8811

凭据仅经环境变量/命令行参数传入，不落盘也不写入脚本默认值。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT_DIR = Path(__file__).resolve().parents[2] / "validation" / "public-access-hardening"
VIEWPORT = {"width": 375, "height": 812}


def _executable_path() -> str | None:
    """按 PCA_TEST_BROWSER 约定取已装浏览器路径；缺省交给 Playwright。"""
    raw = os.environ.get("PCA_TEST_BROWSER", "").strip()
    return raw or None


def run(base: str, user: str, password: str) -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    shot_before = OUT_DIR / "44_mobile_375.png"
    shot_after = OUT_DIR / "44_mobile_confirmed.png"
    with sync_playwright() as p:
        launch_kw = {"headless": True}
        exe = _executable_path()
        if exe:
            launch_kw["executable_path"] = exe
        browser = p.chromium.launch(**launch_kw)
        ctx = browser.new_context(viewport=VIEWPORT, device_scale_factor=2)
        page = ctx.new_page()
        page.goto(f"{base}/", wait_until="networkidle")

        page.fill("#login-user", user)
        page.fill("#login-pass", password)
        page.click("#login-btn")
        page.wait_for_selector("#view-app:not(.hidden)", timeout=15000)

        # 窄屏下侧栏移出画布，先点汉堡菜单展开，再点新建会话
        page.click("#btn-sessions")
        page.wait_for_timeout(250)
        page.click("#btn-new-session")
        page.wait_for_selector("#session-list .session-item", timeout=15000)

        page.fill("#msg-input", "请写入移动测试")
        page.press("#msg-input", "Enter")
        page.wait_for_selector(".card-gate", timeout=20000)
        page.wait_for_timeout(300)
        page.screenshot(path=str(shot_before), full_page=True)

        # 确认写入按钮（卡片内 primary 按钮）
        card = page.locator(".card-gate").last
        card.get_by_role("button", name="确认写入").click()
        page.wait_for_function(
            "() => document.querySelector('.card-gate h3') &&"
            " [...document.querySelectorAll('.card-gate h3')]"
            ".some(h => h.textContent.includes('已确认写入'))",
            timeout=20000,
        )
        page.wait_for_timeout(300)
        page.screenshot(path=str(shot_after), full_page=True)

        ctx.close()
        browser.close()

    ok = shot_before.exists() and shot_after.exists()
    print(f"[capture] before={shot_before} exists={shot_before.exists()}")
    print(f"[capture] after={shot_after} exists={shot_after.exists()}")
    print(f"[capture] viewport={VIEWPORT} RESULT={'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="移动端 375px 确认闭环截图")
    parser.add_argument("--base", default="http://127.0.0.1:8811")
    parser.add_argument(
        "--user",
        default=os.environ.get("PCA_TEST_USER", "demo"),
        help="登录用户名（默认取 PCA_TEST_USER，回落 demo 仅适用冒烟桩）",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("PCA_TEST_PASS", ""),
        help="登录口令（默认取 PCA_TEST_PASS；真实演练必填，不给默认值）",
    )
    args = parser.parse_args()
    if not args.password:
        print("[capture] 缺少登录口令：请设 PCA_TEST_PASS 或传 --password", file=sys.stderr)
        return 2
    return run(args.base, args.user, args.password)


if __name__ == "__main__":
    sys.exit(main())
