"""密码哈希生成工具：从 stdin 读取密码，输出哈希行。

用法（避免明文进入 shell 历史）::

    python -m webchat.hash_password
    （提示后输入密码，回车两次）

输出示例::

    pbkdf2_sha256$480000$<salt>$<hash>

将输出行填入 webchat_accounts.json 的 password_hash 字段。
"""

from __future__ import annotations

import sys

from .hashing import encode_password


def main() -> int:
    """读取 stdin 密码并输出哈希行。"""
    print("请输入密码（输入不回显到日志，回车结束）:", file=sys.stderr)
    password = sys.stdin.readline().rstrip("\r\n")
    if not password:
        print("未读取到密码输入", file=sys.stderr)
        return 1
    print(encode_password(password))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
