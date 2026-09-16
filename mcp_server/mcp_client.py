"""
服务端本机 MCP 客户端入口。

实际实现位于随 Agent 资源包分发的 `.trae/skills/pca/tools/mcp_client.py`。
保留本文件是为了兼容既有命令：

    python mcp_server/mcp_client.py <tool_name> [args_json]
"""

import runpy
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DISTRIBUTED_CLIENT = PROJECT_ROOT / ".trae" / "skills" / "pca" / "tools" / "mcp_client.py"

if __name__ == "__main__":
    if not DISTRIBUTED_CLIENT.exists():
        raise FileNotFoundError(f"分发版 MCP 客户端不存在: {DISTRIBUTED_CLIENT}")
    runpy.run_path(str(DISTRIBUTED_CLIENT), run_name="__main__")
