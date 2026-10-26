"""门户代理配置加载器（服务端运维事实源）。

门户代理地址不再依赖进程环境变量注入（start.bat 读 .env），
而是由服务端直接读取 ``proxy_config.json`` 配置文件，任意启动方式均可生效。

优先级：配置文件 ``proxy_config.json``（存在且有值） > 环境变量 ``PORTAL_PROXY_API_URL``（向后兼容回退） > 空串。

该配置属服务端私有运维信息，不在用户侧文档/提示中暴露地址与文件路径。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# 环境变量名：可覆盖配置文件默认路径（沿用 permissions.json 的 env 覆盖范式）
_CONFIG_PATH_ENV = "PORTAL_PROXY_CONFIG_PATH"
# 环境变量名：旧版配置源（向后兼容回退）
_LEGACY_ENV = "PORTAL_PROXY_API_URL"

# 配置文件默认路径：与 mcp_server 同级目录
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "proxy_config.json"


def _load_from_file(path: Path) -> str:
    """从配置文件读取代理地址；缺失/损坏/为空时返回空串。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
        return ""
    if not isinstance(data, dict):
        return ""
    url = str(data.get("proxy_api_url") or "").strip()
    return url


def portal_proxy_api_url() -> str:
    """返回门户代理地址。

    优先级：配置文件存在且有值 > 环境变量（向后兼容回退） > 空串。
    """
    path = Path(os.getenv(_CONFIG_PATH_ENV, "") or DEFAULT_CONFIG_PATH)
    url = _load_from_file(path)
    if url:
        return url
    return os.getenv(_LEGACY_ENV, "").strip()