"""AC-1 人工测试启动器：拉起配对实例并保持运行，供浏览器手动演练。

复用 _ac1_probe 中已验证的配对启动逻辑（同进程树、MCP_PUBLIC_MODE=0、
模型由 WEBCHAT_AGENT_MODEL 指定），但不在跑完一步后关闭服务：本脚本起完两个服务后阻塞，
你在浏览器手动走完建档闭环，回到此终端按回车（或 Ctrl+C）即优雅关停。

凭据经 _ac_local.env / mcp_server/.env 注入，本文件不落任何密钥。
"""

from __future__ import annotations

__all__ = ["main"]

import sys
from pathlib import Path

from _ac1_probe import (
    ENV_FILE,
    MCP_PORT,
    WEBCHAT_PORT,
    load_env_file,
    start_servers,
    stop_servers,
)

ROOT = Path(__file__).resolve().parent
MCP_DIR = ROOT / "mcp_server"


def main() -> int:
    """启动配对实例并阻塞，等待人工操作结束后关停。"""
    load_env_file(ENV_FILE)
    load_env_file(MCP_DIR / ".env")

    print(f"[serve] 启动配对实例 mcp :{MCP_PORT} + webchat :{WEBCHAT_PORT} ...",
          flush=True)
    procs = start_servers()
    base = f"http://127.0.0.1:{WEBCHAT_PORT}"
    print("=" * 56, flush=True)
    print(f"[serve] 浏览器打开： {base}", flush=True)
    print(f"[serve] 局域网访问： http://<本机局域网IP>:{WEBCHAT_PORT}"
          "（已绑 0.0.0.0，需放行防火墙入站端口）", flush=True)
    print("[serve] 登录账号/口令： admin / admin", flush=True)
    print("[serve] 完成后回到本终端按回车关停服务（Ctrl+C 亦可）。", flush=True)
    print("=" * 56, flush=True)
    try:
        input()
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        print("[serve] 关停服务 ...", flush=True)
        stop_servers(procs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
