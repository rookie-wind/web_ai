"""
协议转换 MCP Server。

基于 FastMCP 实现，将规约管理后端 API 封装为 MCP 原子工具。

工具分组：
  1. 探测   list_mcp_tools            列出所有工具 + 鉴权探测
  2. 登录   login                     手机号+验证码登录，返回业务 Token
  3. 只读   get_* / export_*          查询大类、设备类型、品牌、型号、规约、
                                       数据项、脚本、系数、感知、字典、功能项
  4. 写入   add_* / update_* / del_* / save_* / upload_protocol_file /
                                       gen_script              平台数据变更

鉴权模型：
  - Token 自动分配：访问接入页面时根据 IP 自动生成 Token
  - 本机 IP（含 localhost 和所有网卡 IP） -> 系统级（支持读写），使用管理员 Token
  - 非本机 IP -> 用户级（只读），使用自动生成的 Token
  - MCP 端点需要 Bearer Token 验证
  - 写入类工具统一要求系统级权限，普通用户返回 FORBIDDEN
  - 接入页面和 Skills 下载端点无需鉴权
  - 用户可见地址永远使用 IPv4，绝不展示 IPv6

Token 隔离：
  - MCP 接入 Token：连接 /mcp 的 Authorization: Bearer，不传给后端
  - 后端业务 Token：login 返回，仅作为工具参数传给后端 API

Skills 包：
  - 服务器自动打包 .trae/skills/ 目录，无需手动压缩
  - 访问 /api/docs/export-skills-package 下载 ZIP
"""

import base64
import io
import json
import os
import secrets
import socket
import zipfile
import contextvars
from pathlib import Path
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from api_client import ProtocolApiClient, SUCCESS_CODE

# ── 配置 ──
HOST = os.getenv("MCP_HOST", "0.0.0.0")
PORT = int(os.getenv("MCP_PORT", "8765"))
AUTH_TOKEN = os.getenv("MCP_AUTH_TOKEN", "")

# ── 路径 ──
SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent
SKILLS_DIR = PROJECT_ROOT / ".trae" / "skills"
PACKAGE_MANIFEST_PATH = SKILLS_DIR / "package-manifest.json"
HTML_PATH = SCRIPT_DIR / "static" / "access.html"

# ── 常量 ──
LOCALHOST_IPS = {"127.0.0.1", "::1", "localhost"}


def _get_local_ips() -> set:
    """获取本机的所有有效 IPv4 地址（含 localhost 和 LAN IP）。

    用于判断请求是否来自本机（系统级权限），而不仅限于 127.0.0.1/::1。
    """
    ips = set(LOCALHOST_IPS)
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ("169.254.0.0",) and not ip.startswith("169.254."):
                ips.add(ip)
    except Exception:
        pass
    # 补充：通过 UDP 探测出口 IP（不实际发包）
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.1)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        if local_ip and local_ip != "0.0.0.0":
            ips.add(local_ip)
        s.close()
    except Exception:
        pass
    return ips


# 启动时计算一次本机 IP 集合
LOCAL_IPS = _get_local_ips()

WRITE_TOOLS = {
    "add_classify",
    "update_classify",
    "del_classify",
    "add_device_type",
    "update_device_type",
    "del_device_type",
    "add_brand",
    "update_brand",
    "del_brand",
    "add_model",
    "update_model",
    "del_model",
    "add_protocol_info",
    "update_protocol",
    "del_protocol_info",
    "del_protocol_file",
    "add_data_item",
    "update_data_item",
    "del_data_item",
    "add_coeff",
    "update_coeff",
    "del_coeff",
    "add_sense",
    "update_sense",
    "del_sense",
    "save_protocol_type",
    "del_protocol_type",
    "save_function_item",
    "del_function_item",
    "upload_protocol_file",
    "gen_script",
    "del_script",
}

SKIP_DIRS = {"dist", "__pycache__", ".git", "node_modules"}

