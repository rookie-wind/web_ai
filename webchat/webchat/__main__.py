"""服务启动入口：python -m webchat。"""

from __future__ import annotations

import uvicorn

from .api import create_app
from .config import load_settings


def main() -> None:
    """加载配置并启动服务。"""
    settings = load_settings()
    app = create_app(settings)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
