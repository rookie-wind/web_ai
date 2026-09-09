"""
协议转换 MCP Server

基于 FastMCP 实现，提供 7 个工具（1 个完整实现 + 6 个桩）。

工具清单（对齐 protocol-conversion-dev-plan.md 4.2 节）：
  1. list_mcp_tools          - 完整实现，列出所有工具 + 鉴权探测
  2. query_device_classes     - 桩，查询品牌/型号/原子标签
  3. update_protocol_file     - 桩（写入），更新内部协议参考文件
  4. add_device_class         - 桩（写入），写入品牌/型号数据
  5. check_script_exists      - 桩，查找已有转换脚本
  6. publish_work_log         - 桩（写入），上传脚本创建记录
  7. publish_converted_script - 桩（写入），发布转换脚本到平台

鉴权模型：
  - Token 自动分配：访问接入页面时根据 IP 自动生成 Token
  - localhost (127.0.0.1/::1) -> 系统级（支持读写），使用管理员 Token
  - 非 localhost -> 用户级（只读），使用自动生成的 Token
  - MCP 端点需要 Bearer Token 验证
  - 接入页面和 Skills 下载端点无需鉴权

Skills 包：
  - 服务器自动打包 .trae/skills/ 目录，无需手动压缩
  - 访问 /api/docs/export-skills-package 下载 ZIP
"""

import os
import io
import json
import socket
import secrets
import zipfile
import contextvars
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

# ── 配置 ──
HOST = os.getenv("MCP_HOST", "0.0.0.0")
PORT = int(os.getenv("MCP_PORT", "8765"))
AUTH_TOKEN = os.getenv("MCP_AUTH_TOKEN", "")

# ── 路径 ──
SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent
SKILLS_DIR = PROJECT_ROOT / ".trae" / "skills"
HTML_PATH = SCRIPT_DIR / "static" / "access.html"

# ── 常量 ──
LOCALHOST_IPS = {"127.0.0.1", "::1", "localhost"}

WRITE_TOOLS = {
    "update_protocol_file",
    "add_device_class",
    "publish_work_log",
    "publish_converted_script",
}

SKIP_DIRS = {"dist", "__pycache__", ".git", "node_modules"}

TOOL_DEFINITIONS = [
    {
        "name": "list_mcp_tools",
        "type": "只读",
        "status": "implemented",
        "description": "列出当前支持的 MCP 功能（兼鉴权探测）",
    },
    {
        "name": "query_device_classes",
        "type": "只读",
        "status": "stub",
        "description": "查询运维平台品牌、型号、原子标签",
    },
    {
        "name": "update_protocol_file",
        "type": "写入",
        "status": "stub",
        "description": "更新内部协议参考文件到本地",
    },
    {
        "name": "add_device_class",
        "type": "写入",
        "status": "stub",
        "description": "写入运维平台品牌、型号数据",
    },
    {
        "name": "check_script_exists",
        "type": "只读",
        "status": "stub",
        "description": "查找是否已有同品牌型号的转换脚本",
    },
    {
        "name": "publish_work_log",
        "type": "写入",
        "status": "stub",
        "description": "上传脚本创建记录",
    },
    {
        "name": "publish_converted_script",
        "type": "写入",
        "status": "stub",
        "description": "发布生成的转换脚本到平台",
    },
]


# ── Token 管理器 ──


class TokenManager:
    """管理 Token 的生成、验证和 IP 关联。

    - localhost: 使用管理员 Token（MCP_AUTH_TOKEN），系统级权限
    - 非 localhost: 自动生成 Token，用户级权限（只读）
    - Token 存储在内存中，服务器重启后重新生成
    """

    def __init__(self, admin_token: str = ""):
        self.admin_token = admin_token
        self.ip_tokens: dict[str, str] = {}

    def get_or_create_token(self, ip: str) -> str:
        """为指定 IP 获取或创建 Token。"""
        if ip in LOCALHOST_IPS and self.admin_token:
            return self.admin_token
        if ip not in self.ip_tokens:
            self.ip_tokens[ip] = "metam_pat_" + secrets.token_hex(16)
        return self.ip_tokens[ip]

    def is_valid(self, token: str) -> bool:
        """验证 Token 是否有效。"""
        if self.admin_token and token == self.admin_token:
            return True
        return token in self.ip_tokens.values()

    def get_token_info(self, ip: str) -> dict:
        """获取 IP 对应的 Token 和权限信息。"""
        token = self.get_or_create_token(ip)
        if ip in LOCALHOST_IPS:
            return {
                "token": token,
                "accessLevel": "system",
                "source": "localhost",
            }
        return {
            "token": token,
            "accessLevel": "user",
            "source": ip,
        }