# 工具清单：name/type/status，供 list_mcp_tools 返回。
# type 取值：probe（探测）/ login（登录）/ read（只读）/ write（写入）。
TOOL_DEFINITIONS = [
    {"name": "list_mcp_tools", "type": "probe", "description": "列出所有工具与鉴权探测"},
    {"name": "login", "type": "login", "description": "手机号+验证码登录，返回后端业务 Token"},
    # 大类管理
    {"name": "get_classify_list", "type": "read", "description": "查询大类列表（大类编号 id、名称 sysName）"},
    {"name": "add_classify", "type": "write", "description": "新增大类"},
    {"name": "update_classify", "type": "write", "description": "更新大类"},
    {"name": "del_classify", "type": "write", "description": "删除大类"},
    # 设备类型管理
    {"name": "get_device_type_list", "type": "read", "description": "查询设备类型列表（deviceTypeCode 即 modelNum 来源）"},
    {"name": "add_device_type", "type": "write", "description": "新增设备类型"},
    {"name": "update_device_type", "type": "write", "description": "更新设备类型"},
    {"name": "del_device_type", "type": "write", "description": "删除设备类型"},
    # 品牌管理
    {"name": "get_brand_list", "type": "read", "description": "查询品牌列表"},
    {"name": "add_brand", "type": "write", "description": "新增品牌"},
    {"name": "update_brand", "type": "write", "description": "更新品牌"},
    {"name": "del_brand", "type": "write", "description": "删除品牌"},
    # 型号管理
    {"name": "get_model_list", "type": "read", "description": "查询型号列表"},
    {"name": "add_model", "type": "write", "description": "新增型号"},
    {"name": "update_model", "type": "write", "description": "更新型号"},
    {"name": "del_model", "type": "write", "description": "删除型号"},
    {"name": "export_model_data", "type": "read", "description": "导出型号统计数据（文件流）"},
    # 规约信息
    {"name": "get_protocol_info_list", "type": "read", "description": "查询规约列表"},
    {"name": "add_protocol_info", "type": "write", "description": "新增规约"},
    {"name": "update_protocol", "type": "write", "description": "更新规约"},
    {"name": "del_protocol_info", "type": "write", "description": "删除规约"},
    {"name": "del_protocol_file", "type": "write", "description": "删除规约文档文件"},
    # 数据项
    {"name": "get_data_item_list", "type": "read", "description": "查询协议数据项列表（原子标签查询入口）"},
    {"name": "add_data_item", "type": "write", "description": "新增数据项（首期仅基础信息）"},
    {"name": "update_data_item", "type": "write", "description": "更新数据项"},
    {"name": "del_data_item", "type": "write", "description": "删除数据项"},
    # 脚本
    {"name": "gen_script", "type": "write", "description": "生成脚本"},
    {"name": "get_script_list", "type": "read", "description": "查询脚本列表"},
    {"name": "get_json_detail", "type": "read", "description": "获取脚本 JSON 内容"},
    {"name": "del_script", "type": "write", "description": "删除脚本"},
    {"name": "export_data", "type": "read", "description": "导出协议数据项（文件流）"},
    # 系数
    {"name": "get_coeff_list", "type": "read", "description": "查询数据项系数列表"},
    {"name": "add_coeff", "type": "write", "description": "新增数据项系数"},
    {"name": "update_coeff", "type": "write", "description": "更新数据项系数"},
    {"name": "del_coeff", "type": "write", "description": "删除数据项系数"},
    # 感知
    {"name": "get_sense_list", "type": "read", "description": "查询感知结构列表"},
    {"name": "add_sense", "type": "write", "description": "新增感知结构"},
    {"name": "update_sense", "type": "write", "description": "更新感知结构"},
    {"name": "del_sense", "type": "write", "description": "删除感知结构"},
    # 规约类型（字典）
    {"name": "get_protocol_type_list", "type": "read", "description": "查询规约类型字典列表"},
    {"name": "save_protocol_type", "type": "write", "description": "保存规约类型字典项"},
    {"name": "del_protocol_type", "type": "write", "description": "删除规约类型字典项"},
    # 功能项
    {"name": "get_function_type_list", "type": "read", "description": "查询功能项列表"},
    {"name": "save_function_item", "type": "write", "description": "保存功能项"},
    {"name": "del_function_item", "type": "write", "description": "删除功能项"},
    # 文件
    {"name": "upload_protocol_file", "type": "write", "description": "上传规约文档文件"},
]

