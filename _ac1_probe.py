"""AC-1 执行分支演练 · Phase A：配对实例 + 建档管线空跑（零写入）。

覆盖动作：起 mcp_server/webchat 配对实例 → webchat 登录/建会话/租约 →
建档表格经 archive_table 通道上传（只验管线是否接受该表）→ /mcp 侧
只读发现（tools/list、login 绑定、大类/品牌/型号现状）。

本阶段 MUST NOT 向生产平台写入任何业务数据。
凭据经 _ac_local.env / mcp_server/.env 注入，本文件不落任何密钥。
"""

from __future__ import annotations

__all__ = ["main"]

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
MCP_DIR = ROOT / "mcp_server"
WEBCHAT_DIR = ROOT / "webchat"
ENV_FILE = ROOT / "_ac_local.env"
TABLE_FILE = ROOT / "设备建档模板_20260922153429_fixed.xlsx"
RUN_DIR = ROOT / "_ac1_run"
REPORT_FILE = RUN_DIR / "phaseA.json"

MCP_PORT = 8772
WEBCHAT_PORT = 8808

MCP_PY = ROOT / ".venv" / "Scripts" / "python.exe"
WEBCHAT_PY = WEBCHAT_DIR / ".venv" / "Scripts" / "python.exe"

PHONE = os.environ.get("PCA_AC_PHONE", "13912986342")
CODE = os.environ.get("PCA_AC_CODE", "9413")

DISCOVERY_TOOLS = (
    "login",
    "get_classify_list",
    "add_classify",
    "del_classify",
    "get_device_type_list",
    "get_brand_list",
    "add_brand",
    "del_brand",
    "get_model_list",
    "add_model",
    "del_model",
)


def load_env_file(path: Path) -> None:
    """把 KEY=VALUE 文件并入 os.environ（已存在的键不覆盖）。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, _, value = text.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def http_json(
    method: str,
    url: str,
    *,
    body: dict | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> tuple[int, Any]:
    """极简 HTTP JSON 调用，返回 (状态码, 解析后的 JSON 或原始文本)。"""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            code = resp.status
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        code = exc.code
    except urllib.error.URLError as exc:
        return -1, f"URLError: {exc}"
    try:
        return code, json.loads(raw)
    except json.JSONDecodeError:
        return code, raw


def wait_port(port: int, proc: subprocess.Popen, timeout: float = 90.0) -> bool:
    """轮询端口直至可连通；进程提前退出则立即失败。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        with socket.socket() as sock:
            sock.settimeout(0.6)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.4)
    return False


def start_servers() -> tuple[subprocess.Popen, subprocess.Popen]:
    """同进程树启动 mcp_server 与 webchat（跨命令 loopback 不共享）。

    服务日志落 _ac1_run/，就绪失败时可回看 mcp.log。
    """
    RUN_DIR.mkdir(exist_ok=True)
    env = os.environ.copy()
    env.update({"MCP_HOST": "127.0.0.1", "MCP_PORT": str(MCP_PORT),
                "MCP_PUBLIC_MODE": "0"})
    mcp_log = (RUN_DIR / "mcp.log").open("w", encoding="utf-8", errors="replace")
    mcp = subprocess.Popen(
        [str(MCP_PY), "server.py"], cwd=str(MCP_DIR), env=env,
        stdout=mcp_log, stderr=subprocess.STDOUT, text=True,
    )
    if not wait_port(MCP_PORT, mcp):
        mcp.kill()
        mcp_log.close()
        raise RuntimeError(f"mcp_server 未在 :{MCP_PORT} 就绪，见 _ac1_run/mcp.log")

    wenv = os.environ.copy()
    wenv.update({
        # 监听全部网卡，使局域网内其它机器可访问 webchat（0.0.0.0）；
        # 若仅需本机演练可改回 127.0.0.1。webchat 走账号口令鉴权。
        "WEBCHAT_HOST": "0.0.0.0",
        "WEBCHAT_PORT": str(WEBCHAT_PORT),
        "WEBCHAT_MINT_URL": f"http://127.0.0.1:{MCP_PORT}",
        "WEBCHAT_MAX_SESSIONS_PER_USER": "8",
        "WEBCHAT_MAX_INSTANCES": "8",
        "WEBCHAT_AGENT_MODEL": os.environ.get("WEBCHAT_AGENT_MODEL",
                                              "Qwen3.8-Flash"),
    })
    wc_log = (RUN_DIR / "webchat.log").open("w", encoding="utf-8", errors="replace")
    web = subprocess.Popen(
        [str(WEBCHAT_PY), "-m", "webchat"], cwd=str(WEBCHAT_DIR), env=wenv,
        stdout=wc_log, stderr=subprocess.STDOUT, text=True,
    )
    if not wait_port(WEBCHAT_PORT, web):
        mcp.kill()
        web.kill()
        mcp_log.close()
        wc_log.close()
        raise RuntimeError(f"webchat 未在 :{WEBCHAT_PORT} 就绪，见 _ac1_run/webchat.log")
    return mcp, web


def stop_servers(procs: tuple[subprocess.Popen, subprocess.Popen]) -> None:
    """收尾关闭两个服务进程。"""
    for proc in procs:
        proc.terminate()
    for proc in procs:
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


