"""会话票据：签发、校验、TTL 惰性过期与主动撤销。

票据为服务端内存态：服务重启即全部失效（既定语义，记录在案）。
Session 持有业务凭据（business_token/userId/phone）与角色判定结果，
业务凭据绝不出现在对外响应中。
"""

from __future__ import annotations

__all__ = ["Session", "SessionStore"]

import secrets
import time
from dataclasses import dataclass, field


@dataclass
class Session:
    """单个登录会话。"""

    username: str
    issued_at: int
    expires_at: int
    business_token: str | None = None
    business_user_id: str | None = None
    business_phone: str | None = None
    is_super: bool = False
    login_failures: int = field(default=0, compare=False)


class SessionStore:
    """内存会话票据存储。"""

    def __init__(self, ttl_seconds: int):
        """初始化存储。

        Args:
            ttl_seconds: 票据有效时长（秒）。
        """
        self.ttl_seconds = ttl_seconds
        self._sessions: dict[str, Session] = {}

    def create(self, username: str) -> tuple[str, Session]:
        """签发票据并创建会话。

        Args:
            username: 登录账号名。

        Returns:
            (票据, 会话) 二元组。
        """
        token = secrets.token_urlsafe(32)
        now = int(time.time())
        session = Session(
            username=username,
            issued_at=now,
            expires_at=now + self.ttl_seconds,
        )
        self._sessions[token] = session
        return token, session

    def get(self, token: str) -> Session | None:
        """按票据取会话，过期即惰性删除。

        Args:
            token: 会话票据。

        Returns:
            有效会话；不存在或过期返回 None。
        """
        session = self._sessions.get(token)
        if session is None:
            return None
        if int(time.time()) >= session.expires_at:
            del self._sessions[token]
            return None
        return session

    def revoke(self, token: str) -> bool:
        """主动撤销票据（登出）。

        Args:
            token: 会话票据。

        Returns:
            存在并被撤销返回 True，否则 False。
        """
        if token in self._sessions:
            del self._sessions[token]
            return True
        return False