# 全局 API 客户端实例（事件循环内使用）
api_client = ProtocolApiClient()


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
        if _is_local_ip(ip) and self.admin_token:
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
        if _is_local_ip(ip):
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


def _is_local_ip(ip: str) -> bool:
    """判断 IP 是否属于本机（含 localhost 和所有本机网卡 IP）。"""
    return ip in LOCAL_IPS


def _get_server_ips() -> list:
    """获取服务器的所有有效网络 IPv4 地址。

    排除：localhost、IPv6 link-local (fe80::)、APIPA 链路本地 (169.254.x.x)、
    IPv6 地址（含冒号）。
    """
    ips = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
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
    # 补充 UDP 探测出口 IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.1)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        if local_ip and local_ip not in ips and local_ip not in LOCALHOST_IPS:
            ips.insert(0, local_ip)
        s.close()
    except Exception:
        pass
    return ips


def _sanitize_host_for_display(host: str) -> str:
    """确保用户可见的 baseUrl 不使用 IPv6 地址。

    如果 Host header 包含 IPv6 地址（含冒号/方括号），
    优先使用本机 LAN IP，否则回退到 localhost。
    """
    # 去掉端口部分检查 IP
    host_part = host.split(":")[0] if ":" in host else host
    # 如果 host_part 包含 IPv6 特征（方括号或多冒号），替换为安全地址
    if "[" in host or host_part.count(":") > 0:
        # 优先使用本机 LAN IP
        server_ips = _get_server_ips()
        if server_ips:
            return f"{server_ips[0]}:{PORT}"
        return "localhost"
    return host


