"""服务端云端平台系统 Token 管理器。

负责 MCP Server 进程持有的 system_token 全生命周期：
  - 启动时通过 permissions.json 中的 systemAccount 自动登录
  - 运行期提供有效 Token 给工具层使用
  - Token 过期时自动刷新
  - 支持超级账号用户更新凭据
"""

from __future__ import annotations

__all__ = ["SystemTokenManager"]

import json
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api_client import ProtocolApiClient


class SystemTokenManager:
    """管理服务端内部持有的云端平台系统 Token。

    - 启动时通过 init() 用 systemAccount 凭据登录获取 Token。
    - get_token() 返回当前有效 Token（可能触发自动刷新）。
    - refresh() 强制重新登录获取新 Token。
    - update_credentials() 用新凭据覆盖 permissions.json 并刷新。
    """

    def __init__(
        self,
        api_client: "ProtocolApiClient",
        permissions_path: Path | str,
    ):
        """初始化 SystemTokenManager。

        Args:
            api_client: 规约平台 HTTP 客户端实例。
            permissions_path: permissions.json 文件路径。
        """
        self._client = api_client
        self._permissions_path = Path(permissions_path)
        self._token: str | None = None
        self._phone: str = ""
        self._code: str = ""
        self._obtained_at: float = 0.0
        self._last_error: str = ""

    @property
    def active(self) -> bool:
        """当前是否持有有效 Token。"""
        return self._token is not None

    @property
    def last_error(self) -> str:
        """最近一次刷新失败的错误信息。"""
        return self._last_error

    @property
    def phone(self) -> str:
        """返回当前内置账号手机号（供 login 角色判据比对）。"""
        return self._phone

    def init(self) -> bool:
        """启动时调用：加载 systemAccount 并尝试获取 Token。

        Returns:
            成功获取 Token 返回 True，否则 False。
        """
        self._load_account()
        if not self._phone or not self._code:
            print(
                "[WARNING] permissions.json 中无有效 systemAccount，"
                "无法获取系统 Token。"
            )
            return False
        return self.refresh()

    def get_token(self) -> str | None:
        """返回当前系统 Token。

        Returns:
            有效 Token 字符串，未初始化或已失效时返回 None。
        """
        return self._token

    def refresh(self) -> bool:
        """使用当前 systemAccount 重新登录获取新 Token（同步版）。

        Returns:
            刷新成功返回 True，失败返回 False（Token 保持旧值或 None）。
        """
        try:
            result = _sync_run(
                self._client.login(self._phone, self._code)
            )
            return self._apply_login_result(result)
        except Exception as exc:
            self._last_error = f"登录异常: {exc}"
            return False

    async def arefresh(self) -> bool:
        """异步刷新系统 Token（在事件循环内安全调用）。

        Returns:
            刷新成功返回 True。
        """
        if not self._phone or not self._code:
            self._last_error = "systemAccount 未配置"
            return False
        try:
            result = await self._client.login(self._phone, self._code)
            return self._apply_login_result(result)
        except Exception as exc:
            self._last_error = f"登录异常: {exc}"
            return False

    def _apply_login_result(self, result: dict) -> bool:
        """解析 login 返回并更新内部状态。"""
        if result.get("error"):
            self._last_error = result.get("message", "登录被平台拒绝")
            return False

        data = result.get("data")
        if not isinstance(data, dict):
            self._last_error = "登录返回数据格式异常"
            return False

        token = _extract_token(data)
        if not token:
            self._last_error = "登录返回中未找到 token 字段"
            return False

        self._token = token
        self._obtained_at = time.time()
        self._last_error = ""
        return True

    def update_credentials(self, phone: str, code: str) -> bool:
        """用新凭据更新 systemAccount 并刷新 Token（同步版）。

        Args:
            phone: 新的手机号。
            code: 新的验证码。

        Returns:
            更新并刷新成功返回 True。
        """
        self._phone = phone
        self._code = code
        self._persist_account()
        return self.refresh()

    async def aupdate_credentials(self, phone: str, code: str) -> bool:
        """用新凭据更新 systemAccount 并刷新 Token（异步版）。"""
        self._phone = phone
        self._code = code
        self._persist_account()
        return await self.arefresh()

    def _load_account(self) -> None:
        """从 permissions.json 加载 systemAccount 段。"""
        if not self._permissions_path.exists():
            return
        try:
            data = json.loads(
                self._permissions_path.read_text(encoding="utf-8")
            )
        except (json.JSONDecodeError, OSError):
            return
        account = data.get("systemAccount", {})
        if isinstance(account, dict):
            self._phone = str(account.get("phone", ""))
            self._code = str(account.get("code", ""))

    def _persist_account(self) -> None:
        """将当前 systemAccount 写回 permissions.json。"""
        try:
            if self._permissions_path.exists():
                data = json.loads(
                    self._permissions_path.read_text(encoding="utf-8")
                )
            else:
                data = {}
            data["systemAccount"] = {
                "phone": self._phone,
                "code": self._code,
            }
            tmp = self._permissions_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(tmp, self._permissions_path)
        except OSError:
            pass


def _extract_token(data: dict) -> str | None:
    """从 login 返回的 data 中提取 Token。

    兼容多种可能的字段名。
    """
    for key in ("token", "accessToken", "businessToken", "bearerToken"):
        val = data.get(key)
        if isinstance(val, str) and val:
            return val
    # 嵌套一层查找
    for nest_key in ("userInfo", "user", "data", "result"):
        nested = data.get(nest_key)
        if isinstance(nested, dict):
            for key in ("token", "accessToken"):
                val = nested.get(key)
                if isinstance(val, str) and val:
                    return val
    return None


def _sync_run(coro):
    """在同步上下文中运行异步协程（启动阶段使用）。

    如果已在事件循环中，在新线程中执行 ``asyncio.run``，
    避免 ``run_coroutine_threadsafe`` + ``future.result``
    在同一线程造成的死锁。
    """
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # 已在事件循环内 — 不能阻塞当前线程等待同一循环，
        # 改为在新线程中创建独立事件循环执行协程。
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="sync-run",
        ) as pool:
            return pool.submit(asyncio.run, coro).result(timeout=30)
    else:
        return asyncio.run(coro)
