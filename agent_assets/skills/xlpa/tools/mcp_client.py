"""
通用 MCP 客户端工具 — 随 xlpa Skill 分发，供 Agent 在原生 MCP 连接不可用时备用调用。

用法:
    python .trae/skills/xlpa/tools/mcp_client.py <tool_name> [args_json]
    python .trae/skills/xlpa/tools/mcp_client.py list_mcp_tools
    python .trae/skills/xlpa/tools/mcp_client.py login '{"phoneNum":"139xxxx","code":"9413"}'
    python .trae/skills/xlpa/tools/mcp_client.py get_classify_list '{"token":"xxx","sysName":""}'

特性:
    - 自动向上查找项目根目录，并读取 .trae/mcp.json 中的 MCP 端点和 Bearer Token
    - 若 Token 失效，自动通过 /api/access-info 获取新 Token 并重试一次
    - 刷新后的 Token 自动写回 .trae/mcp.json
    - 输出格式化 JSON，方便 Agent 解析
    - 支持 --url 参数覆盖端点地址
"""

import asyncio
import json
import sys
import traceback
from pathlib import Path

DEFAULT_URL = "http://localhost:8765/mcp"


def _find_project_root(start: Path | None = None) -> Path:
    """向上查找包含 .trae/mcp.json 的项目根目录。"""
    current = (start or Path(__file__)).resolve()
    for parent in [current.parent, *current.parents]:
        if (parent / ".trae" / "mcp.json").exists():
            return parent
    # 兼容从 mcp_server/mcp_client.py 运行的场景
    if current.parent.name == "mcp_server":
        return current.parent.parent
    return Path.cwd()


PROJECT_ROOT = _find_project_root()
MCP_JSON = PROJECT_ROOT / ".trae" / "mcp.json"


def _load_mcp_config() -> dict:
    """从 .trae/mcp.json 读取 MCP 连接配置。"""
    if MCP_JSON.exists():
        try:
            config = json.loads(MCP_JSON.read_text(encoding="utf-8"))
            servers = config.get("mcpServers", {})
            # 取第一个 server 配置
            for name, srv in servers.items():
                return {
                    "url": srv.get("url", DEFAULT_URL),
                    "token": srv.get("headers", {}).get("Authorization", "").removeprefix("Bearer "),
                    "name": name,
                }
        except (json.JSONDecodeError, KeyError):
            pass
    return {"url": DEFAULT_URL, "token": "", "name": ""}


def _fetch_fresh_token(base_url: str) -> str:
    """通过 /api/access-info 获取新的 Token（无需鉴权）。"""
    import urllib.request

    normalized = base_url.rstrip("/")
    if normalized.endswith("/mcp"):
        access_url = normalized[:-4] + "/api/access-info"
    else:
        access_url = normalized + "/api/access-info"
    try:
        req = urllib.request.Request(access_url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            return data.get("token", "")
    except Exception:
        return ""


def _save_token(new_token: str):
    """将新 Token 写回 .trae/mcp.json。"""
    if MCP_JSON.exists():
        try:
            config = json.loads(MCP_JSON.read_text(encoding="utf-8"))
            for _name, srv in config.get("mcpServers", {}).items():
                if "headers" not in srv:
                    srv["headers"] = {}
                srv["headers"]["Authorization"] = f"Bearer {new_token}"
            MCP_JSON.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass


def _is_unauthorized_error(exc: BaseException) -> bool:
    """识别普通异常或 ExceptionGroup 中的 401/Unauthorized/Invalid token。"""
    text = "".join(traceback.format_exception(exc))
    return "Invalid token" in text or "Unauthorized" in text or "401" in text


async def call_tool(tool_name: str, arguments: dict, url: str = "", token: str = "", retry: bool = True):
    """调用 MCP 工具并输出结果。"""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    cfg = _load_mcp_config()
    actual_url = url or cfg["url"]
    actual_token = token or cfg["token"]

    headers = {}
    if actual_token:
        headers["Authorization"] = f"Bearer {actual_token}"

    try:
        async with streamablehttp_client(actual_url, headers=headers) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)

                texts = []
                for item in result.content:
                    if hasattr(item, "text"):
                        texts.append(item.text)

                raw = "\n".join(texts) if texts else "(no output)"
                try:
                    data = json.loads(raw)
                    # 使用 ensure_ascii=True 避免 Windows 控制台编码问题
                    print(json.dumps(data, indent=2, ensure_ascii=True))
                except json.JSONDecodeError:
                    print(raw)
    except BaseException as exc:
        if retry and _is_unauthorized_error(exc):
            base_url = actual_url.rsplit("/mcp", 1)[0]
            new_token = _fetch_fresh_token(base_url)
            if new_token and new_token != actual_token:
                print("[INFO] Token 已刷新，重试中...", file=sys.stderr)
                _save_token(new_token)
                await call_tool(tool_name, arguments, url=actual_url, token=new_token, retry=False)
                return
        raise


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    tool_name = sys.argv[1]
    args_json = sys.argv[2] if len(sys.argv) > 2 else "{}"

    url = ""
    if "--url" in sys.argv:
        idx = sys.argv.index("--url")
        if idx + 1 < len(sys.argv):
            url = sys.argv[idx + 1]

    try:
        args = json.loads(args_json)
    except json.JSONDecodeError as exc:
        print(f"Error: args_json 解析失败: {exc}", file=sys.stderr)
        print(f"Input: {args_json}", file=sys.stderr)
        sys.exit(1)

    asyncio.run(call_tool(tool_name, args, url=url))


if __name__ == "__main__":
    main()