def _load_package_manifest() -> dict:
    """读取 Agent 资源包 manifest。"""
    if not PACKAGE_MANIFEST_PATH.exists():
        return {
            "name": "pca-agent-assets",
            "version": "unknown",
            "kind": "agent-assets-package",
            "requiredFiles": [],
            "manifestMissing": True,
        }
    try:
        return json.loads(PACKAGE_MANIFEST_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {
            "name": "pca-agent-assets",
            "version": "invalid",
            "kind": "agent-assets-package",
            "requiredFiles": [],
            "manifestError": str(exc),
        }


def _validate_package_manifest(manifest: Optional[dict] = None) -> dict:
    """校验资源包 manifest 中声明的必需文件是否存在。"""
    manifest = manifest or _load_package_manifest()
    missing = []
    for rel_path in manifest.get("requiredFiles", []):
        full_path = SKILLS_DIR.parent / rel_path
        if not full_path.exists():
            missing.append(rel_path)
    return {
        "ok": len(missing) == 0,
        "missing": missing,
        "required_count": len(manifest.get("requiredFiles", [])),
    }


def _create_skills_zip() -> bytes:
    """将 .trae/skills/ 目录打包为 Agent 资源包 ZIP（兼容旧 Skills ZIP 端点）。"""
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
                "# Agent assets package\n\nSkills directory not found at %s" % SKILLS_DIR,
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
    package_manifest = _load_package_manifest()
    package_validation = _validate_package_manifest(package_manifest)
    return {
        "server": "protocol-converter",
        "version": "0.1.0",
        "resource_package": {
            "name": package_manifest.get("name", "pca-agent-assets"),
            "version": package_manifest.get("version", "unknown"),
            "kind": package_manifest.get("kind", "agent-assets-package"),
            "manifest_path": "skills/package-manifest.json",
            "validation": package_validation,
        },
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
async def login(phoneNum: str, code: str) -> dict:
    """手机号+验证码登录，返回后端业务 Token。

    登录成功后返回的 data.token 为后端业务 Token，仅作为其他工具的
    token 参数传入后端 API，与 MCP 接入 Token（Bearer）相互独立。

    Args:
        phoneNum: 手机号
        code: 短信验证码（不会过期）
    """
    return await api_client.login(phoneNum, code)


# ── 大类管理 ──


@mcp.tool()
async def get_classify_list(
    token: str, sysName: str = "", pageIndex: int = 1, pageSize: int = 9999
) -> dict:
    """查询大类列表（返回的 id 即大类编号 classNum 来源）。

    Args:
        token: 登录后获取的后端业务 Token
        sysName: 大类名称（模糊搜索，为空查全部）
        pageIndex: 当前页码
        pageSize: 每页条数
    """
    return await api_client.get_classify_list(token, sysName, pageIndex, pageSize)


@mcp.tool()
async def add_classify(token: str, sysName: str) -> dict:
    """新增大类。

    Args:
        token: 登录后获取的后端业务 Token
        sysName: 大类名称
    """
    err = _check_write_permission()
    if err:
        return err
    return await api_client.add_classify(token, sysName)


@mcp.tool()
async def update_classify(token: str, classify_id: int, sysName: str) -> dict:
    """更新大类。

    Args:
        token: 登录后获取的后端业务 Token
        classify_id: 大类 ID
        sysName: 大类名称
    """
    err = _check_write_permission()
    if err:
        return err
    return await api_client.update_classify(token, classify_id, sysName)


@mcp.tool()
async def del_classify(token: str, classify_id: int, sysName: str) -> dict:
    """删除大类。

    Args:
        token: 登录后获取的后端业务 Token
        classify_id: 大类 ID
        sysName: 大类名称
    """
    err = _check_write_permission()
    if err:
        return err
    return await api_client.del_classify(token, classify_id, sysName)


# ── 设备类型管理 ──


@mcp.tool()
async def get_device_type_list(
    token: str,
    deviceTypeName: str = "",
    deviceTypeCode: str = "",
    sysId: int = -1,
    pageIndex: int = 1,
    pageSize: int = 9999,
) -> dict:
    """查询设备类型列表（deviceTypeCode 即 modelNum 来源）。

    Args:
        token: 登录后获取的后端业务 Token
        deviceTypeName: 类型名称（模糊搜索，为空查全部）
        deviceTypeCode: 类型编码
        sysId: 所属大类 ID，-1 表示全部
        pageIndex: 当前页码
        pageSize: 每页条数
    """
    return await api_client.get_device_type_list(
        token, deviceTypeName, deviceTypeCode, sysId, pageIndex, pageSize
    )


@mcp.tool()
async def add_device_type(
    token: str, deviceTypeName: str, deviceTypeCode: str, sysId: int
) -> dict:
    """新增设备类型。

    Args:
        token: 登录后获取的后端业务 Token
        deviceTypeName: 类型名称
        deviceTypeCode: 类型编码（纯数字）
        sysId: 所属大类 ID
    """
    err = _check_write_permission()
    if err:
        return err
    return await api_client.add_device_type(token, deviceTypeName, deviceTypeCode, sysId)


@mcp.tool()
async def update_device_type(
    token: str,
    device_type_id: int,
    deviceTypeName: str,
    deviceTypeCode: str,
    sysId: int,
) -> dict:
    """更新设备类型。

    Args:
        token: 登录后获取的后端业务 Token
        device_type_id: 设备类型记录 ID
        deviceTypeName: 类型名称
        deviceTypeCode: 类型编码
        sysId: 所属大类 ID
    """
    err = _check_write_permission()
    if err:
        return err
    return await api_client.update_device_type(
        token, device_type_id, deviceTypeName, deviceTypeCode, sysId
    )


@mcp.tool()
async def del_device_type(token: str, device_type_id: int) -> dict:
    """删除设备类型。

    Args:
        token: 登录后获取的后端业务 Token
        device_type_id: 设备类型记录 ID
    """
    err = _check_write_permission()
    if err:
        return err
    return await api_client.del_device_type(token, device_type_id)


# ── 品牌管理 ──


@mcp.tool()
async def get_brand_list(
    token: str,
    nameCN: str = "",
    code: str = "",
    deviceTypeId: int = -1,
    pageIndex: int = 1,
    pageSize: int = 9999,
) -> dict:
    """查询品牌列表。

    Args:
        token: 登录后获取的后端业务 Token
        nameCN: 品牌名称-中文（模糊搜索，为空查全部）
        code: 品牌编码
        deviceTypeId: 所属设备类型 ID，-1 表示全部
        pageIndex: 当前页码
        pageSize: 每页条数
    """
    return await api_client.get_brand_list(
        token, nameCN, code, deviceTypeId, pageIndex, pageSize
    )


@mcp.tool()
async def add_brand(
    token: str, nameCN: str, name: str, code: str, deviceTypeId: int
) -> dict:
    """新增品牌。

    Args:
        token: 登录后获取的后端业务 Token
        nameCN: 品牌名称-中文
        name: 品牌名称-英文（禁止中文）
        code: 品牌编码
        deviceTypeId: 所属设备类型 ID
    """
    err = _check_write_permission()
    if err:
        return err
    return await api_client.add_brand(token, nameCN, name, code, deviceTypeId)


@mcp.tool()
async def update_brand(
    token: str, brand_id: int, nameCN: str, name: str, code: str, deviceTypeId: int
) -> dict:
    """更新品牌。

    Args:
        token: 登录后获取的后端业务 Token
        brand_id: 品牌记录 ID
        nameCN: 品牌名称-中文
        name: 品牌名称-英文
        code: 品牌编码
        deviceTypeId: 所属设备类型 ID
    """
    err = _check_write_permission()
    if err:
        return err
    return await api_client.update_brand(token, brand_id, nameCN, name, code, deviceTypeId)


@mcp.tool()
async def del_brand(token: str, brand_id: int, name: str, code: str) -> dict:
    """删除品牌。

    Args:
        token: 登录后获取的后端业务 Token
        brand_id: 品牌记录 ID
        name: 品牌名称-英文
        code: 品牌编码
    """
    err = _check_write_permission()
    if err:
        return err
    return await api_client.del_brand(token, brand_id, name, code)


# ── 型号管理 ──


@mcp.tool()
async def get_model_list(
    token: str,
    name: str = "",
    brandId: int = -1,
    pageIndex: int = 1,
    pageSize: int = 9999,
) -> dict:
    """查询型号列表。

    Args:
        token: 登录后获取的后端业务 Token
        name: 型号名称（模糊搜索，为空查全部）
        brandId: 所属品牌 ID，-1 表示全部
        pageIndex: 当前页码
        pageSize: 每页条数
    """
    return await api_client.get_model_list(token, name, brandId, pageIndex, pageSize)


@mcp.tool()
async def add_model(token: str, name: str, brandId: int) -> dict:
    """新增型号。

    Args:
        token: 登录后获取的后端业务 Token
        name: 型号名称
        brandId: 所属品牌 ID
    """
    err = _check_write_permission()
    if err:
        return err
    return await api_client.add_model(token, name, brandId)


@mcp.tool()
async def update_model(token: str, model_id: int, name: str, brandId: int) -> dict:
    """更新型号。

    Args:
        token: 登录后获取的后端业务 Token
        model_id: 型号记录 ID
        name: 型号名称
        brandId: 所属品牌 ID
    """
    err = _check_write_permission()
    if err:
        return err
    return await api_client.update_model(token, model_id, name, brandId)


@mcp.tool()
async def del_model(token: str, model_id: int) -> dict:
    """删除型号。

    Args:
        token: 登录后获取的后端业务 Token
        model_id: 型号记录 ID
    """
    err = _check_write_permission()
    if err:
        return err
    return await api_client.del_model(token, model_id)


@mcp.tool()
async def export_model_data(token: str) -> dict:
    """导出型号统计数据（文件流，返回 Base64 内容）。

    Args:
        token: 登录后获取的后端业务 Token
    """
    return await api_client.export_model_data(token)


# ── 规约信息 ──


@mcp.tool()
async def get_protocol_info_list(
    token: str,
    name: str = "",
    classifyId: Optional[int] = None,
    deviceTypeId: Optional[int] = None,
    brandId: Optional[int] = None,
    modelId: Optional[int] = None,
    pageIndex: int = 1,
    pageSize: int = 9999,
) -> dict:
    """查询规约列表（支持四级分类过滤）。

    Args:
        token: 登录后获取的后端业务 Token
        name: 规约名称（模糊搜索，空串查全部）
        classifyId: 大类 ID（可选过滤）
        deviceTypeId: 设备类型 ID（可选过滤）
        brandId: 品牌 ID（可选过滤）
        modelId: 型号 ID（可选过滤）
        pageIndex: 当前页码
        pageSize: 每页条数
    """
    return await api_client.get_protocol_info_list(
        token, name, classifyId, deviceTypeId, brandId, modelId, pageIndex, pageSize
    )


@mcp.tool()
async def add_protocol_info(
    token: str,
    protocolName: str,
    protoType: int,
    classifyId: int,
    deviceTypeId: int,
    brandId: int,
    modelId: int,
    protocolFiles: Optional[list] = None,
) -> dict:
    """新增规约。

    Args:
        token: 登录后获取的后端业务 Token
        protocolName: 规约名称
        protoType: 规约类型（1=Modbus）
        classifyId: 大类 ID
        deviceTypeId: 设备类型 ID
        brandId: 品牌 ID
        modelId: 型号 ID
        protocolFiles: 规约文档文件列表（可选）
    """
    err = _check_write_permission()
    if err:
        return err
    return await api_client.add_protocol_info(
        token, protocolName, protoType, classifyId, deviceTypeId, brandId, modelId,
        protocolFiles,
    )


@mcp.tool()
async def update_protocol(
    token: str,
    protocol_id: int,
    protocolName: str,
    protoType: int,
    classifyId: int,
    deviceTypeId: int,
    brandId: int,
    modelId: int,
    protocolFiles: Optional[list] = None,
) -> dict:
    """更新规约。

    Args:
        token: 登录后获取的后端业务 Token
        protocol_id: 规约 ID
        protocolName: 规约名称
        protoType: 规约类型
        classifyId: 大类 ID
        deviceTypeId: 设备类型 ID
        brandId: 品牌 ID
        modelId: 型号 ID
        protocolFiles: 规约文档文件列表（可选）
    """
    err = _check_write_permission()
    if err:
        return err
    return await api_client.update_protocol(
        token, protocol_id, protocolName, protoType, classifyId, deviceTypeId,
        brandId, modelId, protocolFiles,
    )


@mcp.tool()
async def del_protocol_info(token: str, protocol_id: int, protocolName: str) -> dict:
    """删除规约。

    Args:
        token: 登录后获取的后端业务 Token
        protocol_id: 规约 ID
        protocolName: 规约名称
    """
    err = _check_write_permission()
    if err:
        return err
    return await api_client.del_protocol_info(token, protocol_id, protocolName)


@mcp.tool()
async def del_protocol_file(token: str, file_id: int) -> dict:
    """删除规约文档文件。

    Args:
        token: 登录后获取的后端业务 Token
        file_id: 文件 ID
    """
    err = _check_write_permission()
    if err:
        return err
    return await api_client.del_protocol_file(token, file_id)


@mcp.tool()
async def upload_protocol_file(
    token: str, file_name: str, file_content_base64: str
) -> dict:
    """上传规约文档文件。

    Args:
        token: 登录后获取的后端业务 Token
        file_name: 上传文件名
        file_content_base64: 文件内容的 Base64 编码字符串
    """
    err = _check_write_permission()
    if err:
        return err
    try:
        content = base64.b64decode(file_content_base64)
    except Exception as exc:
        return {
            "error": True,
            "empty": False,
            "code": "INVALID_PARAM",
            "message": f"file_content_base64 不是合法 Base64: {exc}",
            "raw": None,
        }
    return await api_client.upload_protocol_file(token, file_name, content)


# ── 数据项（原子标签查询入口） ──


@mcp.tool()
async def get_data_item_list(
    token: str, protocolId: int, protoType: int, pageIndex: int = 1, pageSize: int = 9999
) -> dict:
    """查询协议数据项列表（原子标签查询入口）。

    Args:
        token: 登录后获取的后端业务 Token
        protocolId: 规约 ID
        protoType: 规约类型（1=Modbus）
        pageIndex: 当前页码
        pageSize: 每页条数
    """
    return await api_client.get_data_item_list(
        token, protocolId, protoType, pageIndex, pageSize
    )


@mcp.tool()
async def add_data_item(token: str, data: dict) -> dict:
    """新增协议数据项（首期仅基础信息，不含寄存器配置）。

    Args:
        token: 登录后获取的后端业务 Token
        data: 数据项参数字典
    """
    err = _check_write_permission()
    if err:
        return err
    return await api_client.add_data_item(token, data)


@mcp.tool()
async def update_data_item(token: str, data: dict) -> dict:
    """更新协议数据项。

    Args:
        token: 登录后获取的后端业务 Token
        data: 数据项参数字典
    """
    err = _check_write_permission()
    if err:
        return err
    return await api_client.update_data_item(token, data)


@mcp.tool()
async def del_data_item(token: str, data: dict) -> dict:
    """删除协议数据项。

    Args:
        token: 登录后获取的后端业务 Token
        data: 数据项参数字典
    """
    err = _check_write_permission()
    if err:
        return err
    return await api_client.del_data_item(token, data)


# ── 脚本管理 ──


@mcp.tool()
async def gen_script(token: str, data: dict) -> dict:
    """生成脚本。

    Args:
        token: 登录后获取的后端业务 Token
        data: 脚本生成参数字典
    """
    err = _check_write_permission()
    if err:
        return err
    return await api_client.gen_script(token, data)


@mcp.tool()
async def get_script_list(token: str, protocolId: int, protoType: int) -> dict:
    """查询脚本列表。

    Args:
        token: 登录后获取的后端业务 Token
        protocolId: 规约 ID
        protoType: 规约类型
    """
    return await api_client.get_script_list(token, protocolId, protoType)


@mcp.tool()
async def get_json_detail(token: str, data: dict) -> dict:
    """获取脚本 JSON 内容。

    Args:
        token: 登录后获取的后端业务 Token
        data: 请求参数字典（含脚本 ID 等）
    """
    return await api_client.get_json_detail(token, data)


@mcp.tool()
async def del_script(token: str, data: dict) -> dict:
    """删除脚本。

    Args:
        token: 登录后获取的后端业务 Token
        data: 删除参数字典
    """
    err = _check_write_permission()
    if err:
        return err
    return await api_client.del_script(token, data)


@mcp.tool()
async def export_data(token: str, protocolId: int) -> dict:
    """导出协议数据项（文件流，返回 Base64 内容）。

    Args:
        token: 登录后获取的后端业务 Token
        protocolId: 规约 ID
    """
    return await api_client.export_data(token, protocolId)


# ── 系数管理 ──


@mcp.tool()
async def get_coeff_list(token: str, protocolId: int, dataItemId: int) -> dict:
    """查询数据项系数列表。

    Args:
        token: 登录后获取的后端业务 Token
        protocolId: 规约 ID
        dataItemId: 数据项 ID
    """
    return await api_client.get_coeff_list(token, protocolId, dataItemId)


@mcp.tool()
async def add_coeff(token: str, data: dict) -> dict:
    """新增数据项系数。

    Args:
        token: 登录后获取的后端业务 Token
        data: 系数参数字典
    """
    err = _check_write_permission()
    if err:
        return err
    return await api_client.add_coeff(token, data)


@mcp.tool()
async def update_coeff(token: str, data: dict) -> dict:
    """更新数据项系数。

    Args:
        token: 登录后获取的后端业务 Token
        data: 系数参数字典
    """
    err = _check_write_permission()
    if err:
        return err
    return await api_client.update_coeff(token, data)


@mcp.tool()
async def del_coeff(token: str, data: dict) -> dict:
    """删除数据项系数。

    Args:
        token: 登录后获取的后端业务 Token
        data: 系数参数字典
    """
    err = _check_write_permission()
    if err:
        return err
    return await api_client.del_coeff(token, data)


# ── 感知管理 ──


@mcp.tool()
async def get_sense_list(token: str, data: dict) -> dict:
    """查询感知结构列表。

    Args:
        token: 登录后获取的后端业务 Token
        data: 请求参数字典
    """
    return await api_client.get_sense_list(token, data)


@mcp.tool()
async def add_sense(token: str, data: dict) -> dict:
    """新增感知结构。

    Args:
        token: 登录后获取的后端业务 Token
        data: 感知参数字典
    """
    err = _check_write_permission()
    if err:
        return err
    return await api_client.add_sense(token, data)


@mcp.tool()
async def update_sense(token: str, data: dict) -> dict:
    """更新感知结构。

    Args:
        token: 登录后获取的后端业务 Token
        data: 感知参数字典
    """
    err = _check_write_permission()
    if err:
        return err
    return await api_client.update_sense(token, data)


@mcp.tool()
async def del_sense(token: str, data: dict) -> dict:
    """删除感知结构。

    Args:
        token: 登录后获取的后端业务 Token
        data: 感知参数字典
    """
    err = _check_write_permission()
    if err:
        return err
    return await api_client.del_sense(token, data)


# ── 规约类型（字典） ──


@mcp.tool()
async def get_protocol_type_list(
    token: str,
    name: str = "",
    dictItemCode: str = "",
    dictTypeCode: str = "protocolType",
    pageIndex: int = 1,
    pageSize: int = 9999,
) -> dict:
    """查询规约类型字典分页列表。

    Args:
        token: 登录后获取的后端业务 Token
        name: 字典项名称（模糊搜索，为空查全部）
        dictItemCode: 字典项编码
        dictTypeCode: 字典类型编码，规约类型固定 protocolType
        pageIndex: 当前页码
        pageSize: 每页条数
    """
    return await api_client.get_protocol_type_list(
        token, name, dictItemCode, dictTypeCode, pageIndex, pageSize
    )


@mcp.tool()
async def save_protocol_type(
    token: str, name: str, dictItemCode: str, dictTypeCode: str = "protocolType",
    type_id: int = 0,
) -> dict:
    """保存规约类型字典项（新增/编辑共用）。

    Args:
        token: 登录后获取的后端业务 Token
        name: 字典项名称
        dictItemCode: 字典项编码
        dictTypeCode: 字典类型编码，固定 protocolType
        type_id: 字典项 ID，新增时为 0
    """
    err = _check_write_permission()
    if err:
        return err
    return await api_client.save_protocol_type(
        token, name, dictItemCode, dictTypeCode, type_id
    )


@mcp.tool()
async def del_protocol_type(token: str, type_id: int) -> dict:
    """删除规约类型字典项。

    Args:
        token: 登录后获取的后端业务 Token
        type_id: 字典项 ID
    """
    err = _check_write_permission()
    if err:
        return err
    return await api_client.del_protocol_type(token, type_id)


# ── 功能项管理 ──


@mcp.tool()
async def get_function_type_list(
    token: str,
    functionTypeName: str = "",
    functionCode: str = "",
    pageIndex: int = 1,
    pageSize: int = 9999,
) -> dict:
    """查询功能项列表。

    Args:
        token: 登录后获取的后端业务 Token
        functionTypeName: 功能项名称（模糊搜索，为空查全部）
        functionCode: 功能码
        pageIndex: 当前页码
        pageSize: 每页条数
    """
    return await api_client.get_function_type_list(
        token, functionTypeName, functionCode, pageIndex, pageSize
    )


@mcp.tool()
async def save_function_item(token: str, data: dict) -> dict:
    """保存功能项（新增/编辑共用）。

    Args:
        token: 登录后获取的后端业务 Token
        data: 功能项参数字典
    """
    err = _check_write_permission()
    if err:
        return err
    return await api_client.save_function_item(token, data)


@mcp.tool()
async def del_function_item(token: str, functionId: int) -> dict:
    """删除功能项。

    Args:
        token: 登录后获取的后端业务 Token
        functionId: 功能项 ID
    """
    err = _check_write_permission()
    if err:
        return err
    return await api_client.del_function_item(token, functionId)


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
        if _is_local_ip(client_ip):
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
        # - 本机访问者（含 localhost 和本机 LAN IP）：用服务器 LAN IP（给远程用户用）
        # - 远程访问者：用当前 Host header（就是他们访问的地址）
        # - IPv6 访问者：优先 LAN IP，回退 localhost，不展示 IPv6
        if _is_local_ip(client_ip) and server_ips:
            base_url = f"http://{server_ips[0]}:{PORT}"
        elif _is_local_ip(client_ip):
            # 本机访问但没有 LAN IP → 用 localhost，绝不用 IPv6
            base_url = f"http://localhost:{PORT}"
        else:
            safe_host = _sanitize_host_for_display(host)
            base_url = f"http://{safe_host}"

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
    _tool_types = [t["type"] for t in TOOL_DEFINITIONS]
    print(
        f"[INFO]   Tools:         {len(TOOL_DEFINITIONS)} "
        f"(read: {_tool_types.count('read')}, write: {_tool_types.count('write')})"
    )
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
