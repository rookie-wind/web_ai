"""日志脱敏工具。

对日志输出中的敏感信息进行脱敏处理，防止密码、Token、票据等泄露。

脱敏范围：
  - Bearer Token（``Bearer xxx`` → ``Bearer ***``）
  - 密码字段（``password``、``code`` 等键的值）
  - 票据查询串中的 ``owner=`` 参数
  - Authorization 头部值
  - 原始请求体（仅记录大小，不记录内容）
"""

from __future__ import annotations

__all__ = ["sanitize_log_message", "sanitize_headers", "redact_value", "sanitize_report"]

import re

# 敏感键名（小写匹配）
_SENSITIVE_KEYS = frozenset({
    "password", "code", "token", "authorization",
    "secret", "apikey", "api_key", "access_token",
})

# Bearer Token 模式
_BEARER_RE = re.compile(r"Bearer\s+\S+", re.IGNORECASE)

# 敏感键值对模式（JSON/查询串）
_KEY_VALUE_RE = re.compile(
    r'("(?:' + "|".join(_SENSITIVE_KEYS) + r')"\s*:\s*)"[^"]*"',
    re.IGNORECASE,
)

# 查询串中的敏感参数
_QUERY_SENSITIVE_RE = re.compile(
    r"(?:owner|token|password|code)=[^&\s]*",
    re.IGNORECASE,
)


def redact_value(value: str) -> str:
    """将敏感值脱敏为 ``***``。

    Args:
        value: 原始值。

    Returns:
        脱敏后的字符串。
    """
    if not value:
        return value
    return "***"


def sanitize_headers(headers: dict) -> dict:
    """对请求头中的敏感字段脱敏。

    Args:
        headers: 请求头字典。

    Returns:
        脱敏后的请求头字典（新对象，不修改原字典）。
    """
    sanitized = {}
    for key, value in headers.items():
        if key.lower() in _SENSITIVE_KEYS:
            sanitized[key] = "***"
        else:
            sanitized[key] = value
    return sanitized


def sanitize_log_message(message: str) -> str:
    """对日志消息中的敏感信息脱敏。

    处理：Bearer Token、JSON 敏感键值、查询串敏感参数。

    Args:
        message: 原始日志消息。

    Returns:
        脱敏后的消息。
    """
    # Bearer Token
    result = _BEARER_RE.sub("Bearer ***", message)
    # JSON 敏感键值
    result = _KEY_VALUE_RE.sub(r'\1"***"', result)
    # 查询串敏感参数
    result = _QUERY_SENSITIVE_RE.sub(
        lambda m: m.group(0).split("=")[0] + "=***",
        result,
    )
    return result


def sanitize_report(value: object, secrets: tuple[str, ...] = ()) -> object:
    """递归脱敏报告字段与混入响应文本的本任务凭据。"""
    sensitive = _SENSITIVE_KEYS | {
        "captcha", "phone", "loginname", "login_name", "authparam", "headers",
        "raw", "request_body",
    }
    if isinstance(value, dict):
        property_code = str(value.get("propertyCode", "")).lower()
        return {
            str(key): (
                "***"
                if str(key).lower() in sensitive
                or (key == "propertyValue" and property_code in sensitive)
                else sanitize_report(item, secrets)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_report(item, secrets) for item in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "***")
        return sanitize_log_message(value)
    return value
