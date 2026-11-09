"""平台业务凭据绑定：LoginByCode 代理 + 身份提取 + 超级账号判定。

与 mcp_server 的 api_client/permissions 保持同一语义：
- 平台成功码 SUCCESS_CODE = 20000；
- 身份提取键位与 permissions.extract_account_identity 一致
  （本包不 import mcp_server，维持包边界，纯函数本地复刻）；
- 写权限唯一判据 = permissions.json 的 superAccounts（userId/phone
  任一命中即 super），每次登录时重读，不缓存。
"""

from __future__ import annotations

__all__ = [
    "SUCCESS_CODE",
    "PlatformLoginError",
    "extract_account_identity",
    "load_super_accounts",
    "is_super_account",
    "platform_login",
]

import json
from pathlib import Path

import httpx

SUCCESS_CODE = 20000

# login 返回体中可能出现的账号标识键（与 permissions.py 一致）
_USER_ID_KEYS = ("userId", "userid", "id", "uid", "sysUserId", "accountId")
_PHONE_KEYS = (
    "phoneNum", "phone", "mobile", "mobilePhone", "telephone", "phoneNumber",
)
_TOKEN_KEYS = ("token", "accessToken", "businessToken", "bearerToken")


class PlatformLoginError(Exception):
    """平台登录失败（含网络错误与业务拒绝）。"""


def _dig(data: object, keys: tuple[str, ...]) -> str | None:
    """从嵌套字典按候选键顺序查找第一个非空值（含整型，str() 宽容）。

    与 mcp_server permissions._dig 行为一致：接受整型 userId 等非字符串
    取值（平台 user.userId 为整型），统一转字符串返回。
    """
    if not isinstance(data, dict):
        return None
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return str(data[key])
    for nested_key in ("userInfo", "user", "data", "result"):
        nested = data.get(nested_key)
        if isinstance(nested, dict):
            found = _dig(nested, keys)
            if found:
                return found
    return None


def extract_account_identity(login_data: object) -> dict:
    """从 login 返回的 data 提取稳定账号标识与业务 Token。

    Args:
        login_data: 平台登录成功返回体中的 data 字段。

    Returns:
        含 userId / phone / token 的字典，缺失项为 None。
    """
    return {
        "userId": _dig(login_data, _USER_ID_KEYS),
        "phone": _dig(login_data, _PHONE_KEYS),
        "token": _dig(login_data, _TOKEN_KEYS),
    }


def load_super_accounts(path: Path | str) -> dict[str, set[str]]:
    """读取超级账号配置（缺失/损坏视为无超级账号）。

    Args:
        path: permissions.json 路径。

    Returns:
        {"userIds": set, "phones": set}。
    """
    result: dict[str, set[str]] = {"userIds": set(), "phones": set()}
    path = Path(path)
    if not path.exists():
        return result
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return result
    accounts = data.get("superAccounts") if isinstance(data, dict) else None
    if not isinstance(accounts, dict):
        return result
    result["userIds"] = {
        str(x) for x in accounts.get("userIds", []) if str(x)
    }
    result["phones"] = {
        str(x) for x in accounts.get("phones", []) if str(x)
    }
    return result


def is_super_account(identity: dict, super_accounts: dict[str, set[str]]) -> bool:
    """判定账号标识是否命中超级账号配置。

    Args:
        identity: extract_account_identity 的输出。
        super_accounts: load_super_accounts 的输出。

    Returns:
        命中返回 True；账号为空或未命中返回 False。
    """
    user_id = identity.get("userId")
    phone = identity.get("phone")
    if user_id and str(user_id) in super_accounts["userIds"]:
        return True
    if phone and str(phone) in super_accounts["phones"]:
        return True
    return False


async def platform_login(
    phone: str,
    code: str,
    base_url: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict:
    """代用户完成平台手机号+验证码登录。

    Args:
        phone: 绑定的平台手机号。
        code: 绑定的平台验证码。
        base_url: 平台 API 基地址（PCA_API_BASE_URL 语义）。
        transport: 可注入的 httpx transport（测试用 MockTransport）。

    Returns:
        身份标识字典（userId/phone/token）。

    Raises:
        PlatformLoginError: 网络失败、HTTP 异常或平台业务拒绝。
    """
    url = f"{base_url}/api/Auth/LoginByCode"
    try:
        async with httpx.AsyncClient(
            transport=transport, timeout=httpx.Timeout(15.0)
        ) as client:
            resp = await client.post(
                url, json={"phoneNum": phone, "code": code}
            )
    except httpx.HTTPError as exc:
        raise PlatformLoginError(f"平台网络请求失败: {type(exc).__name__}") from exc
    if resp.status_code != 200:
        raise PlatformLoginError(f"平台 HTTP 状态码异常: {resp.status_code}")
    try:
        body = resp.json()
    except ValueError as exc:
        raise PlatformLoginError("平台响应体不是合法 JSON") from exc
    resp_code = body.get("code") if isinstance(body, dict) else None
    if resp_code != SUCCESS_CODE:
        raise PlatformLoginError("平台登录被拒绝")
    return extract_account_identity(body.get("data") if isinstance(body, dict) else None)
