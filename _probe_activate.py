"""一次性探针：直接调用 webchat 的 call_login_tool，递归展开异常树。"""

from __future__ import annotations

import asyncio

import httpx

from webchat.sdk_runtime.login_activation import call_login_tool

MINT_URL = "http://127.0.0.1:8767/api/mcp-token/mint"
MCP_URL = "http://127.0.0.1:8767/mcp"
MINT_SECRET = "V9WU6xiiMgkTa7-vnu9b8EGri2JXZQrK"
PHONE = "13912986342"
CODE = "9413"


def dump(exc: BaseException, depth: int = 0) -> None:
    pad = "  " * depth
    print(f"{pad}! {type(exc).__name__}: {exc}")
    for sub in getattr(exc, "exceptions", []) or []:
        dump(sub, depth + 1)
    if exc.__cause__ is not None and depth < 10:
        print(f"{pad}  caused by:")
        dump(exc.__cause__, depth + 1)


async def main() -> None:
    resp = httpx.post(
        MINT_URL,
        json={"username": "admin"},
        headers={"X-Mint-Secret": MINT_SECRET},
        timeout=15.0,
    )
    print("mint HTTP", resp.status_code)
    token = resp.json()["token"]
    try:
        data = await call_login_tool(MCP_URL, token, PHONE, CODE)
        print("call_login_tool OK:", data)
    except BaseException as exc:  # noqa: BLE001
        print("=== EXCEPTION TREE ===")
        dump(exc)


if __name__ == "__main__":
    asyncio.run(main())
