"""云端平台写权限判定：超级账号配置 + 业务 Token 缓存。

权限模型（与 MCP 接入 Token 完全解耦）：
  - MCP 接入 Token：仅用于连接 /mcp 端点，一律 user 级，不授予云端写权限。
  - 云端业务 Token：``login(phoneNum, code)`` 返回，仅用于云端规约平台 API。
  - 云端平台写权限：业务 Token 对应的账号命中本地超级账号配置才可确认后写入。

超级账号配置默认从 ``permissions.json`` 读取，可用环境变量
``MCP_PERMISSIONS_PATH`` 覆盖。业务 Token 缓存为本地敏感运行态文件，
不得提交版本控制或打包分发，且不得在输出中泄露明文 Token。
"""

from __future__ import annotations

__all__ = [
    "SuperAccountConfig",
    "BusinessTokenCache",
    "extract_account_identity",
    "is_auth_expired",
]

import json
import os
import time
from pathlib import Path

# login 返回体中可能出现的账号标识键（userId 优先，phone 兜底）
_USER_ID_KEYS = ("userId", "userid", "id", "uid", "sysUserId", "accountId")
_PHONE_KEYS = ("phoneNum", "phone", "mobile", "telephone", "phoneNumber")
_TOKEN_KEYS = ("token", "accessToken", "businessToken", "bearerToken")
# 认证失效错误码（来源 api_client：AUTH_ERROR / 40100）
_AUTH_EXPIRED_CODES = {"AUTH_ERROR"}
_AUTH_EXPIRED_RAW_CODES = {40100}


def _dig(data: dict, keys: tuple[str, ...]) -> str | None:
    """从嵌套字典中按候选键顺序深度查找第一个非空字符串值。

    Args:
        data: 待查找的字典（如 login 返回的 data）。
        keys: 候选键名，按优先级排列。

    Returns:
        命中的字符串值；未找到返回 None。
    """
    if not isinstance(data, dict):
        return None
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return str(data[key])
    # 常见嵌套容器再找一层
    for nested_key in ("userInfo", "user", "data", "result"):
        nested = data.get(nested_key)
        if isinstance(nested, dict):
            found = _dig(nested, keys)
            if found:
                return found
    return None


def extract_account_identity(login_data: dict) -> dict:
    """从 login 返回的 data 中提取稳定账号标识与业务 Token。

    优先使用 userId 作为稳定标识；缺失时退回 phone。返回结构用于
    超级账号匹配和业务 Token 缓存。

    Args:
        login_data: ``login`` 成功返回结构中的 ``data`` 字段。

    Returns:
        含 ``userId``、``phone``、``token`` 的字典，缺失项为 None。
    """
    return {
        "userId": _dig(login_data, _USER_ID_KEYS),
        "phone": _dig(login_data, _PHONE_KEYS),
        "token": _dig(login_data, _TOKEN_KEYS),
    }


def is_auth_expired(result: dict) -> bool:
    """判断工具返回是否为认证失效。

    Args:
        result: api_client 统一返回结构。

    Returns:
        认证失效返回 True，否则 False。
    """
    if not isinstance(result, dict) or not result.get("error"):
        return False
    if result.get("code") in _AUTH_EXPIRED_CODES:
        return True
    raw = result.get("raw")
    if isinstance(raw, dict) and raw.get("code") in _AUTH_EXPIRED_RAW_CODES:
        return True
    return False


class SuperAccountConfig:
    """本地超级账号配置，决定云端平台写权限是否可用。

    配置文件形如::

        {
          "superAccounts": {
            "userIds": ["1001", "1002"],
            "phones": ["13900000000"]
          }
        }

    userId 与 phone 任一命中即视为超级账号；配置缺失时视为无超级账号。
    """

    def __init__(self, path: Path | str):
        """初始化并加载超级账号配置。

        Args:
            path: 配置文件路径。
        """
        self.path = Path(path)
        self.user_ids: set[str] = set()
        self.phones: set[str] = set()
        self.load()

    def load(self) -> None:
        """从磁盘加载配置；缺失或损坏时视为空配置（无超级账号）。"""
        self.user_ids = set()
        self.phones = set()
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        accounts = data.get("superAccounts", {}) if isinstance(data, dict) else {}
        if not isinstance(accounts, dict):
            return
        self.user_ids = {str(x) for x in accounts.get("userIds", []) if str(x)}
        self.phones = {str(x) for x in accounts.get("phones", []) if str(x)}

    def is_super(self, account: dict | None) -> bool:
        """判断账号是否命中超级账号配置。

        Args:
            account: 含 userId / phone 的账号标识字典。

        Returns:
            命中返回 True；账号为空或未命中返回 False。
        """
        if not account:
            return False
        user_id = account.get("userId")
        phone = account.get("phone")
        if user_id and str(user_id) in self.user_ids:
            return True
        if phone and str(phone) in self.phones:
            return True
        return False


class BusinessTokenCache:
    """云端业务 Token 到账号标识的本地缓存。

    - login 成功后写入，供后续 `/xlpa` 会话复用与写权限判定。
    - 认证失效时可清理对应 Token。
    - 缓存文件为本地敏感运行态文件，不得提交版本控制或打包分发。
    """

    def __init__(self, path: Path | str):
        """初始化并加载缓存。

        Args:
            path: 缓存文件路径。
        """
        self.path = Path(path)
        # token -> {userId, phone, loginAt, lastSeenAt}
        self._entries: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        """从磁盘加载缓存，损坏时回退为空。"""
        if not self.path.exists():
            self._entries = {}
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            entries = data.get("tokens", {})
            self._entries = {
                tok: acc for tok, acc in entries.items() if isinstance(acc, dict)
            }
        except (json.JSONDecodeError, OSError):
            self._entries = {}

    def _save(self) -> None:
        """持久化缓存到磁盘（原子替换）。"""
        try:
            payload = {"tokens": self._entries}
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(tmp, self.path)
        except OSError:
            pass

    def save(self, token: str, account: dict) -> None:
        """写入或更新业务 Token 对应的账号标识。

        Args:
            token: login 返回的云端业务 Token。
            account: 账号标识字典（userId / phone）。
        """
        if not token:
            return
        now = int(time.time())
        existing = self._entries.get(token, {})
        self._entries[token] = {
            "userId": account.get("userId"),
            "phone": account.get("phone"),
            "loginAt": existing.get("loginAt", now),
            "lastSeenAt": now,
        }
        self._save()

    def get_account(self, token: str) -> dict | None:
        """按业务 Token 查询缓存的账号标识。

        Args:
            token: 云端业务 Token。

        Returns:
            账号标识字典；未缓存返回 None。命中时刷新 lastSeenAt。
        """
        account = self._entries.get(token)
        if not account:
            return None
        account["lastSeenAt"] = int(time.time())
        self._save()
        return account

    def invalidate(self, token: str) -> bool:
        """清理失效的业务 Token 缓存。

        Args:
            token: 待清理的云端业务 Token。

        Returns:
            存在并被清理返回 True，否则 False。
        """
        if token in self._entries:
            del self._entries[token]
            self._save()
            return True
        return False

    def most_recent_token(self) -> str | None:
        """返回最近使用过的业务 Token。

        用于无显式 Token 的只读展示场景（如 showcase 平台统计），
        按 lastSeenAt 取最近一条；不刷新 lastSeenAt，也不回显明文。

        Returns:
            最近使用的业务 Token；缓存为空时返回 None。
        """
        if not self._entries:
            return None
        token, _ = max(
            self._entries.items(),
            key=lambda kv: kv[1].get("lastSeenAt", 0),
        )
        return token
