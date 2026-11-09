"""PBKDF2-HMAC-SHA256 密码哈希（标准库实现）。

编码格式：``pbkdf2_sha256$<iterations>$<salt_b64url>$<hash_b64url>``。
校验使用 ``hmac.compare_digest`` 恒时比较。
"""

from __future__ import annotations

__all__ = ["encode_password", "verify_password", "DEFAULT_ITERATIONS"]

import base64
import hashlib
import hmac
import secrets

ALGORITHM = "pbkdf2_sha256"
DEFAULT_ITERATIONS = 480_000
SALT_BYTES = 16
KEY_BYTES = 32


def encode_password(password: str, iterations: int = DEFAULT_ITERATIONS) -> str:
    """生成密码哈希行。

    Args:
        password: 明文密码。
        iterations: PBKDF2 迭代次数。

    Returns:
        编码后的哈希行，盐为每次随机生成。
    """
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations, dklen=KEY_BYTES
    )
    salt_b64 = base64.urlsafe_b64encode(salt).decode("ascii")
    hash_b64 = base64.urlsafe_b64encode(digest).decode("ascii")
    return f"{ALGORITHM}${iterations}${salt_b64}${hash_b64}"


def verify_password(password: str, encoded: str) -> bool:
    """校验明文密码与哈希行是否匹配（恒时比较）。

    Args:
        password: 明文密码。
        encoded: encode_password 生成的哈希行。

    Returns:
        匹配返回 True；格式非法或迭代非法时返回 False（不抛异常，
        与"密码错误"同语义，防格式探测）。
    """
    try:
        algorithm, iterations_raw, salt_b64, hash_b64 = encoded.split("$")
        if algorithm != ALGORITHM:
            return False
        iterations = int(iterations_raw)
        if iterations <= 0:
            return False
        salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
        expected = base64.urlsafe_b64decode(hash_b64.encode("ascii"))
    except (ValueError, TypeError):
        return False
    if len(expected) != KEY_BYTES:
        return False
    actual = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations, dklen=len(expected)
    )
    return hmac.compare_digest(actual, expected)
