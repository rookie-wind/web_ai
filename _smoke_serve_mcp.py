"""冒烟配套：只拉起 MCP Server（:8772）并保持运行，供 WebSearch 共存验证。

复用 _ac1_probe 的环境加载与端口常量，凭据从 _ac_local.env / mcp_server/.env
注入，本文件不落任何密钥。用完回终端按回车即关停。
"""

from __future__ import annotations

__all__ = ["main"]

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from _ac1_probe import ENV_FILE, MCP_PORT, MCP_PY, load_env_file, wait_port  # noqa: E402

MCP_DIR = ROOT / "mcp_server"


def main() -> int:
    """启动 MCP Server，保持 TTL 秒后自动关停（供后台冒烟使用）。"""
    ttl = int(sys.argv[1]) if len(sys.argv) > 1 else 600
    port = int(sys.argv[2]) if len(sys.argv) > 2 else MCP_PORT
    load_env_file(ENV_FILE)
    load_env_file(MCP_DIR / ".env")
    import os

    env = os.environ.copy()
    env.update({"MCP_HOST": "127.0.0.1", "MCP_PORT": str(port),
                "MCP_PUBLIC_MODE": "0"})
    log = (ROOT / "_smoke_mcp.log").open("w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen([str(MCP_PY), "server.py"], cwd=str(MCP_DIR),
                            env=env, stdout=log, stderr=subprocess.STDOUT)
    if not wait_port(port, proc):
        proc.kill()
        log.close()
        print(f"[serve] mcp 未在 :{port} 就绪，见 _smoke_mcp.log", flush=True)
        return 1
    print(f"[serve] MCP ready at http://127.0.0.1:{port}/mcp "
          f"(ttl={ttl}s)", flush=True)
    try:
        time.sleep(ttl)
    finally:
        proc.terminate()
        time.sleep(2)
        if proc.poll() is None:
            proc.kill()
        log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
