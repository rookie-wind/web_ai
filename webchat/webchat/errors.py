"""会话运行时异常（无依赖叶子模块）。

单独成模块的原因：``artifacts → sessions_api → runtime → artifacts`` 存在
导入环，异常类若定义在 runtime 中，sessions_api 顶层引用会触发循环导入
（C7 组2 授权激活引入）。此模块不得 import 本包任何其他模块。
"""

from __future__ import annotations

__all__ = [
    "QuotaExceeded",
    "SessionActivationFailed",
    "InvalidQoderPat",
    "DefaultAccountUnavailable",
]


class QuotaExceeded(Exception):
    """实例/会话配额超限。"""


class SessionActivationFailed(Exception):
    """会话平台授权激活失败（上游/凭据问题，非配额）。"""


class InvalidQoderPat(Exception):
    """用户自带 Qoder PAT 无效/过期/品牌不一致（用户输入错误）。"""


class DefaultAccountUnavailable(Exception):
    """默认 Qoder 账号不可用（无服务端 PAT 且无本机登录态），需自带。"""
