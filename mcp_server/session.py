"""客户端 Session 管理：按 MCP 接入 Token 绑定身份和权限。

login 成功后创建 Session，后续工具调用通过 mcp_token_var 查找对应 Session，
据此判定读/写权限和 Token 降级策略。
"""

from __future__ import annotations

__all__ = ["Session", "SessionRegistry", "mcp_token_var", "owner_ref_var"]

import contextvars
import time
from dataclasses import dataclass, field

# 当前请求的 MCP 接入 Token（由 AuthMiddleware 设置，工具读取）
mcp_token_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "mcp_token", default=""
)
# 当前请求的归属引用（v3 entry 的 owner_ref，webchat 族由 AuthMiddleware
# 注入；IDE 族为空字符串，操作日志分区回退 sha256(token)）
owner_ref_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "owner_ref", default=""
)


@dataclass
class Session:
    """单个客户端的身份会话。

    Attributes:
        phone: 登录手机号。
        role: 权限角色，"super" 或 "user"。
        fallback_token: 用户 login 时获取的备用业务 Token。
        login_at: 登录时间戳。
        trace_id: 本次操作会话窗标识（login 时由服务端生成）。
    """

    phone: str
    role: str  # "super" | "user"
    fallback_token: str | None = None
    login_at: float = field(default_factory=time.time)
    trace_id: str = ""


class SessionRegistry:
    """按 MCP 接入 Token 管理的内存 Session 集合。

    - 单进程 asyncio 环境，无需加锁。
    - 服务端重启即清空（不持久化）。
    """

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create(
        self,
        mcp_token: str,
        phone: str,
        role: str,
        fallback_token: str | None = None,
    ) -> Session:
        """为指定 MCP Token 创建或覆盖 Session。

        Args:
            mcp_token: 客户端的 MCP 接入 Bearer Token。
            phone: 登录手机号。
            role: "super" 或 "user"。
            fallback_token: 备用业务 Token。

        Returns:
            创建的 Session 对象。
        """
        session = Session(
            phone=phone,
            role=role,
            fallback_token=fallback_token,
        )
        self._sessions[mcp_token] = session
        return session

    def get(self, mcp_token: str) -> Session | None:
        """查询指定 MCP Token 的 Session。

        Args:
            mcp_token: MCP 接入 Token。

        Returns:
            存在返回 Session，否则 None。
        """
        return self._sessions.get(mcp_token)

    def delete(self, mcp_token: str) -> bool:
        """删除指定 MCP Token 的 Session。

        Args:
            mcp_token: MCP 接入 Token。

        Returns:
            删除成功返回 True，不存在返回 False。
        """
        return self._sessions.pop(mcp_token, None) is not None

    def clear(self) -> None:
        """清空所有 Session（服务端重启时隐式调用）。"""
        self._sessions.clear()

    @property
    def count(self) -> int:
        """当前活跃 Session 数量。"""
        return len(self._sessions)
