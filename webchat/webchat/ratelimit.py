"""登录限流：内存滑动窗口，双维度计数。

维度一：(ip, username) 组合；维度二：ip 全局。任一维度超阈即拒。
失败尝试才计数；成功后不清空历史（窗口自然滑出）。
"""

from __future__ import annotations

__all__ = ["RateLimiter", "RateLimitHit"]

import time
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RateLimitHit:
    """限流命中结果。"""

    retry_after: int


@dataclass
class _Window:
    """单键滑动窗口：时间戳队列。"""

    timestamps: list[float] = field(default_factory=list)


class RateLimiter:
    """双维度滑动窗口限流器（账号级 + 来源级，各自阈值）。"""

    def __init__(
        self, window_seconds: int, max_failures: int, source_max_failures: int | None = None
    ):
        """初始化限流器。

        Args:
            window_seconds: 窗口时长（秒）。
            max_failures: 账号级（ip+username）窗口内失败阈值。
            source_max_failures: 来源级（仅 ip）阈值；缺省沿用 max_failures，
                配置后应显著高于账号级，避免同出口/同反代用户互锁。
        """
        self.window_seconds = window_seconds
        self.max_failures = max_failures
        self.source_max_failures = (
            max_failures if source_max_failures is None else source_max_failures
        )
        self._windows: dict[tuple, _Window] = {}
        # 限流留痕：(时间戳, ip, username)，不含密码
        self.hits: list[dict] = []

    def _prune(self, key: tuple, now: float) -> _Window:
        """滑出窗口外的失败记录。"""
        window = self._windows.setdefault(key, _Window())
        cutoff = now - self.window_seconds
        window.timestamps = [t for t in window.timestamps if t > cutoff]
        return window

    def check(self, ip: str, username: str) -> RateLimitHit | None:
        """检查是否已触发限流。

        Args:
            ip: 客户端地址。
            username: 登录用户名。

        Returns:
            未触发返回 None；触发返回 RateLimitHit（含建议重试秒数）。
        """
        now = time.time()
        for key, limit in (
            ((ip, username), self.max_failures),
            ((ip, ""), self.source_max_failures),
        ):
            window = self._prune(key, now)
            if len(window.timestamps) >= limit:
                oldest = window.timestamps[0]
                return RateLimitHit(
                    retry_after=max(1, int(self.window_seconds - (now - oldest)) + 1)
                )
        return None

    def record_failure(self, ip: str, username: str) -> None:
        """记录一次失败登录（双维度各计一次）。"""
        now = time.time()
        for key in ((ip, username), (ip, "")):
            self._prune(key, now).timestamps.append(now)
        self.hits.append(
            {"at": int(now), "ip": ip, "username": username}
        )
