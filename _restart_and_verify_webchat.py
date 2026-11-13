"""重启 webchat（读取 _ac_local.env 里的 Qwen3.8-Flash）并端到端验证。

流程：
1. 载入 _ac_local.env + mcp_server/.env（密钥经 os.environ 注入，不落盘）
2. 用与 _ac1_probe 相同的环境变量启动 webchat 子进程（模型取 env 值）
3. 等待 :8808 就绪
4. 通过真实 HTTP API 发一条极短消息「你好」，消费 SSE 到 turn_done
5. 判定：回复为正常文本且不含 "credit usage limit" -> 修复生效

前提：调用前已在外部关停旧的 webchat 进程；MCP :8772 保持运行。
"""

from __future__ import annotations

__all__ = ["main"]

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from _ac1_probe import (  # noqa: E402
    ENV_FILE, MCP_DIR, RUN_DIR, WEBCHAT_DIR, WEBCHAT_PY, WEBCHAT_PORT,
    load_env_file, wait_port,
)

import httpx  # noqa: E402

BASE = f"http://127.0.0.1:{WEBCHAT_PORT}"
HOLDER = "verify-holder-01"
PROMPT = "只回复两个字：你好"
CREDIT_HINT = "credit usage limit"
MCP_PORT = 8772


def launch_webchat() -> subprocess.Popen:
    """按 launcher 同款 env 启动 webchat，返回子进程句柄。"""
    load_env_file(ENV_FILE)
    load_env_file(MCP_DIR / ".env")
    model = os.environ.get("WEBCHAT_AGENT_MODEL", "Qwen3.8-Flash")
    print(f"[launch] 生效模型 WEBCHAT_AGENT_MODEL = {model!r}", flush=True)
    wenv = os.environ.copy()
    wenv.update({
        "WEBCHAT_HOST": "0.0.0.0",
        "WEBCHAT_PORT": str(WEBCHAT_PORT),
        "WEBCHAT_MINT_URL": f"http://127.0.0.1:{MCP_PORT}",
        "WEBCHAT_MAX_SESSIONS_PER_USER": "8",
        "WEBCHAT_MAX_INSTANCES": "8",
        "WEBCHAT_AGENT_MODEL": model,
    })
    RUN_DIR.mkdir(exist_ok=True)
    log = (RUN_DIR / "webchat_restart.log").open("w", encoding="utf-8",
                                                 errors="replace")
    proc = subprocess.Popen(
        [str(WEBCHAT_PY), "-m", "webchat"], cwd=str(WEBCHAT_DIR), env=wenv,
        stdout=log, stderr=subprocess.STDOUT, text=True,
    )
    if not wait_port(WEBCHAT_PORT, proc, timeout=90.0):
        proc.kill()
        raise RuntimeError("webchat 未在 :8808 就绪，见 _ac1_run/webchat_restart.log")
    print(f"[launch] webchat 就绪，PID={proc.pid}", flush=True)
    return proc


def chat_once() -> dict:
    """走真实 API 发一条极短消息，返回回复文本与事件分布。"""
    out: dict = {"reply": "", "types": {}, "ok": False, "note": ""}
    c = httpx.Client(timeout=60.0)
    r = c.post(f"{BASE}/api/auth/login",
               json={"username": "admin",
                     "password": os.environ.get("PCA_AC_WEBCHAT_PASS", "admin")})
    if r.status_code != 200:
        out["note"] = f"登录失败 HTTP {r.status_code}"
        return out
    auth = {"Authorization": f"Bearer {r.json()['session_token']}"}

    r = c.post(f"{BASE}/api/sessions", headers=auth)
    if r.status_code != 200:
        out["note"] = f"建会话失败 HTTP {r.status_code} {r.text[:200]}"
        return out
    sid = r.json()["session_id"]

    # 等待后台慢路就绪（异步创建后写路径要求 ready）
    deadline = time.time() + 90
    status_now = "?"
    while time.time() < deadline:
        items = c.get(f"{BASE}/api/sessions", headers=auth).json()["sessions"]
        meta = [x for x in items if x["session_id"] == sid]
        status_now = meta[0].get("status", "?") if meta else "?"
        if status_now == "ready":
            break
        time.sleep(0.5)
    else:
        out["note"] = f"初始化未就绪（status={status_now}）"
        out["init_status"] = status_now
        return out
    out["init_status"] = status_now

    c.post(f"{BASE}/api/sessions/{sid}/lease", headers=auth,
           json={"holder_id": HOLDER})

    r = c.post(f"{BASE}/api/sessions/{sid}/messages",
               headers={**auth, "x-holder-id": HOLDER}, json={"text": PROMPT})
    if r.status_code != 200:
        out["note"] = f"发消息失败 HTTP {r.status_code} {r.text[:200]}"
        return out

    texts: list[str] = []
    done = False
    deadline = time.time() + 180
    with c.stream("GET", f"{BASE}/api/sessions/{sid}/events",
                  headers=auth) as resp:
        buf = ""
        for raw in resp.iter_text():
            if time.time() > deadline:
                out["note"] = "SSE 超时，未等到 turn_done"
                break
            buf += raw
            while "\n\n" in buf:
                frame, buf = buf.split("\n\n", 1)
                for ln in frame.splitlines():
                    if not ln.startswith("data: "):
                        continue
                    try:
                        ev = json.loads(ln[6:])
                    except json.JSONDecodeError:
                        continue
                    t = ev.get("type", "?")
                    out["types"][t] = out["types"].get(t, 0) + 1
                    p = ev.get("payload", {})
                    if t == "text_delta" and p.get("role") != "user":
                        texts.append(p.get("text") or "")
                    elif t == "error":
                        out["note"] = f"error 事件: {json.dumps(p, ensure_ascii=False)[:200]}"
                    elif t == "turn_done":
                        done = True
            if done:
                break
    out["reply"] = "".join(texts).strip()
    out["ok"] = bool(out["reply"]) and CREDIT_HINT not in out["reply"].lower()
    return out


def main() -> int:
    """启动并验证。"""
    proc = launch_webchat()
    res = chat_once()
    print("\n===== 端到端验证 =====", flush=True)
    print(f"  初始化态 : {res.get('init_status', '?')}", flush=True)
    print(f"  事件分布 : {res['types']}", flush=True)
    print(f"  回复文本 : {res['reply'][:200]!r}", flush=True)
    if res["note"]:
        print(f"  备注     : {res['note']}", flush=True)
    print(f"  判定     : {'[OK] 正常出话、无额度报错' if res['ok'] else '[NO] 仍有问题'}",
          flush=True)
    print(f"\n[keep] webchat 由 PID={proc.pid} 持续运行（脚本退出不影响子进程）",
          flush=True)
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
