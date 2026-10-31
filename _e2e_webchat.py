"""真实 webchat 链路端到端探测（不含前端页面，用 HTTP API 模拟前端）。

目的：钉死 V-L——登录代登是否成功、mint 建会话是否成功、agent 调用云端
只读工具是否被「需先 login」阻塞。全程只发起**只读**任务，不写入任何数据。

凭据只用于请求头，不回显 token 明文。
"""

from __future__ import annotations

import json
import os
import time

import httpx

BASE = os.environ.get("WEBCHAT_PROBE_BASE", "http://127.0.0.1:8800")
HOLDER = "probe-holder-1"
USERNAME = os.environ.get("WEBCHAT_PROBE_USER", "admin")
PASSWORD = os.environ.get("WEBCHAT_PROBE_PASSWORD", "admin")
PROMPT = (
    "请调用云端只读查询工具，列出设备类型/大类清单里的前 5 个条目"
    "（编号和名称即可）。只做查询，绝对不要新建、修改或删除任何数据。"
)


def show(title: str, ok: bool, extra: str = "") -> None:
    print(f"  [{'OK ' if ok else 'FAIL'}] {title}" + (f"  {extra}" if extra else ""))


def main() -> int:
    c = httpx.Client(timeout=60.0)

    print("=== 1. POST /api/auth/login（会真打平台代登 phone+code）===")
    r = c.post(f"{BASE}/api/auth/login",
               json={"username": USERNAME, "password": PASSWORD})
    if r.status_code != 200:
        show("登录", False, f"HTTP {r.status_code} body={r.text[:200]}")
        print("  ⇒ 登录失败，链路无法继续（多为平台凭据/验证码失效）")
        return 1
    login = r.json()
    st = login["session_token"]
    show("登录", True,
         f"is_super={login.get('is_super')} 票据长度={len(st)}（值不回显）")

    auth = {"Authorization": f"Bearer {st}"}

    print("\n=== 2. POST /api/sessions（内部走 mint → mcp_server）===")
    r = c.post(f"{BASE}/api/sessions", headers=auth)
    if r.status_code != 200:
        show("建会话", False, f"HTTP {r.status_code} body={r.text[:300]}")
        return 1
    sid = r.json()["session_id"]
    show("建会话", True, f"session_id={sid}")

    print("\n=== 3. POST /api/sessions/{id}/lease（写租约）===")
    r = c.post(f"{BASE}/api/sessions/{sid}/lease", headers=auth,
               json={"holder_id": HOLDER})
    show("租约", r.status_code == 200,
         f"HTTP {r.status_code} {r.text[:160] if r.status_code != 200 else ''}")
    if r.status_code != 200:
        return 1

    print("\n=== 4. POST /api/sessions/{id}/messages（只读任务）===")
    r = c.post(f"{BASE}/api/sessions/{sid}/messages",
               headers={**auth, "x-holder-id": HOLDER}, json={"text": PROMPT})
    show("发消息", r.status_code == 200,
         f"HTTP {r.status_code} {r.text[:200] if r.status_code != 200 else ''}")
    if r.status_code != 200:
        return 1

    print("\n=== 5. GET /api/sessions/{id}/events（SSE 消费到 turn_done）===")
    tool_calls: list[str] = []
    texts: list[str] = []
    seen_types: dict[str, int] = {}
    done = False
    deadline = time.time() + 240

    with c.stream("GET", f"{BASE}/api/sessions/{sid}/events", headers=auth) as resp:
        print(f"  events HTTP {resp.status_code} content-type={resp.headers.get('content-type')}")
        buf = ""
        for raw in resp.iter_text():
            if time.time() > deadline:
                print("  ⇒ 超时退出（agent 未在 240s 内产出 turn_done）")
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
                    seen_types[t] = seen_types.get(t, 0) + 1
                    p = ev.get("payload", {})
                    if t == "tool_call":
                        tool_calls.append(str(p.get("name") or p.get("tool") or p))
                        print(f"    tool_call → {p.get('name') or p}")
                    elif t == "tool_result":
                        s = json.dumps(p, ensure_ascii=False)
                        print(f"    tool_result ← {s[:220]}")
                    elif t == "text_delta":
                        seg = p.get("text") or ""
                        if p.get("role") != "user":
                            texts.append(seg)
                    elif t in ("ask_user", "gate_blocked", "error"):
                        print(f"    {t} → {json.dumps(p, ensure_ascii=False)[:260]}")
                    elif t == "turn_done":
                        print(f"    turn_done → {json.dumps(p, ensure_ascii=False)[:200]}")
                        done = True
            if done:
                break

    print("\n=== 6. 判定汇总 ===")
    print(f"  事件类型分布: {seen_types}")
    print(f"  工具调用 {len(tool_calls)} 次: {tool_calls[:12]}")
    full = "".join(texts)
    print(f"  agent 文本长度: {len(full)}")
    if full:
        print("  ── 文本节选（前 900 字）──")
        print("  " + full[:900].replace("\n", "\n  "))
        low = full.lower()
        for kw in ("验证码", "登录", "login", "权限", "被拒", "无法"):
            if kw in low or kw in full:
                print(f"  ⚠ 文本含关键词「{kw}」")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