# ── 权限上下文 ──
access_level_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "access_level", default="user"
)
source_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "source", default="unknown"
)

# ── FastMCP 实例 ──
mcp = FastMCP(
    name="protocol-converter",
    host=HOST,
    port=PORT,
)

# ── 接入页面 ──
try:
    ACCESS_HTML = HTML_PATH.read_text(encoding="utf-8")
except FileNotFoundError:
    ACCESS_HTML = (
        "<html><body><h1>access.html not found</h1>"
        "<p>Ensure mcp_server/static/access.html exists.</p></body></html>"
    )


# ── 辅助函数 ──


def _stub_response(tool_name: str) -> dict:
    return {
        "status": "not_implemented",
        "tool": tool_name,
        "message": "工具已注册，参数 schema 已就绪，具体实现待开发",
    }


def _check_write_permission() -> Optional[dict]:
    """检查写入权限。返回错误 dict 或 None（允许写入）。"""
    if access_level_var.get() != "system":
        return {
            "error": True,
            "code": "FORBIDDEN",
            "message": (
                f"写入操作需要系统级权限（localhost 访问）。"
                f"当前权限级别: {access_level_var.get()}，来源: {source_var.get()}"
            ),
        }
    return None


def _get_host(scope) -> str:
    """从 ASGI scope 提取 Host header。"""
    for name, value in scope.get("headers", []):
        if name == b"host":
            return value.decode()
    server = scope.get("server", ("localhost", PORT))
    return f"{server[0]}:{server[1]}"


def _get_client_ip(scope) -> str:
    """从 ASGI scope 提取客户端 IP。"""
    client = scope.get("client")
    return client[0] if client else "unknown"


def _get_server_ips() -> list:
    """获取服务器的所有有效网络 IP 地址。

    排除：localhost、IPv6 link-local (fe80::)、APIPA 链路本地 (169.254.x.x)、
    IPv6 地址（含冒号）。
    """
    ips = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None):
            ip = info[4][0]
            if (
                ip not in LOCALHOST_IPS
                and not ip.startswith("fe80")
                and not ip.startswith("169.254.")
                and ":" not in ip
            ):
                if ip not in ips:
                    ips.append(ip)
    except Exception:
        pass
    return ips


