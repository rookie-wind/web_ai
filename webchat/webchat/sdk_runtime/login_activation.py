"""会话授权激活：用接入凭据经 /mcp 完成一次平台登录绑定（design D9）。

新建会话的接入凭据未经平台登录绑定时，任何云端工具（只读与写入均包括）
都会返回 NOT_LOGGED_IN。本模块以该凭据对 /mcp 调一次 ``login(phone, code)``
（凭据来自账号预设，code 服务端语义为不过期），使凭据完成绑定。

依赖 ``mcp`` 客户端库（qodercn-agent-sdk 的传递依赖，随 SDK 一同安装）；
本包之外不得出现其类型与字段名。
"""

from __future__ import annotations

__all__ = ["ActivationError", "call_login_tool"]

import json
from typing import Any


class ActivationError(Exception):
    """平台授权激活失败（网络/协议/业务拒绝均归此类）。"""


def _describe_exc(exc: BaseException, depth: int = 0) -> str:
    """递归展开异常（含 anyio TaskGroup 抛出的 ExceptionGroup 子异常）。

    仅靠 ``str(exc)`` 会得到 "unhandled errors in a TaskGroup" 之类的
    汇总行，丢失真正的根因（design D9：激活失败需返回可辨识原因）。
    """
    pad = "  " * depth
    line = f"{pad}{type(exc).__name__}: {exc}"
    parts = [line]
    for sub in getattr(exc, "exceptions", None) or []:
        parts.append(_describe_exc(sub, depth + 1))
    cause = exc.__cause__
    if cause is not None and depth < 6:
        parts.append(f"{pad}caused by {_describe_exc(cause, depth + 1)}")
    return "\n".join(parts)


def _unwrap_result(result: Any) -> dict:
    """把 CallToolResult 拆成业务字典（文本块按 JSON 解析，失败原样包装）。"""
    content = getattr(result, "content", None) or []
    texts: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            texts.append(text)
    raw = "\n".join(texts)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"text": raw}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


async def call_login_tool(
    mcp_url: str, mcp_token: str, phone: str, code: str
) -> dict:
    """用接入凭据对 /mcp 调用一次 login 工具。

    Args:
        mcp_url: MCP 端点完整地址（形如 ``http://host:port/mcp``）。
        mcp_token: 该会话的接入凭据（Bearer）。
        phone: 账号预设的平台手机号。
        code: 账号预设的平台验证码（服务端语义为不过期）。

    Returns:
        login 工具返回的业务字典。

    Raises:
        ActivationError: 连接/协议失败，或业务返回含错误标记。
    """
    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        headers = {"Authorization": f"Bearer {mcp_token}"}
        async with streamablehttp_client(mcp_url, headers=headers) as (
            read,
            write,
            _,
        ):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "login", {"phoneNum": phone, "code": code}
                )
    except Exception as exc:  # noqa: BLE001 - 激活失败统一归一
        detail = _describe_exc(exc).replace("\n", " | ")
        raise ActivationError(f"授权激活调用失败: {detail}") from exc
    data = _unwrap_result(result)
    is_error = bool(getattr(result, "isError", False))
    failed = (
        is_error
        or data.get("error") is True
        or data.get("success") is False
        or bool(data.get("error"))
        or "NOT_LOGGED_IN" in json.dumps(data, ensure_ascii=False)
    )
    if failed:
        message = data.get("message") or data.get("text") or "业务拒绝"
        raise ActivationError(f"授权激活被拒绝: {message}")
    return data