def unwrap(result: Any) -> Any:
    """把 CallToolResult 的文本块归一为 Python 对象。"""
    texts = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            texts.append(text)
    raw = "\n".join(texts)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def upload_table(base: str, auth: dict, sid: str) -> Any:
    """multipart 上传建档表格（archive_table 通道，代理换 file_id）。"""
    boundary = "----ac1probeboundary"
    payload = TABLE_FILE.read_bytes()
    parts = [
        (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"channel\""
            "\r\n\r\narchive_table\r\n"
        ).encode("utf-8"),
        (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"{TABLE_FILE.name}\"\r\n"
            "Content-Type: application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet\r\n\r\n"
        ).encode("utf-8"),
        payload,
        f"\r\n--{boundary}--\r\n".encode("utf-8"),
    ]
    req = urllib.request.Request(
        f"{base}/api/sessions/{sid}/artifacts/upload",
        data=b"".join(parts), method="POST",
    )
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    for key, value in auth.items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            raw = resp.read().decode("utf-8", "replace")
            try:
                return {"http": resp.status, "body": json.loads(raw)}
            except json.JSONDecodeError:
                return {"http": resp.status, "body": raw}
    except urllib.error.HTTPError as exc:
        return {"http": exc.code,
                "body": exc.read().decode("utf-8", "replace")[:800]}
    except urllib.error.URLError as exc:
        return {"http": -1, "body": f"URLError: {exc}"}


def scrub(value: Any) -> Any:
    """递归剔掉报告里可能出现的凭据字段（token / Authorization）。"""
    if isinstance(value, dict):
        return {
            k: scrub(v)
            for k, v in value.items()
            if k.lower() not in {"auth", "token", "authorization",
                                  "mcp_token", "password", "code"}
        }
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


async def run_webchat_steps(base: str, report: dict) -> dict | None:
    """webchat 侧只读/无害步骤：登录、建会话、取租约、建档上传空跑。"""
    code, login_resp = http_json(
        "POST", f"{base}/api/auth/login",
        body={"username": "admin", "password": os.environ.get(
            "PCA_AC_WEBCHAT_PASS", "admin")},
    )
    print(f"[A] webchat 登录 HTTP {code}", flush=True)
    if code != 200 or not isinstance(login_resp, dict):
        report["login"] = {"http": code, "body": login_resp}
        return None
    auth = {"Authorization": f"Bearer {login_resp['session_token']}"}

    code, sess = http_json("POST", f"{base}/api/sessions", headers=auth)
    print(f"[A] 建会话 HTTP {code} -> {sess}", flush=True)
    if code != 200 or not isinstance(sess, dict):
        report["create_session"] = {"http": code, "body": sess}
        return None
    sid = sess["session_id"]

    holder = "probe-holder-01"
    lcode, lbody = http_json(
        "POST", f"{base}/api/sessions/{sid}/lease",
        body={"holder_id": holder}, headers=auth,
    )
    print(f"[A] 租约 HTTP {lcode} -> {lbody}", flush=True)

    upload = upload_table(base, auth, sid)
    report["upload_table"] = upload
    print(f"[A] 建档上传 -> {json.dumps(upload, ensure_ascii=False)[:600]}",
          flush=True)
    return {"session_id": sid, "holder_id": holder, "auth": auth}


async def run_discovery(report: dict) -> None:
    """/mcp 只读发现：工具清单与 schema、login 绑定、现有大类/品牌/型号。"""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    token = os.environ.get("MCP_AUTH_TOKEN", "")
    url = f"http://127.0.0.1:{MCP_PORT}/mcp"
    async with streamablehttp_client(
        url, headers={"Authorization": f"Bearer {token}"}
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listing = await session.list_tools()
            report["tool_count"] = len(listing.tools)
            report["schemas"] = {
                t.name: t.inputSchema
                for t in listing.tools
                if t.name in DISCOVERY_TOOLS
            }
            print(f"[A] tools/list = {len(listing.tools)}", flush=True)

            bound = unwrap(await session.call_tool("login", {
                "phoneNum": PHONE, "code": CODE,
            }))
            report["login_bind"] = bound
            print(f"[A] login 绑定 -> {json.dumps(bound, ensure_ascii=False)[:300]}"
                  , flush=True)

            classes = unwrap(await session.call_tool("get_classify_list", {}))
            report["classify_list"] = classes
            text = json.dumps(classes, ensure_ascii=False)
            report["classify_has_ac1_mark"] = "AC1可删" in text
            print(f"[A] 大类响应 {len(text)} 字符，含 AC1可删 标记: "
                  f"{report['classify_has_ac1_mark']}", flush=True)
            print(f"[A] 大类片段 -> {text[:600]}", flush=True)

            brands = unwrap(await session.call_tool("get_brand_list", {}))
            report["brand_list"] = brands
            print(f"[A] 品牌片段 -> "
                  f"{json.dumps(brands, ensure_ascii=False)[:400]}", flush=True)


async def phase_a() -> int:
    """执行 Phase A 全量探测并落盘报告。"""
    report: dict[str, Any] = {}
    load_env_file(ENV_FILE)
    load_env_file(MCP_DIR / ".env")

    print("[A] 启动配对实例 ...", flush=True)
    procs = start_servers()
    base = f"http://127.0.0.1:{WEBCHAT_PORT}"
    report["ports"] = {"mcp": MCP_PORT, "webchat": WEBCHAT_PORT, "base": base}
    try:
        web = await run_webchat_steps(base, report)
        report["webchat"] = {
            k: v for k, v in (web or {}).items() if k != "auth"
        }
        await run_discovery(report)
        code, me = http_json(
            "GET", f"{base}/api/auth/me",
            headers=(web or {}).get("auth", {}),
        )
        report["auth_me"] = {"http": code, "body": me}
        report["ok"] = web is not None
        return 0 if report["ok"] else 1
    finally:
        REPORT_FILE.write_text(
            json.dumps(scrub(report), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"[A] 报告落盘 -> {REPORT_FILE}", flush=True)
        stop_servers(procs)


def main() -> int:
    """入口：运行 Phase A 探测。"""
    return asyncio.run(phase_a())


if __name__ == "__main__":
    sys.exit(main())