def _create_skills_zip() -> bytes:
    """将 .trae/skills/ 目录打包为 ZIP（内存中），无需手动压缩。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        if SKILLS_DIR.exists():
            for root, dirs, files in os.walk(SKILLS_DIR):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                for file in files:
                    file_path = Path(root) / file
                    arcname = file_path.relative_to(SKILLS_DIR.parent)
                    zf.write(file_path, arcname)
        else:
            zf.writestr(
                "README.md",
                "# Skills package\n\nSkills directory not found at %s" % SKILLS_DIR,
            )
    return buffer.getvalue()


def _create_skills_markdown() -> str:
    """生成 Skills 目录的 Markdown 摘要。"""
    lines = ["# 协议转换 Skills 汇总", ""]
    if not SKILLS_DIR.exists():
        lines.append("Skills 目录不存在: %s" % SKILLS_DIR)
        return "\n".join(lines)

    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue
        content = skill_md.read_text(encoding="utf-8")
        lines.append("---")
        lines.append("")
        lines.append(content)
        lines.append("")

    return "\n".join(lines)


# ── 工具实现 ──


@mcp.tool()
def list_mcp_tools() -> dict:
    """列出当前 MCP 服务器支持的所有工具及其状态，同时用于鉴权探测。

    返回包含服务器信息、鉴权状态、权限级别和完整工具列表。
    安装验证时调用此工具探测 Token 是否有效及当前权限级别。
    """
    return {
        "server": "protocol-converter",
        "version": "0.1.0",
        "auth": {
            "token_required": True,
            "token_valid": True,
            "access_level": access_level_var.get(),
            "source": source_var.get(),
        },
        "total": len(TOOL_DEFINITIONS),
        "tools": TOOL_DEFINITIONS,
    }


@mcp.tool()
def query_device_classes(brand: str = "", model: str = "", tag: str = "") -> dict:
    """查询运维平台品牌、型号、原子标签。

    Args:
        brand: 品牌名称（可选，为空则查全部）
        model: 型号名称（可选，为空则查全部）
        tag: 原子标签（可选，为空则查全部）
    """
    return _stub_response("query_device_classes")


@mcp.tool()
def update_protocol_file(file_name: str) -> dict:
    """更新内部协议参考文件到本地。

    从服务器拉取最新的协议参考文件并保存到本地。

    Args:
        file_name: 要更新的文件名（必填）
    """
    err = _check_write_permission()
    if err:
        return err
    return _stub_response("update_protocol_file")


@mcp.tool()
def add_device_class(brand: str, model: str, info: str = "") -> dict:
    """写入运维平台品牌、型号数据。

    Args:
        brand: 品牌名称（必填）
        model: 型号名称（必填）
        info: 附加信息（可选）
    """
    err = _check_write_permission()
    if err:
        return err
    return _stub_response("add_device_class")


@mcp.tool()
def check_script_exists(brand: str, model: str) -> dict:
    """查找是否已有同品牌型号的转换脚本。

    Args:
        brand: 品牌名称（必填）
        model: 型号名称（必填）
    """
    return _stub_response("check_script_exists")


@mcp.tool()
def publish_work_log(script_name: str, created_at: str, author: str) -> dict:
    """上传脚本创建记录，用于审计追踪。

    Args:
        script_name: 脚本名称
        created_at: 创建时间
        author: 创建者
    """
    err = _check_write_permission()
    if err:
        return err
    return _stub_response("publish_work_log")


@mcp.tool()
def publish_converted_script(script_content: str, metadata: dict) -> dict:
    """发布生成的转换脚本到平台。

    发布前需通过测试验证。

    Args:
        script_content: 脚本内容，JSON 字符串（必填）
        metadata: 元数据，包含 brand/model/version 等（必填）
    """
    err = _check_write_permission()
    if err:
        return err
    return _stub_response("publish_converted_script")


# ── ASGI 鉴权中间件 ──


class AuthMiddleware:
    """纯 ASGI 中间件，负责 Token 验证和权限分级。

    - Token 验证：所有 /mcp 请求必须携带 Authorization: Bearer <TOKEN>
    - 权限分级：localhost -> system（读写），非 localhost -> user（只读）
    - 使用 contextvars 传递权限信息到工具函数
    """

    def __init__(self, app, token_manager: TokenManager):
        self.app = app
        self.token_manager = token_manager

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {}
        for name, value in scope.get("headers", []):
            headers[name.decode().lower()] = value.decode()

        auth = headers.get("authorization", "")

        if not auth.startswith("Bearer "):
            await self._send_json(send, 401, "Unauthorized: Bearer token required")
            return

        token = auth[7:]
        if not self.token_manager.is_valid(token):
            await self._send_json(send, 401, "Unauthorized: Invalid token")
            return

        client_ip = _get_client_ip(scope)
        if client_ip in LOCALHOST_IPS:
            access_level_var.set("system")
            source_var.set("localhost")
        else:
            access_level_var.set("user")
            source_var.set(client_ip)

        await self.app(scope, receive, send)

    @staticmethod
    async def _send_json(send, status: int, message: str):
        body = json.dumps(
            {"jsonrpc": "2.0", "error": {"code": -32001, "message": message}}
        ).encode()

        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    [b"content-type", b"application/json"],
                    [b"content-length", str(len(body)).encode()],
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


# ── 复合路由 ──


class CompositeApp:
    """ASGI 复合路由：接入页面 + API + 鉴权 MCP。

    路由规则：
      /                         -> 接入页面 HTML（无需鉴权）
      /access                   -> 接入页面 HTML（无需鉴权）
      /api/access-info          -> 自动检测的接入信息 JSON（无需鉴权）
      /api/docs/export-skills-package -> Skills ZIP 下载（无需鉴权）
      /api/docs/export-skills   -> Skills Markdown 摘要（无需鉴权）
      /mcp 及其它                -> 鉴权 MCP 端点（需要 Bearer Token）
    """

    def __init__(self, mcp_app, html_content, token_manager: TokenManager):
        self.mcp_app = mcp_app
        self.auth = AuthMiddleware(mcp_app, token_manager)
        self.html_content = html_content
        self.token_manager = token_manager

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.mcp_app(scope, receive, send)
            return

        path = scope.get("path", "")

        # 接入页面
        if path in ("/", "/access"):
            body = self.html_content.encode("utf-8")
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        [b"content-type", b"text/html; charset=utf-8"],
                        [b"content-length", str(len(body)).encode()],
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        # 接入信息 API（自动检测 IP + 分配 Token）
        if path == "/api/access-info":
            await self._handle_access_info(scope, send)
            return

        # Skills ZIP 下载
        if path == "/api/docs/export-skills-package" or path.startswith(
            "/api/docs/export-skills-package?"
        ):
            await self._handle_export_package(scope, send)
            return

        # Skills Markdown 摘要
        if path == "/api/docs/export-skills" or path.startswith(
            "/api/docs/export-skills?"
        ):
            await self._handle_export_md(scope, send)
            return

        # MCP 端点（需要鉴权）
        await self.auth(scope, receive, send)

    async def _handle_access_info(self, scope, send):
        """返回自动检测的接入信息（含 Token、服务器地址、权限级别）。"""
        client_ip = _get_client_ip(scope)
        host = _get_host(scope)
        server_ips = _get_server_ips()
        token_info = self.token_manager.get_token_info(client_ip)

        # 确定生成接入文本时使用的服务器地址：
        # - localhost 访问者：用服务器网络 IP（给远程用户用）
        # - 远程访问者：用当前 Host header（就是他们访问的地址）
        if client_ip in LOCALHOST_IPS and server_ips:
            base_url = f"http://{server_ips[0]}:{PORT}"
        else:
            base_url = f"http://{host}"

        body = json.dumps(
            {
                "baseUrl": base_url,
                "token": token_info["token"],
                "accessLevel": token_info["accessLevel"],
                "source": token_info["source"],
                "serverIPs": server_ips,
            },
            ensure_ascii=False,
        ).encode("utf-8")

        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    [b"content-type", b"application/json; charset=utf-8"],
                    [b"content-length", str(len(body)).encode()],
                    [b"access-control-allow-origin", b"*"],
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def _handle_export_package(self, scope, send):
        """打包并返回 Skills ZIP。服务器自动打包，无需手动压缩。"""
        zip_data = _create_skills_zip()
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    [b"content-type", b"application/zip"],
                    [b"content-disposition", b'attachment; filename="skills.zip"'],
                    [b"content-length", str(len(zip_data)).encode()],
                ],
            }
        )
        await send({"type": "http.response.body", "body": zip_data})

    async def _handle_export_md(self, scope, send):
        """返回 Skills Markdown 摘要。"""
        md_content = _create_skills_markdown()
        body = md_content.encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    [b"content-type", b"text/markdown; charset=utf-8"],
                    [b"content-length", str(len(body)).encode()],
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


# ── 启动入口 ──
if __name__ == "__main__":
    import threading
    import webbrowser
    import uvicorn

    token_manager = TokenManager(admin_token=AUTH_TOKEN)

    if not AUTH_TOKEN:
        print("[WARNING] MCP_AUTH_TOKEN not set - auto-generating tokens for all IPs.")
        print("[WARNING] Set MCP_AUTH_TOKEN env var for a stable admin token.")
    else:
        print("[INFO] Admin token authentication enabled.")

    get_app = getattr(mcp, "streamable_http_app", None) or getattr(
        mcp, "http_app", None
    )
    if get_app is None:
        raise RuntimeError(
            "Cannot find ASGI app method on FastMCP instance. "
            "Expected 'streamable_http_app' or 'http_app'."
        )
    app = get_app()

    wrapped_app = CompositeApp(app, ACCESS_HTML, token_manager)

    server_ips = _get_server_ips()
    display = "localhost" if HOST in ("0.0.0.0", "::") else HOST
    access_url = f"http://localhost:{PORT}/"
    print(f"[INFO] MCP Server starting on http://{display}:{PORT}")
    print(f"[INFO]   Access Page:  {access_url}")
    print(f"[INFO]   MCP Endpoint: http://{display}:{PORT}/mcp")
    print(f"[INFO]   Skills Download: http://{display}:{PORT}/api/docs/export-skills-package")
    print(f"[INFO]   Tools:         {len(TOOL_DEFINITIONS)} (1 implemented + {len(TOOL_DEFINITIONS) - 1} stubs)")
    print(f"[INFO]   Skills Dir:    {SKILLS_DIR}")
    if server_ips:
        print(f"[INFO]   Network IPs:   {', '.join(ip + ':' + str(PORT) for ip in server_ips)}")
    print()

    # Auto-open browser after startup
    def _open_browser():
        import time
        time.sleep(1.5)
        webbrowser.open(access_url)
        print(f"[INFO] Browser opened: {access_url}")

    threading.Thread(target=_open_browser, daemon=True).start()

    uvicorn.run(wrapped_app, host=HOST, port=PORT, use_colors=False)
