"""一次性探针：隔离 /mcp login 激活调用，递归打印 ExceptionGroup 子异常。"""

from __future__ import annotations

import asyncio
import traceback

import httpx

MCP_URL = "http://127.0.0.1:8767/mcp"
MINT_URL = "http://127.0.0.1:8767/api/mcp-token/mint"
MINT_SECRET = "V9WU6xiiMgkTa7-vnu9b8EGri2JXZQrK"
PHONE = "13912986342"
CODE = "9413"


def dump(exc: BaseException, depth: int = 0) -> None:
    pad = "  " * depth
    print(f"{pad}! {type(exc).__name__}: {exc}")
    for sub in getattr(exc, "exceptions", []) or []:
        dump(sub, depth + 1)
    if exc.__cause__ is not None and depth < 8:
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
    print("token len", len(token))

    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with streamablehttp_client(MCP_URL, headers=headers) as (
            read,
            write,
            _,
        ):
            async with ClientSession(read, write) as session:
                await session.initialize()
                print("initialize OK")
                result = await session.call_tool(
                    "login", {"phoneNum": PHONE, "code": CODE}
                )
                print("call_tool isError:", getattr(result, "isError", None))
                for block in getattr(result, "content", []) or []:
                    print("  content:", repr(block)[:400])
    except BaseException as exc:  # noqa: BLE001
        print("=== ACTIVATION EXCEPTION TREE ===")
        dump(exc)
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
