"""Web 准入账号库：加载、校验与查询。

账号库为独立 JSON 文件（不入版本控制，模板见
``webchat_accounts.template.json``），每条账号结构：:

    {
      "username": "admin",
      "password_hash": "pbkdf2_sha256$480000$...$...",
      "phone": "13900000000",
      "code": "9413",
      "enabled": true
    }

缺失或损坏时进入"配置错误"状态：登录一律 503，不崩溃、不放行。
"""

from __future__ import annotations

__all__ = ["Account", "AccountsStore", "AccountsConfigError"]

import json
from dataclasses import dataclass
from pathlib import Path


class AccountsConfigError(Exception):
    """账号库缺失、损坏或条目非法。"""


@dataclass(frozen=True)
class Account:
    """单个准入账号条目。"""

    username: str
    password_hash: str
    phone: str
    code: str
    enabled: bool


def _parse_entry(entry: object, index: int) -> Account:
    """解析单条账号，非法即抛 AccountsConfigError。"""
    if not isinstance(entry, dict):
        raise AccountsConfigError(f"账号库第 {index} 条不是对象")
    username = entry.get("username")
    password_hash = entry.get("password_hash")
    phone = entry.get("phone")
    code = entry.get("code")
    enabled = entry.get("enabled", True)
    if not isinstance(username, str) or not username:
        raise AccountsConfigError(f"账号库第 {index} 条 username 缺失或非法")
    if not isinstance(password_hash, str) or not password_hash:
        raise AccountsConfigError(f"账号库第 {index} 条 password_hash 缺失或非法")
    if not isinstance(phone, str) or not phone:
        raise AccountsConfigError(f"账号库第 {index} 条 phone 缺失或非法")
    if not isinstance(code, str) or not code:
        raise AccountsConfigError(f"账号库第 {index} 条 code 缺失或非法")
    if not isinstance(enabled, bool):
        raise AccountsConfigError(f"账号库第 {index} 条 enabled 必须为布尔值")
    return Account(
        username=username,
        password_hash=password_hash,
        phone=phone,
        code=code,
        enabled=enabled,
    )


class AccountsStore:
    """账号库加载与查询。"""

    def __init__(self, path: Path | str):
        """初始化并加载账号库。

        Args:
            path: 账号库 JSON 文件路径。
        """
        self.path = Path(path)
        self._accounts: dict[str, Account] = {}
        self._config_error: AccountsConfigError | None = None
        self._mtime_ns: int | None = None
        self._load()

    def _stat_mtime(self) -> int | None:
        """取账号库文件 mtime（纳秒）；不存在/不可读返回 None。"""
        try:
            return self.path.stat().st_mtime_ns
        except OSError:
            return None

    def _maybe_reload(self) -> None:
        """文件 mtime 变化即重载（账号增删改无需重启服务）。"""
        if self._stat_mtime() == self._mtime_ns:
            return
        self._load()

    def _load(self) -> None:
        """从磁盘加载；缺失/损坏/条目非法时置配置错误状态。"""
        self._accounts = {}
        self._mtime_ns = self._stat_mtime()
        if not self.path.exists():
            self._config_error = AccountsConfigError(
                f"账号库文件不存在: {self.path}"
            )
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, OSError) as exc:
            self._config_error = AccountsConfigError(f"账号库解析失败: {exc}")
            return
        accounts_raw = data.get("accounts") if isinstance(data, dict) else None
        if not isinstance(accounts_raw, list):
            self._config_error = AccountsConfigError("账号库缺少 accounts 数组")
            return
        for index, entry in enumerate(accounts_raw):
            try:
                account = _parse_entry(entry, index)
            except AccountsConfigError as exc:
                self._config_error = exc
                self._accounts = {}
                return
            self._accounts[account.username] = account
        self._config_error = None

    @property
    def config_error(self) -> AccountsConfigError | None:
        """当前配置错误状态；None 表示可用（读取前按 mtime 热加载）。"""
        self._maybe_reload()
        return self._config_error

    def find(self, username: str) -> Account | None:
        """按用户名查询账号。

        Args:
            username: 用户名。

        Returns:
            命中返回 Account；未命中或账号库处于配置错误状态返回 None。
        """
        self._maybe_reload()
        if self._config_error is not None:
            return None
        return self._accounts.get(username)
