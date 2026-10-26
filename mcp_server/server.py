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
  - 服务器自动打包 agent_assets/skills/ 目录，无需手动压缩
  - 访问 /api/docs/export-skills-package 下载 ZIP
"""

import asyncio
import base64
import copy
import functools
import io
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
import zipfile
import contextvars
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from api_client import ProtocolApiClient, SUCCESS_CODE
from permissions import (
    SuperAccountConfig,
    BusinessTokenCache,
    extract_account_identity,
    is_auth_expired)
from token_manager import SystemTokenManager
from session import Session, SessionRegistry, mcp_token_var
from edge_tools import register_edge_tools
from operation_log_store import default_store
from archiving.snapshot_store import derive_owner_id

# ── 配置 ──
HOST = os.getenv("MCP_HOST", "0.0.0.0")
PORT = int(os.getenv("MCP_PORT", "8765"))
AUTH_TOKEN = os.getenv("MCP_AUTH_TOKEN", "")
# XLPA 公网入口 URL（配置后强制 HTTPS 检查；未配置则不限制）
XLPA_PUBLIC_BASE_URL = os.getenv("XLPA_PUBLIC_BASE_URL", "")

# ── 路径 ──
SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent
# Agent 资源包打包源目录（与具体 IDE 无关；客户端安装目录才按平台区分）
SKILLS_DIR = PROJECT_ROOT / "agent_assets" / "skills"
PACKAGE_MANIFEST_PATH = SKILLS_DIR / "package-manifest.json"
HTML_PATH = SCRIPT_DIR / "static" / "access.html"
SHOWCASE_HTML_PATH = SCRIPT_DIR / "static" / "showcase.html"
# Token Registry 持久化文件路径（本地敏感运行态文件，不得提交版本控制）
TOKEN_REGISTRY_PATH = SCRIPT_DIR / ".token_registry.json"
# MCP Server 版本配置事实源（由开发者维护，禁止在代码中硬编码版本）
VERSION_CONFIG_PATH = SCRIPT_DIR / "version.json"
# 本地超级账号配置路径（云端平台写权限事实源，可用环境变量覆盖）
PERMISSIONS_PATH = Path(
    os.getenv("MCP_PERMISSIONS_PATH", str(SCRIPT_DIR / "permissions.json"))
)
# 云端业务 Token 缓存路径（本地敏感运行态文件，不得提交版本控制）
BUSINESS_TOKEN_CACHE_PATH = SCRIPT_DIR / ".business_token_cache.json"
# showcase 平台统计最近成功缓存（本地运行态文件，不得提交版本控制）
SHOWCASE_CACHE_PATH = SCRIPT_DIR / ".showcase_cache.json"
# 事件计数持久化（scriptsGenerated / testTotal / testPassed / testFailed）
STATS_PATH = SCRIPT_DIR / ".stats.json"
# 服务端回归结果独立保存，不覆盖业务事件计数或沿用旧映射核心统计。
SERVER_TEST_REPORT_PATH = SCRIPT_DIR / ".server_test_report.json"

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
            if ip not in ("169.254.0.0") and not ip.startswith("169.254."):
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

SKIP_DIRS = {"dist", "__pycache__", ".git", "node_modules", "temp", "output"}

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
    {"name": "get_data_item_list", "type": "read", "description": "查询协议数据项列表（按规约查询采集点位配置）"},
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
    {"name": "get_function_type_list", "type": "read", "description": "查询功能项列表（原子标签查询入口，API-E10 GetProtocoFunctionTypeList）"},
    {"name": "save_function_item", "type": "write", "description": "保存功能项"},
    {"name": "del_function_item", "type": "write", "description": "删除功能项"},
    # 文件
    {"name": "upload_protocol_file", "type": "write", "description": "上传规约文档文件"},
    # XLPA 自动建档（边缘后端）
    {"name": "convert_comm_address_tool", "type": "edge_util", "description": "条码转 12 位通讯地址（去第 1/2/7 位补 3 个 0）"},
    {
        "name": "generate_device_archive_template", "type": "edge_read",
        "description": "生成建档模板，返回file_id与文件摘要",
    },
    {
        "name": "get_device_archive_template_download", "type": "edge_read",
        "description": "取得指定file_id的模板下载信息",
    },
    {"name": "migrate_device_archive_template", "type": "edge_read", "description": "将旧版本建档模板迁移为当前版本（服务端补表+保留数据）"},
    {"name": "read_device_archive_template", "type": "edge_read", "description": "解析自动建档 Excel 模板并创建会话（脱敏返回）"},
    {"name": "upload_device_archive_template", "type": "edge_read", "description": "上传已填建档模板（Base64），支持单次或分块（upload_id/seq/is_last），末片合并后返回等价 file_id"},
    {"name": "plan_device_archive", "type": "edge_plan", "description": "基于现有设备树生成幂等 dry-run 计划"},
    {"name": "edge_upsert_device", "type": "edge_write", "description": "建档或更新设备（modifyDevice）；支持 node_key 单节点或 node_keys 批量"},
    {"name": "edge_mount_device", "type": "edge_write", "description": "挂载设备到父节点（updateDeviceParent）；支持 node_key 或 node_keys 批量"},
    {"name": "edge_get_device_tree", "type": "edge_read", "description": "读取边缘完整设备树（getDeviceTree）"},
    {"name": "edge_get_device_list", "type": "edge_read", "description": "读取设备档案/子树列表"},
    {
        "name": "edge_get_device_parameters", "type": "edge_read",
        "description": "通用读设备当前参数项（getDeviceParam）；网关默认20100024、监测点默认20200002，可传 item_ids 读任意项；模板/免模板直连代理均支持",
    },
    {
        "name": "edge_save_device_parameters", "type": "edge_write",
        "description": "当前plan独立确认后保存网关20100024或回读XLBA参数；支持 node_key 或 node_keys 批量",
    },
    {
        "name": "edge_set_device_param", "type": "edge_write",
        "description": (
            "批量/全量下发，不区分类型；模板会话按填报值、免模板直连会话"
            "逐台先读后端当前参数(20200002)，读不到则从设备档案(getDeviceList)组装 itemBody 后下发；仅 rtnCode=0 计成功"
        ),
    },
    {
        "name": "edge_call_clock", "type": "edge_write",
        "description": "独立确认召测网关时钟，无建档前置；不校时",
    },
    {
        "name": "edge_call_monitor_debug", "type": "edge_write",
        "description": "31800006监测点召测；rtnCode=0表示召测成功",
    },
    {
        "name": "execute_archive_task", "type": "edge_write",
        "description": "一键执行建档任务（完整/独立）；task_id 模式支持 stages 子集与 batch_size/budget 分批推进，返回续跑游标 cursor/remaining；独立模式对已存在网关执行时钟/下发/召测",
    },
    {
        "name": "get_device_archive_task_report", "type": "edge_read",
        "description": "按归属查询持久阶段报告，支持任务会话过期后查询",
    },
    {"name": "edge_check_monitor_online", "type": "edge_read", "description": "按设备类型判监测点在线（照明/配电房走感知事件，XLBA 走运维召测；模板与免模板直连/代理均支持，不阻塞）"},
    {
        "name": "edge_call_device_data", "type": "edge_write",
        "description": "旧召测兼容入口已阻断，不可替代31800006验收",
    },
    {"name": "edge_apply_compensation_plan", "type": "edge_write", "description": "按补偿清单确认式删除本次新建设备"},
    {"name": "edge_get_token", "type": "edge_util", "description": "独立登录边缘后端，返回 task_id 供后续 edge_* 工具使用"},
    {"name": "edge_delete_device", "type": "edge_write", "description": "删除设备（自动递归删除子设备，叶子优先）"},
]

# 展示分组仅提供元数据，不作为工具存在与否的第二份清单。
TOOL_DOMAIN_GROUPS = {
    "探测与登录": ("list_mcp_tools", "login"),
    "大类管理": ("get_classify_list", "add_classify", "update_classify", "del_classify"),
    "设备类型": (
        "get_device_type_list", "add_device_type", "update_device_type", "del_device_type",
    ),
    "品牌管理": ("get_brand_list", "add_brand", "update_brand", "del_brand"),
    "型号管理": (
        "get_model_list", "add_model", "update_model", "del_model", "export_model_data",
    ),
    "规约信息": (
        "get_protocol_info_list", "add_protocol_info", "update_protocol",
        "del_protocol_info", "del_protocol_file",
    ),
    "数据项": ("get_data_item_list", "add_data_item", "update_data_item", "del_data_item"),
    "脚本管理": (
        "gen_script", "get_script_list", "get_json_detail", "del_script", "export_data",
    ),
    "系数管理": ("get_coeff_list", "add_coeff", "update_coeff", "del_coeff"),
    "感知结构": ("get_sense_list", "add_sense", "update_sense", "del_sense"),
    "规约类型字典": ("get_protocol_type_list", "save_protocol_type", "del_protocol_type"),
    "功能项·原子标签": ("get_function_type_list", "save_function_item", "del_function_item"),
    "文件上传": ("upload_protocol_file",),
    "建档准备": (
        "convert_comm_address_tool", "generate_device_archive_template",
        "get_device_archive_template_download", "upload_device_archive_template",
        "migrate_device_archive_template",
        "read_device_archive_template",
        "plan_device_archive", "edge_get_token",
    ),
    "档案与参数": (
        "edge_upsert_device", "edge_mount_device", "edge_save_device_parameters",
        "edge_set_device_param", "edge_get_device_tree", "edge_get_device_list",
        "edge_get_device_parameters",
        "edge_delete_device", "execute_archive_task",
    ),
    "通信验证": (
        "edge_call_clock", "edge_call_monitor_debug",
        "edge_check_monitor_online", "edge_call_device_data",
    ),
    "报告与补偿": ("get_device_archive_task_report", "edge_apply_compensation_plan"),
}

# 两个页面共用的公开客户端目录；真实凭证只能由接入页在生成时填入。
CLIENT_DEFINITIONS = [
    {
        "id": "trae", "name": "Trae（字节跳动）", "displayName": "Trae",
        "ideName": "Trae IDE", "vendor": "字节跳动", "icon": "T",
        "configPath": ".trae/mcp.json", "configLevel": "项目级（项目根目录）",
        "rootKey": "mcpServers", "urlKey": "url", "transport": {},
        "skillsDir": ".trae/skills",
    },
    {
        "id": "cursor", "name": "Cursor", "displayName": "Cursor",
        "ideName": "Cursor", "vendor": "AI-First IDE", "icon": "C",
        "configPath": ".cursor/mcp.json", "configLevel": "项目级（项目根目录）",
        "rootKey": "servers", "urlKey": "url", "transport": {"type": "http"},
        "skillsDir": ".cursor/skills",
    },
    {
        "id": "vscode", "name": "VS Code Copilot", "displayName": "VS Code Copilot",
        "ideName": "VS Code", "vendor": "GitHub Copilot", "icon": "V",
        "configPath": ".vscode/mcp.json", "configLevel": "项目级（项目根目录）",
        "rootKey": "servers", "urlKey": "url", "transport": {"type": "http"},
        "skillsDir": ".github/skills",
    },
    {
        "id": "claude", "name": "Claude Desktop", "displayName": "Claude Desktop",
        "ideName": "Claude Desktop", "vendor": "Anthropic", "icon": "C",
        "configPath": (
            "Windows: %APPDATA%\\Claude\\claude_desktop_config.json；"
            "macOS: ~/Library/Application Support/Claude/claude_desktop_config.json"
        ),
        "configLevel": "用户级", "rootKey": "mcpServers", "urlKey": "url",
        "transport": {"type": "streamableHttp"}, "skillsDir": ".claude/skills",
    },
    {
        "id": "windsurf", "name": "Windsurf (Codeium)", "displayName": "Windsurf",
        "ideName": "Windsurf", "vendor": "Codeium", "icon": "W",
        "configPath": "~/.codeium/windsurf/mcp_config.json", "configLevel": "用户级",
        "rootKey": "mcpServers", "urlKey": "serverUrl", "transport": {},
        "skillsDir": ".codeium/skills",
    },
    {
        "id": "cline", "name": "Cline", "displayName": "Cline",
        "ideName": "VS Code (Cline extension)", "vendor": "VS Code 插件", "icon": "C",
        "configPath": "cline_mcp_settings.json（VS Code 全局扩展目录）",
        "configLevel": "用户级", "rootKey": "mcpServers", "urlKey": "url",
        "transport": {"type": "streamableHttp"}, "skillsDir": ".cline/skills",
    },
    {
        "id": "kimi", "name": "Kimi Code（月之暗面）", "displayName": "Kimi Code",
        "ideName": "Kimi Code", "vendor": "月之暗面", "icon": "K",
        "configPath": "~/.kimi/mcp.json", "configLevel": "用户级",
        "rootKey": "mcpServers", "urlKey": "url", "transport": {"transport": "http"},
        "skillsDir": ".kimi/skills",
    },
    {
        "id": "qoder", "name": "Qoder", "displayName": "Qoder",
        "ideName": "Qoder", "vendor": "阿里巴巴", "icon": "Q",
        "configPath": "~/.qoder/mcp.json", "configLevel": "用户级",
        "rootKey": "mcpServers", "urlKey": "url", "transport": {},
        "skillsDir": ".qoder/skills",
    },
    {
        "id": "workbuddy", "name": "WorkBuddy", "displayName": "WorkBuddy",
        "ideName": "WorkBuddy", "vendor": "腾讯", "icon": "W",
        "configPath": "~/.workbuddy/mcp.json（Windows 的 ~ 为 %USERPROFILE%）",
        "configLevel": "用户级", "rootKey": "mcpServers", "urlKey": "url",
        "transport": {"type": "streamableHttp"}, "skillsDir": ".codebuddy/skills",
        "skillsNote": "MCP 配置为用户级；Skills 安装到当前项目的 .codebuddy/skills/。",
    },
]

# 全局 API 客户端实例（事件循环内使用）
api_client = ProtocolApiClient()

# 云端平台写权限事实源：超级账号配置 + 业务 Token 缓存
super_account_config = SuperAccountConfig(PERMISSIONS_PATH)
business_token_cache = BusinessTokenCache(BUSINESS_TOKEN_CACHE_PATH)

# 服务端系统 Token 管理（启动时 init）
system_token_mgr = SystemTokenManager(
    api_client=api_client,
    permissions_path=PERMISSIONS_PATH)

# 客户端 Session 注册表（按 MCP Token 绑定）
session_registry = SessionRegistry()


# ── Token 管理器 ──

# Token Registry schema 版本；v2 为 user-only，不再承载 system 权限语义
REGISTRY_SCHEMA_VERSION = 2


class TokenManager:
    """管理 MCP 接入 Token 的生成、验证和 IP 关联。

    - MCP 接入 Token 一律为 user 级接入凭据，不因 localhost / 本机 IP
      或管理员 Token 而授予云端平台写权限。
    - localhost 且配置了 MCP_AUTH_TOKEN 时返回该稳定配置 Token（仍为 user 级）。
    - 非本机 IP 按 IP 固定自动生成 Token，持久化到 .token_registry.json，
      服务器重启后旧 Token 继续有效。
    - Registry 采用 v2 user-only schema；启动时检测旧版并备份后迁移。
    - Token Registry 为本地敏感运行态文件，不得打包分发或提交版本控制。
    """

    def __init__(self, admin_token: str = "", registry_path: Path = TOKEN_REGISTRY_PATH):
        self.admin_token = admin_token
        self.registry_path = Path(registry_path)
        # ip -> {token, accessLevel, createdAt, lastSeenAt, revoked, legacyMigrated}
        self.ip_tokens: dict[str, dict] = {}
        # token -> ip 反向索引，用于鉴权时快速查找
        self._token_to_ip: dict[str, str] = {}
        self._load_registry()

    def _load_registry(self) -> None:
        """加载 Token Registry；检测旧版并迁移为 v2 user-only。

        - 文件不存在：创建空 v2 注册表。
        - schema_version 非 2：备份旧文件后迁移，所有 Token 强制 user 级。
        - 解析失败：备份损坏文件并创建空 v2 注册表，绝不授予 system。
        """
        if not self.registry_path.exists():
            self.ip_tokens = {}
            self._token_to_ip = {}
            return
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self._backup_registry("corrupt")
            self.ip_tokens = {}
            self._token_to_ip = {}
            return
        if not isinstance(data, dict):
            self._backup_registry("corrupt")
            self.ip_tokens = {}
            self._token_to_ip = {}
            return
        entries = data.get("entries", {})
        self.ip_tokens = {
            ip: self._normalize_entry(entry)
            for ip, entry in entries.items()
            if isinstance(entry, dict)
        }
        self._token_to_ip = {
            entry["token"]: ip
            for ip, entry in self.ip_tokens.items()
            if entry.get("token")
        }
        if data.get("schema_version") != REGISTRY_SCHEMA_VERSION:
            # 旧版 registry：先备份，再迁移为 v2 user-only
            self._backup_registry("v1")
            for entry in self.ip_tokens.values():
                entry["legacyMigrated"] = True
            self._save_registry()

    @staticmethod
    def _normalize_entry(entry: dict) -> dict:
        """将任意版本的 entry 归一化为 v2 user-only 结构。

        忽略并移除旧版可能携带的 system / admin 权限来源语义，
        accessLevel 一律归一为 user。
        """
        return {
            "token": entry.get("token"),
            "accessLevel": "user",
            "createdAt": entry.get("createdAt", 0),
            "lastSeenAt": entry.get("lastSeenAt", 0),
            "revoked": bool(entry.get("revoked", False)),
            "legacyMigrated": bool(entry.get("legacyMigrated", False)),
            "source": entry.get("source", "auto"),
        }

    def _backup_registry(self, tag: str) -> None:
        """备份当前 registry 文件用于迁移或诊断；失败不阻塞启动。

        Args:
            tag: 备份标记，如 ``v1`` 或 ``corrupt``。
        """
        try:
            if self.registry_path.exists():
                backup_path = Path(f"{self.registry_path}.{tag}.backup")
                backup_path.write_bytes(self.registry_path.read_bytes())
        except OSError:
            pass

    def _save_registry(self) -> None:
        """持久化 v2 user-only Token Registry 到磁盘。"""
        try:
            payload = {
                "schema_version": REGISTRY_SCHEMA_VERSION,
                "entries": self.ip_tokens,
            }
            tmp_path = self.registry_path.with_suffix(".tmp")
            tmp_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8")
            os.replace(tmp_path, self.registry_path)
        except OSError:
            # 写入失败不阻塞请求，仅影响重启后复用
            pass

    def get_or_create_token(self, ip: str) -> str:
        """为指定 IP 获取或创建 Token（任意 IP 含本机均持久化，重启后仍可用）。

        - 任意 IP：Registry 中已有（未撤销）则复用。
        - 本机且无记录：返回管理员 Token（.env），并登记持久化（source=admin）。
        - 其余：新建 ``metam_pat_<hex>`` 并持久化（source=auto）。
        - 已撤销的 IP 会生成新 Token 并覆盖旧记录。
        """
        entry = self.ip_tokens.get(ip)
        if entry and not entry.get("revoked"):
            entry["lastSeenAt"] = int(time.time())
            self._save_registry()
            return entry["token"]
        if _is_local_ip(ip) and self.admin_token:
            new_token = self.admin_token
            source = "admin"
        else:
            new_token = "metam_pat_" + secrets.token_hex(16)
            source = "auto"
        now = int(time.time())
        self.ip_tokens[ip] = {
            "token": new_token,
            "accessLevel": "user",
            "createdAt": now,
            "lastSeenAt": now,
            "revoked": False,
            "legacyMigrated": False,
            "source": source,
        }
        self._token_to_ip[new_token] = ip
        self._save_registry()
        return new_token

    def is_valid(self, token: str) -> bool:
        """验证 Token 是否有效。

        - 管理员 Token 精确匹配
        - Registry 中未撤销的 user Token 视为有效
        """
        if self.admin_token and token == self.admin_token:
            return True
        if token in self._token_to_ip:
            ip = self._token_to_ip[token]
            entry = self.ip_tokens.get(ip)
            if entry and not entry.get("revoked") and entry.get("token") == token:
                return True
        return False

    def get_token_info(self, ip: str) -> dict:
        """获取 IP 对应的 Token 和接入信息（一律 user 级）。

        MCP 接入 Token 不再区分 system / user；本机与远程来源均返回
        user 级接入凭据，云端平台写权限另由业务登录账号判定。
        """
        token = self.get_or_create_token(ip)
        return {
            "token": token,
            "accessLevel": "user",
            "source": ("localhost" if _is_local_ip(ip)
                        else _sanitize_ip_for_display(ip)),
        }

    def revoke_token(self, ip: str) -> bool:
        """撤销指定 IP 的 Token（预留管理接口）。"""
        entry = self.ip_tokens.get(ip)
        if not entry:
            return False
        old_token = entry.get("token")
        if old_token and self._token_to_ip.get(old_token) == ip:
            self._token_to_ip.pop(old_token, None)
        entry["revoked"] = True
        entry["lastSeenAt"] = int(time.time())
        self._save_registry()
        return True

    def touch_ip_last_seen(self, ip: str) -> None:
        """更新已存在 IP 记录的 lastSeenAt（不改变 Token）。"""
        entry = self.ip_tokens.get(ip)
        if not entry or entry.get("revoked"):
            return
        entry["lastSeenAt"] = int(time.time())
        self._save_registry()


# ── 权限上下文 ──
# 旧 contextvar，过渡期保留，Group 4 完成后移除
access_level_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "access_level", default="user"
)
source_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "source", default="unknown"
)
# mcp_token_var 已移至 session.py 共享，避免循环导入

# ── FastMCP 实例 ──
mcp = FastMCP(
    name="xl-protocol-agent",
    host=HOST,
    port=PORT)

# ── 注册边缘自动建档原子工具 ──

def _rows_of(result: dict, key: str = "rows") -> list[dict]:
    """从统一返回结构抽取 data.rows 列表。"""
    data = result.get("data") if isinstance(result, dict) else None
    if isinstance(data, dict):
        rows = data.get(key, [])
        return rows if isinstance(rows, list) else []
    if isinstance(data, list):
        return data
    return []


async def _template_dict_source() -> dict:
    """以系统超管 Token 拉取平台全量字典，构造 generate_template 所需 kwargs。

    逻辑与服务器侧 stage_zero.generate_archive_template 保持一致（device_types
    / user_big_nos 复用 get_device_type_list 全集，品牌以型号 brandName 为稳定键，
    通信方式采用内置实测枚举），从而使用户侧与服务器侧生成同一份完整模板。

    任一平台 API 返回错误时抛出 RuntimeError，由调用方捕获并写入 warning。

    Returns:
        generate_template 字典 kwargs（device_types / user_big_nos /
        comm_modes / brands / models_by_brand）。

    Raises:
        RuntimeError: 平台 API 返回错误（含具体原因）。
    """
    type_rows = await _call_platform(api_client.get_device_type_list)
    brand_rows = await _call_platform(api_client.get_brand_list)
    model_rows = await _call_platform(api_client.get_model_list)

    # 检查 API 返回，透传错误信息
    errors = []
    for label, result in [
        ("设备类型", type_rows),
        ("品牌", brand_rows),
        ("型号", model_rows),
    ]:
        if isinstance(result, dict) and result.get("error"):
            errors.append(f"{label}: {result.get('message', '未知错误')}")
    if errors:
        raise RuntimeError("; ".join(errors))

    device_types = [
        {"name": r.get("deviceTypeName") or "", "code": str(r.get("deviceTypeCode") or "")}
        for r in _rows_of(type_rows)
        if r.get("deviceTypeName")
    ]
    user_big_nos = [
        {"name": r.get("deviceTypeName") or "", "code": str(r.get("deviceTypeCode") or "")}
        for r in _rows_of(type_rows)
        if r.get("deviceTypeName")
    ]
    code_by_bname = {
        (b.get("nameCN") or b.get("name")): b.get("code") for b in _rows_of(brand_rows)
    }
    brands, seen_b = [], set()
    for m in _rows_of(model_rows):
        bn = m.get("brandName")
        if not bn or bn in seen_b:
            continue
        seen_b.add(bn)
        brands.append({"name": bn, "code": str(code_by_bname.get(bn, "") or "")})
    models_by_brand: dict[str, list[dict]] = {}
    for m in _rows_of(model_rows):
        bn = m.get("brandName") or "未知品牌"
        models_by_brand.setdefault(bn, []).append(
            {"name": m.get("name") or "", "code": str(m.get("modelCode") or "")}
        )
    return {
        "device_types": device_types,
        "user_big_nos": user_big_nos,
        "comm_modes": [{"name": "AI_test现场MQTT", "code": "13"}],
        "brands": brands,
        "models_by_brand": models_by_brand,
    }


register_edge_tools(mcp, template_dict_source=_template_dict_source)

# ── 静态页面 ──
try:
    ACCESS_HTML = HTML_PATH.read_text(encoding="utf-8")
except FileNotFoundError:
    ACCESS_HTML = (
        "<html><body><h1>access.html not found</h1>"
        "<p>Ensure mcp_server/static/access.html exists.</p></body></html>"
    )

try:
    SHOWCASE_HTML = SHOWCASE_HTML_PATH.read_text(encoding="utf-8")
except FileNotFoundError:
    # 展示页缺失时回退到接入页面，保证根路径始终可访问
    SHOWCASE_HTML = ACCESS_HTML


# ── 辅助函数 ──


def _require_session() -> Session | dict:
    """检查当前请求是否已登录，返回 Session 或错误字典。

    Returns:
        已登录返回 Session 对象；未登录返回 NOT_LOGGED_IN 错误字典。
    """
    token = mcp_token_var.get("")
    session = session_registry.get(token)
    if session is None:
        return {
            "error": True,
            "code": "NOT_LOGGED_IN",
            "message": "请先调用 login 验证身份。",
        }
    return session


def _require_super() -> Session | dict:
    """检查当前请求是否拥有超级账号权限。

    Returns:
        有写权限返回 Session；否则返回错误字典。
    """
    result = _require_session()
    if isinstance(result, dict):
        return result
    if result.role != "super":
        return {
            "error": True,
            "code": "FORBIDDEN",
            "message": "此操作需要超级账号权限，当前角色为 user（只读）。",
        }
    return result


def _get_api_token() -> str | None:
    """返回服务端持有的有效系统 Token。

    如果系统 Token 失效，尝试从当前 session 的 fallback_token 获取。
    """
    token = system_token_mgr.get_token()
    if token:
        return token
    # 系统 Token 失效，尝试用当前 session 的 fallback
    mcp_token = mcp_token_var.get("")
    session = session_registry.get(mcp_token)
    if session and session.fallback_token:
        return session.fallback_token
    return None


async def _call_platform(
    api_method, *args, **kwargs
) -> dict:
    """调用平台 API，封装透明 Token 刷新和降级链。

    流程：
      1. 用 system_token 调用
      2. 40100 自动 refresh → 重试
      3. 仍失败：尝试 session.fallback_token
      4. 全部失败：返回 AUTH_EXPIRED

    Args:
        api_method: api_client 的异步方法（第一个参数为 token）。
        *args / **kwargs: 传递给 api_method 的其余参数。

    Returns:
        平台 API 返回结果，或 AUTH_EXPIRED 错误字典。
    """
    token = system_token_mgr.get_token()
    if not token:
        # 无系统 Token，直接尝试 fallback
        return await _try_fallback_and_report(api_method, *args, **kwargs)

    result = await api_method(token, *args, **kwargs)

    if is_auth_expired(result):
        # 透明刷新：尝试重新获取 system_token
        refreshed = await system_token_mgr.arefresh()
        if refreshed:
            token = system_token_mgr.get_token()
            result = await api_method(token, *args, **kwargs)
            if not is_auth_expired(result):
                return result
        # 刷新也失败，走降级链
        return await _try_fallback_and_report(api_method, *args, **kwargs)

    return result


async def _try_fallback_and_report(
    api_method, *args, **kwargs
) -> dict:
    """尝试用当前 session 的 fallback_token 调用，失败返回 AUTH_EXPIRED。"""
    mcp_token = mcp_token_var.get("")
    session = session_registry.get(mcp_token)
    if session and session.fallback_token:
        result = await api_method(session.fallback_token, *args, **kwargs)
        if not is_auth_expired(result):
            return result
    return {
        "error": True,
        "code": "AUTH_EXPIRED",
        "message": "云端平台不可用，请检查账号或等待恢复。",
    }


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


def _sanitize_ip_for_display(ip: str) -> str:
    """确保用户可见的 IP 不包含 IPv6 地址。

    IPv4 地址原样返回；IPv6 地址（含冒号）返回 'remote'，
    绝不向用户展示 IPv6 地址。
    """
    if ":" in ip:
        return "remote"
    return ip


def _is_local_ip(ip: str) -> bool:
    """判断 IP 是否属于本机（含 localhost、所有网卡 IP 和 IPv6 环回）。"""
    if ip in LOCAL_IPS:
        return True
    # IPv6 环回地址 ::1 与 :: 也视为本机
    return ip in ("::1", "::", "0:0:0:0:0:0:0:1")


# 已知虚拟网卡 IP 前缀（VMware / Hyper-V / WSL 等），展示时排除
_VIRTUAL_ADAPTER_PREFIXES = (
    "192.168.58.",   # VMware VMnet8
    "192.168.117.",  # VMware VMnet1 / 其他虚拟网卡
    "172.28.",       # WSL / DockerNAT
    "172.29.",       # WSL / DockerNAT
    "172.30.",       # DockerNAT
    "172.31.",       # DockerNAT
)


def _is_virtual_adapter_ip(ip: str) -> bool:
    """判断 IP 是否属于已知虚拟网卡网段。"""
    return ip.startswith(_VIRTUAL_ADAPTER_PREFIXES)


def _get_server_ips() -> list:
    """获取服务器的所有有效网络 IPv4 地址。

    排除：localhost、IPv6 link-local (fe80::)、APIPA 链路本地 (169.254.x.x)、
    IPv6 地址（含冒号）、虚拟网卡（VMware / Hyper-V / WSL / DockerNAT）。
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
                and not _is_virtual_adapter_ip(ip)
            ):
                if ip not in ips:
                    ips.append(ip)
    except Exception:
        pass
    # 补充 UDP 探测出口 IP（同样排除虚拟网卡）
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.1)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        if (
            local_ip
            and local_ip not in ips
            and local_ip not in LOCALHOST_IPS
            and not _is_virtual_adapter_ip(local_ip)
        ):
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


def _load_server_version() -> dict:
    """读取 MCP Server 版本配置事实源。

    版本从 version.json 读取，不再硬编码。配置缺失或无效时
    返回 version="unknown" 并携带无法比较的原因，供上层展示。

    Returns:
        包含 serverName、version 和可选 versionError 的字典。
    """
    fallback_name = "xl-protocol-agent"
    if not VERSION_CONFIG_PATH.exists():
        return {
            "serverName": fallback_name,
            "version": "unknown",
            "versionError": "版本配置缺失: version.json 不存在",
        }
    try:
        data = json.loads(VERSION_CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {
            "serverName": fallback_name,
            "version": "invalid",
            "versionError": f"版本配置无法解析: {exc}",
        }
    version = data.get("serverVersion")
    if not isinstance(version, str) or not version:
        return {
            "serverName": data.get("serverName", fallback_name),
            "version": "unknown",
            "versionError": "版本配置缺少有效 serverVersion 字段",
        }
    return {
        "serverName": data.get("serverName", fallback_name),
        "version": version,
    }


def _load_package_manifest() -> dict:
    """读取 Agent 资源包 manifest。"""
    if not PACKAGE_MANIFEST_PATH.exists():
        return {
            "name": "xlpa-agent-assets",
            "version": "unknown",
            "kind": "agent-assets-package",
            "requiredFiles": [],
            "manifestMissing": True,
        }
    try:
        manifest = json.loads(PACKAGE_MANIFEST_PATH.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("资源包 manifest 必须是对象")
        return manifest
    except (OSError, UnicodeError, ValueError):
        return {
            "name": "xlpa-agent-assets",
            "version": "invalid",
            "kind": "agent-assets-package",
            "requiredFiles": [],
            "manifestError": "资源包 manifest 不可用",
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
    """将 agent_assets/skills/ 目录打包为 Agent 资源包 ZIP（兼容旧 Skills ZIP 端点）。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        if SKILLS_DIR.exists():
            for root, dirs, files in os.walk(SKILLS_DIR):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                for file in files:
                    if file.startswith("~$"):
                        continue
                    file_path = Path(root) / file
                    arcname = file_path.relative_to(SKILLS_DIR.parent)
                    zf.write(file_path, arcname)
        else:
            zf.writestr(
                "README.md",
                "# Agent assets package\n\nSkills directory not found at %s" % SKILLS_DIR)
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


# ── showcase 展示数据汇总 ──


def _skill_directories() -> list[Path]:
    """列出发布目录内的所有 Skill，包含独立分发的子技能。"""
    if not SKILLS_DIR.is_dir():
        return []
    return [
        entry for entry in sorted(SKILLS_DIR.iterdir())
        if entry.is_dir() and entry.name not in SKIP_DIRS
        and not entry.name.startswith(".") and (entry / "SKILL.md").is_file()
    ]


def _count_skills() -> int:
    """统计实际 Skill 文件数量，不以顶层协议方向数量代替。"""
    return len(_skill_directories())


def _public_tool_catalog() -> list[dict]:
    """从唯一工具清单提取公开展示字段，并补充分组与操作性质。"""
    domains = {name: domain for domain, names in TOOL_DOMAIN_GROUPS.items() for name in names}
    tools = []
    for tool in TOOL_DEFINITIONS:
        kind = tool["type"]
        operation = "read" if kind in ("read", "edge_read") else "other"
        if kind in ("write", "edge_write"):
            operation = "write"
        tools.append({
            "name": tool["name"], "type": kind,
            "description": tool.get("description", ""),
            "domain": tool.get("domain") or domains.get(tool["name"], "其他"),
            "operation": operation,
        })
    return tools


def _skill_capabilities(package: dict) -> dict:
    """动态统计 Skill，并仅聚合已发布技能显式声明的顶层方向。"""
    errors = []
    skills_available = SKILLS_DIR.is_dir()
    try:
        folders = _skill_directories()
    except OSError:
        folders = []
        skills_available = False
    if not skills_available:
        errors.append("Skill 目录不可用")
    skills = [folder.name for folder in folders]
    declared = package.get("skills")
    directions = {}
    if not isinstance(declared, list) or any(not isinstance(n, str) for n in declared):
        declared = []
        errors.append("资源包 Skill 清单不可用")
    for name in declared:
        if name not in skills:
            errors.append(f"Skill 缺失：{name}")
    for folder in folders:
        if folder.name not in declared:
            continue
        try:
            manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
            entries = manifest.get("protocolDirections", [])
            if not isinstance(entries, list):
                raise ValueError("方向声明必须是数组")
            for item in entries:
                if not isinstance(item, dict) or item.get("level") not in ("top", "sub"):
                    raise ValueError("方向必须声明 top/sub 层级")
                if item["level"] == "sub":
                    continue
                if any(not isinstance(item.get(k), str) or not item[k].strip()
                       for k in ("id", "name")):
                    raise ValueError("方向缺少标识或名称")
                direction = {"id": item["id"].strip(), "name": item["name"].strip()}
                previous = directions.get(direction["id"])
                if previous and previous != direction:
                    raise ValueError("同一方向标识的名称不一致")
                directions[direction["id"]] = direction
        except (OSError, UnicodeError, ValueError, AttributeError):
            errors.append(f"Skill 方向声明不可用：{folder.name}")
    # 任何声明损坏时保留错误语义，不能把部分结果当作真实总数。
    ordered = sorted(directions.values(), key=lambda item: item["id"])
    return {
        "skills": skills,
        "skillCount": len(skills) if skills_available else None,
        "skillsAvailable": skills_available,
        "protocolDirections": ordered if not errors else [],
        "protocolDirectionCount": len(ordered) if not errors else None,
        "protocolDirectionsAvailable": not errors,
        "catalogErrors": errors,
    }


def _count_rows(result: dict) -> int:
    """从平台统一返回结构中统计条目数量。

    优先使用 data.total，其次 data.rows 长度，兼容 data 直接为列表。
    """
    data = result.get("data")
    if isinstance(data, dict):
        total = data.get("total")
        if isinstance(total, int):
            return total
        rows = data.get("rows")
        if isinstance(rows, list):
            return len(rows)
    if isinstance(data, list):
        return len(data)
    return 0


def _read_showcase_cache() -> dict | None:
    """读取 showcase 平台统计缓存，缺失或损坏返回 None。"""
    if not SHOWCASE_CACHE_PATH.exists():
        return None
    try:
        data = json.loads(SHOWCASE_CACHE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if isinstance(data, dict) and isinstance(data.get("platform"), dict):
        return data
    return None


def _write_showcase_cache(payload: dict) -> None:
    """写入 showcase 平台统计缓存（原子替换）；失败不阻塞请求。"""
    try:
        tmp = SHOWCASE_CACHE_PATH.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, SHOWCASE_CACHE_PATH)
    except OSError:
        pass


# ── Stats 事件计数持久化 ──


_DEFAULT_STATS: dict[str, int] = {
    "scriptsGenerated": 19,
    "testTotal": 0,
    "testPassed": 0,
    "testFailed": 0,
}


def _load_stats() -> dict[str, int]:
    """读取 .stats.json，不存在或解析失败时返回默认值。"""
    try:
        raw = json.loads(STATS_PATH.read_text(encoding="utf-8"))
        return {**_DEFAULT_STATS, **raw}
    except (OSError, json.JSONDecodeError):
        return dict(_DEFAULT_STATS)


def _save_stats(stats: dict[str, int]) -> None:
    """原子写入 .stats.json。"""
    tmp = STATS_PATH.with_suffix(".tmp")
    try:
        tmp.write_text(
            json.dumps(stats, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, STATS_PATH)
    except OSError:
        pass


_TEST_COUNT_KEYS = ("testPassed", "testFailed", "testErrors", "testSkipped")
_test_report_fallback: dict | None = None
_test_refresh_lock = threading.Lock()


def _unavailable_test_report(status: str = "UNAVAILABLE") -> dict:
    """返回不可用测试结果，未知数量不用零代替。"""
    return {
        "testScope": "mcp_server/tests", "testAvailable": False,
        "testStatus": status, "testRunAt": None, "testTotal": None,
        **dict.fromkeys(_TEST_COUNT_KEYS), "testSuites": [],
    }


def _load_server_test_report() -> dict:
    """只读取完整服务端报告，不使用旧事件文件中的映射核心计数。"""
    try:
        raw = _test_report_fallback
        if raw is None:
            raw = json.loads(SERVER_TEST_REPORT_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("testScope") != "mcp_server/tests":
            raise ValueError("测试报告范围不匹配")
        if raw.get("testAvailable") is not True:
            status = raw.get("testStatus")
            return _unavailable_test_report(
                status if status in ("RUNNING", "INTERRUPTED") else "UNAVAILABLE",
            )
        counts = [raw[key] for key in ("testTotal", *_TEST_COUNT_KEYS)]
        if any(isinstance(n, bool) or not isinstance(n, int) or n < 0 for n in counts):
            raise ValueError("测试数量无效")
        if counts[0] == 0 or counts[0] != sum(counts[1:]):
            raise ValueError("测试数量不一致")
        if datetime.fromisoformat(raw["testRunAt"]).tzinfo is None:
            raise ValueError("测试报告时间缺少时区")
        suites = raw["testSuites"]
        if not isinstance(suites, list) or any(
            not isinstance(s, dict) or not isinstance(s.get("name"), str)
            or not s["name"] or isinstance(s.get("total"), bool)
            or not isinstance(s.get("total"), int) or s["total"] <= 0
            for s in suites
        ):
            raise ValueError("测试模块统计无效")
        if sum(s["total"] for s in suites) != raw["testTotal"]:
            raise ValueError("测试模块总数不一致")
        result = {key: raw[key] for key in _unavailable_test_report()}
        result["testSuites"] = [{"name": s["name"], "total": s["total"]} for s in suites]
        result["testStatus"] = "FAILED" if raw["testFailed"] or raw["testErrors"] else "PASSED"
        return result
    except (OSError, ValueError, TypeError, KeyError):
        return _unavailable_test_report()


def _save_server_test_report(report: dict) -> None:
    """原子保存脱敏报告，落盘失败时保留当前进程的真实状态。"""
    global _test_report_fallback
    tmp = SERVER_TEST_REPORT_PATH.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, SERVER_TEST_REPORT_PATH)
        _test_report_fallback = None
    except OSError:
        _test_report_fallback = copy.deepcopy(report)
        print("[WARNING] 服务端测试报告无法落盘，当前进程使用内存结果。")


def _parse_server_test_xml(path: Path, returncode: int) -> dict:
    """汇总完整 pytest JUnit 报告，按用例去重并优先记为错误。"""
    if returncode not in (0, 1):
        return _unavailable_test_report("INTERRUPTED")
    root = ET.parse(path).getroot()
    cases = {}
    priorities = {"testPassed": 0, "testSkipped": 1, "testFailed": 2, "testErrors": 3}
    for case in root.iter("testcase"):
        key = (case.get("classname", ""), case.get("name", ""))
        if not all(key):
            raise ValueError("测试用例标识缺失")
        outcome = "testPassed"
        for tag, category in (("skipped", "testSkipped"), ("failure", "testFailed"),
                              ("error", "testErrors")):
            if case.find(tag) is not None:
                outcome = category
        # pytest 可为同一用例分别记录调用失败和清理错误，不能计为两项。
        if key not in cases or priorities[outcome] > priorities[cases[key]]:
            cases[key] = outcome
    if not cases:
        return _unavailable_test_report()
    counts = {key: list(cases.values()).count(key) for key in _TEST_COUNT_KEYS}
    if (returncode == 0) != (counts["testFailed"] + counts["testErrors"] == 0):
        raise ValueError("测试退出码与报告不一致")
    suites = {}
    for classname, _ in cases:
        parts = classname.split(".")
        module = next((part for part in parts if part.startswith("test_")), classname)
        suites[module] = suites.get(module, 0) + 1
    return {
        "testScope": "mcp_server/tests", "testAvailable": True,
        "testStatus": "PASSED" if returncode == 0 else "FAILED",
        "testRunAt": datetime.now(timezone.utc).isoformat(),
        "testTotal": len(cases), **counts,
        "testSuites": [{"name": name, "total": total} for name, total in sorted(suites.items())],
    }


def _run_startup_tests() -> dict:
    """完整运行服务端回归，使用结构化报告且不接受筛选或提前停止。"""
    if not (SCRIPT_DIR / "tests").is_dir():
        return _unavailable_test_report()
    env = dict(os.environ)
    env.pop("PYTEST_ADDOPTS", None)
    try:
        with tempfile.TemporaryDirectory(prefix="pca-server-tests-") as folder:
            report_path = Path(folder) / "results.xml"
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", str(SCRIPT_DIR / "tests"),
                 "-o", "addopts=", "--maxfail=0", "--tb=no", "-q",
                 "--junitxml", str(report_path)],
                capture_output=True, timeout=180, cwd=str(PROJECT_ROOT), env=env,
            )
            return _parse_server_test_xml(report_path, proc.returncode)
    except subprocess.TimeoutExpired:
        return _unavailable_test_report("INTERRUPTED")
    except (OSError, ValueError, ET.ParseError):
        return _unavailable_test_report()


def _refresh_startup_test_report() -> None:
    """在独立线程中更新报告，不阻塞服务、不重复运行、不触碰事件计数。"""
    if not _test_refresh_lock.acquire(blocking=False):
        return
    try:
        _save_server_test_report(_unavailable_test_report("RUNNING"))
        try:
            report = _run_startup_tests()
        except Exception:
            # 自检异常不得影响业务服务，也不得把部分测试当作完整结果。
            report = _unavailable_test_report("INTERRUPTED")
        _save_server_test_report(report)
        print(f"[INFO] 服务端回归状态: {report['testStatus']}, 用例数: {report['testTotal']}")
    finally:
        _test_refresh_lock.release()


async def _query_platform_stats(token: str) -> dict:
    """查询平台大类/设备类型/品牌/规约计数。

    优先用传入的系统 Token；若平台返回认证失效，则通过
    _call_platform 透明刷新系统 Token 后重试，避免 Token 过期
    导致展示页长期停留在降级模式。

    Args:
        token: 云端业务 Token。

    Returns:
        含 classifyCount、deviceTypeCount、brandCount、protocolCount 的字典。

    Raises:
        RuntimeError: 任一查询返回错误或认证失效时。
    """
    methods = (
        api_client.get_classify_list,
        api_client.get_device_type_list,
        api_client.get_brand_list,
        api_client.get_protocol_info_list,
    )
    keys = ("classifyCount", "deviceTypeCount", "brandCount", "protocolCount")
    results: list[dict] = []
    for method in methods:
        result = await method(token)
        if is_auth_expired(result):
            # 系统 Token 已过期，走透明刷新重试（与工具调用同链路）
            result = await _call_platform(method)
        results.append(result)
    stats: dict[str, int] = {}
    for key, result in zip(keys, results):
        if not isinstance(result, dict) or result.get("error"):
            reason = (result or {}).get("message", "平台查询失败")
            raise RuntimeError(str(reason))
        stats[key] = _count_rows(result)
    return stats


SHOWCASE_CACHE_TTL = 60
_showcase_platform_result: dict | None = None
_showcase_platform_expires = 0.0
_showcase_platform_task: asyncio.Task | None = None


async def _refresh_showcase_platform() -> dict:
    """刷新平台统计并保留真实采样时间，失败时回退最近成功缓存。"""
    global _showcase_platform_result, _showcase_platform_expires
    token = system_token_mgr.get_token()
    reason = "服务端系统 Token 不可用"
    if token:
        try:
            stats = await asyncio.wait_for(_query_platform_stats(token), timeout=25)
        except Exception:
            # 对外不回显后端异常，避免异常携带请求凭证。
            reason = "平台统计查询失败或超时"
        else:
            result = {
                "platform": {"available": True, **stats}, "dataSource": "live",
                "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "degraded": False, "degradeReason": "",
            }
            _write_showcase_cache({
                "platform": result["platform"], "updatedAt": result["updatedAt"],
            })
            _showcase_platform_result = result
            _showcase_platform_expires = time.monotonic() + SHOWCASE_CACHE_TTL
            return result
    cached = _read_showcase_cache()
    result = {
        "platform": cached["platform"] if cached else {"available": False},
        "dataSource": "cache" if cached else "static",
        "updatedAt": cached.get("updatedAt") if cached else None,
        "degraded": True,
        "degradeReason": reason + ("，展示最近成功缓存" if cached else "，无历史缓存"),
    }
    _showcase_platform_result = result
    _showcase_platform_expires = time.monotonic() + SHOWCASE_CACHE_TTL
    return result


async def _get_showcase_platform() -> dict:
    """合并并发平台查询，客户端取消请求不取消共享刷新任务。"""
    global _showcase_platform_task
    if _showcase_platform_result is not None and time.monotonic() < _showcase_platform_expires:
        result = copy.deepcopy(_showcase_platform_result)
        if result["dataSource"] == "live":
            result["dataSource"] = "cache"
        return result
    task = _showcase_platform_task
    if task is None or task.done() or task.get_loop() is not asyncio.get_running_loop():
        task = asyncio.create_task(_refresh_showcase_platform())
        _showcase_platform_task = task
    return copy.deepcopy(await asyncio.shield(task))


async def _build_showcase_data() -> dict:
    """汇总 showcase 页面展示数据。

    工具、Skill 和顶层方向由本地目录汇总，声明异常单独标记不可用。
    平台规约、品牌、设备类型和大类计数使用短缓存，失败回退历史缓存。
    平台不可用不影响本地能力目录，采样时间和降级原因一并返回。

    Returns:
        showcase 展示数据字典。
    """
    server_version = _load_server_version()
    package_manifest = _load_package_manifest()
    tools = _public_tool_catalog()

    data: dict = {
        "toolCount": len(tools),
        "tools": tools,
        "domainCount": len({tool["domain"] for tool in tools}),
        "clients": copy.deepcopy(CLIENT_DEFINITIONS),
        "clientCount": len(CLIENT_DEFINITIONS),
        **_skill_capabilities(package_manifest),
        "serverVersion": server_version["version"],
        "packageName": package_manifest.get("name", "xlpa-agent-assets"),
        "packageVersion": package_manifest.get("version", "unknown"),
        "platform": {"available": False},
        "dataSource": "static",
        "updatedAt": None,
        "degraded": True,
        "degradeReason": "",
    }
    if server_version.get("versionError"):
        data["serverVersionError"] = server_version["versionError"]

    # 合并本地事件计数
    local_stats = _load_stats()
    data["scriptsGenerated"] = local_stats["scriptsGenerated"]
    data.update(_load_server_test_report())

    data.update(await _get_showcase_platform())
    return data


# ── 工具实现 ──


@mcp.tool()
def list_mcp_tools() -> dict:
    """列出当前 MCP 服务器支持的所有工具及其状态，同时用于鉴权探测。

    返回包含服务器信息、鉴权状态、权限级别、完整工具列表、
    MCP Server 版本、Agent 资源包版本、manifest 校验状态和
    服务器支持的特性列表（capabilities）。
    安装验证时调用此工具探测 Token 是否有效及当前权限级别。
    """
    package_manifest = _load_package_manifest()
    package_validation = _validate_package_manifest(package_manifest)
    server_version = _load_server_version()
    result = {
        "server": server_version["serverName"],
        "version": server_version["version"],
        "resource_package": {
            "name": package_manifest.get("name", "xlpa-agent-assets"),
            "version": package_manifest.get("version", "unknown"),
            "kind": package_manifest.get("kind", "agent-assets-package"),
            "manifest_path": "skills/package-manifest.json",
            "validation": package_validation,
        },
        "capabilities": [
            "persistent_user_token",
            "function_type_atomic_tag",
            "capability_matrix_report",
            "user_only_mcp_access",
            "super_account_cloud_write",
            "edge_device_archiving",
            "edge_parameter_save_readback",
            "edge_persistent_stage_report",
            "edge_explicit_deploy_scope_guard",
            "archive_chunked_upload",
            "edge_batch_archive",
            "edge_execute_batching",
        ],
        "capability_matrix": [
            {
                "capability": "mcp_access",
                "status": "available",
                "requires": "有效 MCP 接入 Token（一律 user 级）",
            },
            {
                "capability": "cloud_read",
                "status": "conditional",
                "requires": "云端业务 Token（login 获取）",
            },
            {
                "capability": "cloud_write",
                "status": "conditional",
                "requires": "云端业务 Token + 命中超级账号配置 + 用户逐项确认",
            },
            {
                "capability": "edge_archive_dry_run",
                "status": "conditional",
                "requires": "自动建档 Excel 任务凭据",
            },
            {
                "capability": "edge_archive_write",
                "status": "conditional",
                "requires": "边缘任务凭据 + 当前plan_id + 独立确认 + 写后回读",
            },
            {
                "capability": "edge_gateway_clock",
                "status": "conditional",
                "requires": "当前plan_id + 档案/参数回读成功 + 独立确认；不校时",
            },
            {
                "capability": "edge_param_deploy",
                "status": "available",
                "requires": "rtnCode=0表示下发成功",
            },
            {
                "capability": "edge_monitor_debug",
                "status": "available",
                "requires": "rtnCode=0表示召测成功",
            },
            {
                "capability": "edge_task_report",
                "status": "conditional",
                "requires": "所属MCP身份与有效期内持久报告；不依赖内存会话",
            },
            {
                "capability": "archive_chunked_upload",
                "status": "available",
                "requires": "upload_device_archive_template 分块入参；单次上传保持向后兼容",
            },
            {
                "capability": "edge_batch_archive",
                "status": "available",
                "requires": "建档/挂载/参数保存工具 node_keys 批量入参；单节点保持向后兼容",
            },
            {
                "capability": "edge_execute_batching",
                "status": "available",
                "requires": "execute_archive_task 的 batch_size/budget/cursor 分批与断点续跑；缺省一次跑完向后兼容",
            },
        ],
        "auth": {
            "token_required": True,
            "token_valid": True,
            "access_level": access_level_var.get(),
            "source": source_var.get(),
            "cloud_write_source": "业务登录账号命中超级账号配置",
        },
        "total": len(TOOL_DEFINITIONS),
        "tools": TOOL_DEFINITIONS,
    }
    if server_version.get("versionError"):
        result["version_error"] = server_version["versionError"]
    return result


def _is_system_login(phoneNum: str) -> bool:
    """判定登录账号是否为系统（super）角色：内置账号或 superAccounts 双源。

    Args:
        phoneNum: login 提交的手机号。

    Returns:
        命中内置账号或配置白名单返回 True，否则 False。
    """
    if phoneNum and phoneNum == system_token_mgr.phone:
        return True
    return super_account_config.is_super({"phone": phoneNum})


@mcp.tool()
async def login(phoneNum: str, code: str) -> dict:
    """手机号+验证码登录，验证身份并确定权限角色。

    登录成功不返回业务 Token，仅返回角色信息。
    服务端内部使用系统 Token 调用平台 API，写操作需超级账号。

    Args:
        phoneNum: 手机号
        code: 短信验证码（不会过期）
    """
    result = await api_client.login(phoneNum, code)
    if result.get("error"):
        return {
            "success": False,
            "error": "LOGIN_FAILED",
            "message": "登录失败：账号或验证码错误。",
        }

    data = result.get("data")
    identity = extract_account_identity(data if isinstance(data, dict) else {})
    user_token = identity.get("token")

    # 判定角色：内置账号或 superAccounts 双源命中即 system
    is_super = _is_system_login(phoneNum)
    role = "super" if is_super else "user"

    # 获取当前 MCP 接入 Token 并创建 session
    mcp_token = mcp_token_var.get("")
    session = session_registry.create(
        mcp_token=mcp_token,
        phone=phoneNum,
        role=role,
        fallback_token=user_token if not is_super else None)

    # 开启本次操作会话窗：生成 trace_id 并绑定到该身份
    trace_id = _op_store.next_trace_id()
    session.trace_id = trace_id
    _op_store.set_current_trace(derive_owner_id(mcp_token), trace_id)

    # 超级账号 + 系统 Token 失效时用客户端参数刷新（更新并持久化内置凭据）
    if is_super and not system_token_mgr.active:
        refreshed = await system_token_mgr.aupdate_credentials(phoneNum, code)
        if refreshed:
            msg = "已授权，系统账号（系统 Token 已用您的凭据刷新）"
        else:
            msg = "已授权，系统账号（系统 Token 仍不可用）"
    elif is_super:
        msg = "已授权，系统账号"
    else:
        msg = "已登录，只读权限"

    return {
        "success": True,
        "role": role,
        "message": msg,
    }


# ── 大类管理 ──


@mcp.tool()
async def get_classify_list(
    sysName: str = "", pageIndex: int = 1, pageSize: int = 9999
) -> dict:
    """查询大类列表（返回的 id 即大类编号 classNum 来源）。

    Args:
        sysName: 大类名称（模糊搜索，为空查全部）
        pageIndex: 当前页码
        pageSize: 每页条数
    """
    session = _require_session()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.get_classify_list, sysName, pageIndex, pageSize)


@mcp.tool()
async def add_classify(sysName: str) -> dict:
    """新增大类。

    Args:
        sysName: 大类名称
    """
    session = _require_super()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.add_classify, sysName)


@mcp.tool()
async def update_classify(classify_id: int, sysName: str) -> dict:
    """更新大类。

    Args:
        classify_id: 大类 ID
        sysName: 大类名称
    """
    session = _require_super()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.update_classify, classify_id, sysName)


@mcp.tool()
async def del_classify(classify_id: int, sysName: str) -> dict:
    """删除大类。

    Args:
        classify_id: 大类 ID
        sysName: 大类名称
    """
    session = _require_super()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.del_classify, classify_id, sysName)


# ── 设备类型管理 ──


@mcp.tool()
async def get_device_type_list(
    deviceTypeName: str = "",
    deviceTypeCode: str = "",
    sysId: int = -1,
    pageIndex: int = 1,
    pageSize: int = 9999) -> dict:
    """查询设备类型列表（deviceTypeCode 即 modelNum 来源）。

    Args:
        deviceTypeName: 类型名称（模糊搜索，为空查全部）
        deviceTypeCode: 类型编码
        sysId: 所属大类 ID，-1 表示全部
        pageIndex: 当前页码
        pageSize: 每页条数
    """
    session = _require_session()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.get_device_type_list, deviceTypeName, deviceTypeCode, sysId, pageIndex, pageSize
    )


@mcp.tool()
async def add_device_type(
    deviceTypeName: str, deviceTypeCode: str, sysId: int
) -> dict:
    """新增设备类型。

    Args:
        deviceTypeName: 类型名称
        deviceTypeCode: 类型编码（纯数字）
        sysId: 所属大类 ID
    """
    session = _require_super()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.add_device_type, deviceTypeName, deviceTypeCode, sysId)


@mcp.tool()
async def update_device_type(
    device_type_id: int,
    deviceTypeName: str,
    deviceTypeCode: str,
    sysId: int) -> dict:
    """更新设备类型。

    Args:
        device_type_id: 设备类型记录 ID
        deviceTypeName: 类型名称
        deviceTypeCode: 类型编码
        sysId: 所属大类 ID
    """
    session = _require_super()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.update_device_type, device_type_id, deviceTypeName, deviceTypeCode, sysId
    )


@mcp.tool()
async def del_device_type(device_type_id: int) -> dict:
    """删除设备类型。

    Args:
        device_type_id: 设备类型记录 ID
    """
    session = _require_super()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.del_device_type, device_type_id)


# ── 品牌管理 ──


@mcp.tool()
async def get_brand_list(
    nameCN: str = "",
    code: str = "",
    deviceTypeId: int = -1,
    pageIndex: int = 1,
    pageSize: int = 9999) -> dict:
    """查询品牌列表。

    Args:
        nameCN: 品牌名称-中文（模糊搜索，为空查全部）
        code: 品牌编码
        deviceTypeId: 所属设备类型 ID，-1 表示全部
        pageIndex: 当前页码
        pageSize: 每页条数
    """
    session = _require_session()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.get_brand_list, nameCN, code, deviceTypeId, pageIndex, pageSize
    )


@mcp.tool()
async def add_brand(
    nameCN: str, name: str, code: str, deviceTypeId: int
) -> dict:
    """新增品牌。

    Args:
        nameCN: 品牌名称-中文
        name: 品牌名称-英文（禁止中文）
        code: 品牌编码
        deviceTypeId: 所属设备类型 ID
    """
    session = _require_super()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.add_brand, nameCN, name, code, deviceTypeId)


@mcp.tool()
async def update_brand(
    brand_id: int, nameCN: str, name: str, code: str, deviceTypeId: int
) -> dict:
    """更新品牌。

    Args:
        brand_id: 品牌记录 ID
        nameCN: 品牌名称-中文
        name: 品牌名称-英文
        code: 品牌编码
        deviceTypeId: 所属设备类型 ID
    """
    session = _require_super()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.update_brand, brand_id, nameCN, name, code, deviceTypeId)


@mcp.tool()
async def del_brand(brand_id: int, name: str, code: str) -> dict:
    """删除品牌。

    Args:
        brand_id: 品牌记录 ID
        name: 品牌名称-英文
        code: 品牌编码
    """
    session = _require_super()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.del_brand, brand_id, name, code)


# ── 型号管理 ──


@mcp.tool()
async def get_model_list(
    name: str = "",
    brandId: int = -1,
    pageIndex: int = 1,
    pageSize: int = 9999) -> dict:
    """查询型号列表。

    Args:
        name: 型号名称（模糊搜索，为空查全部）
        brandId: 所属品牌 ID，-1 表示全部
        pageIndex: 当前页码
        pageSize: 每页条数
    """
    session = _require_session()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.get_model_list, name, brandId, pageIndex, pageSize)


@mcp.tool()
async def add_model(name: str, brandId: int) -> dict:
    """新增型号。

    Args:
        name: 型号名称
        brandId: 所属品牌 ID
    """
    session = _require_super()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.add_model, name, brandId)


@mcp.tool()
async def update_model(model_id: int, name: str, brandId: int) -> dict:
    """更新型号。

    Args:
        model_id: 型号记录 ID
        name: 型号名称
        brandId: 所属品牌 ID
    """
    session = _require_super()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.update_model, model_id, name, brandId)


@mcp.tool()
async def del_model(model_id: int) -> dict:
    """删除型号。

    Args:
        model_id: 型号记录 ID
    """
    session = _require_super()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.del_model, model_id)


@mcp.tool()
async def export_model_data() -> dict:
    """导出型号统计数据（文件流，返回 Base64 内容）。
    """
    session = _require_session()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.export_model_data)


# ── 规约信息 ──


@mcp.tool()
async def get_protocol_info_list(
    name: str = "",
    classifyId: Optional[int] = None,
    deviceTypeId: Optional[int] = None,
    brandId: Optional[int] = None,
    modelId: Optional[int] = None,
    pageIndex: int = 1,
    pageSize: int = 9999) -> dict:
    """查询规约列表（支持四级分类过滤）。

    Args:
        name: 规约名称（模糊搜索，空串查全部）
        classifyId: 大类 ID（可选过滤）
        deviceTypeId: 设备类型 ID（可选过滤）
        brandId: 品牌 ID（可选过滤）
        modelId: 型号 ID（可选过滤）
        pageIndex: 当前页码
        pageSize: 每页条数
    """
    session = _require_session()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.get_protocol_info_list, name, classifyId, deviceTypeId, brandId, modelId, pageIndex, pageSize
    )


@mcp.tool()
async def add_protocol_info(
    protocolName: str,
    protoType: int,
    classifyId: int,
    deviceTypeId: int,
    brandId: int,
    modelId: int,
    protocolFiles: Optional[list] = None) -> dict:
    """新增规约。

    Args:
        protocolName: 规约名称
        protoType: 规约类型（1=Modbus）
        classifyId: 大类 ID
        deviceTypeId: 设备类型 ID
        brandId: 品牌 ID
        modelId: 型号 ID
        protocolFiles: 规约文档文件列表（可选）
    """
    session = _require_super()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.add_protocol_info, protocolName, protoType, classifyId, deviceTypeId, brandId, modelId,
        protocolFiles)


@mcp.tool()
async def update_protocol(
    protocol_id: int,
    protocolName: str,
    protoType: int,
    classifyId: int,
    deviceTypeId: int,
    brandId: int,
    modelId: int,
    protocolFiles: Optional[list] = None) -> dict:
    """更新规约。

    Args:
        protocol_id: 规约 ID
        protocolName: 规约名称
        protoType: 规约类型
        classifyId: 大类 ID
        deviceTypeId: 设备类型 ID
        brandId: 品牌 ID
        modelId: 型号 ID
        protocolFiles: 规约文档文件列表（可选）
    """
    session = _require_super()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.update_protocol, protocol_id, protocolName, protoType, classifyId, deviceTypeId,
        brandId, modelId, protocolFiles)


@mcp.tool()
async def del_protocol_info(protocol_id: int, protocolName: str) -> dict:
    """删除规约。

    Args:
        protocol_id: 规约 ID
        protocolName: 规约名称
    """
    session = _require_super()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.del_protocol_info, protocol_id, protocolName)


@mcp.tool()
async def del_protocol_file(file_id: int) -> dict:
    """删除规约文档文件。

    Args:
        file_id: 文件 ID
    """
    session = _require_super()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.del_protocol_file, file_id)


@mcp.tool()
async def upload_protocol_file(
    file_name: str, file_content_base64: str
) -> dict:
    """上传规约文档文件。

    Args:
        file_name: 上传文件名
        file_content_base64: 文件内容的 Base64 编码字符串
    """
    session = _require_super()
    if isinstance(session, dict):
        return session
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
    return await _call_platform(api_client.upload_protocol_file, file_name, content)


# ── 数据项（按规约查询采集点位配置） ──


@mcp.tool()
async def get_data_item_list(
    protocolId: int, protoType: int, pageIndex: int = 1, pageSize: int = 9999
) -> dict:
    """查询协议数据项列表（按规约查询采集点位配置）。

    注意：原子标签/功能项查询请使用 get_function_type_list（API-E10）。

    Args:
        protocolId: 规约 ID
        protoType: 规约类型（1=Modbus）
        pageIndex: 当前页码
        pageSize: 每页条数
    """
    session = _require_session()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.get_data_item_list, protocolId, protoType, pageIndex, pageSize
    )


@mcp.tool()
async def add_data_item(data: dict) -> dict:
    """新增协议数据项（首期仅基础信息，不含寄存器配置）。

    Args:
        data: 数据项参数字典
    """
    session = _require_super()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.add_data_item, data)


@mcp.tool()
async def update_data_item(data: dict) -> dict:
    """更新协议数据项。

    Args:
        data: 数据项参数字典
    """
    session = _require_super()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.update_data_item, data)


@mcp.tool()
async def del_data_item(data: dict) -> dict:
    """删除协议数据项。

    Args:
        data: 数据项参数字典
    """
    session = _require_super()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.del_data_item, data)


# ── 脚本管理 ──


@mcp.tool()
async def gen_script(data: dict) -> dict:
    """生成脚本。

    Args:
        data: 脚本生成参数字典
    """
    session = _require_super()
    if isinstance(session, dict):
        return session
    result = await _call_platform(api_client.gen_script, data)
    # 成功时递增 scriptsGenerated 计数
    if isinstance(result, dict) and not result.get("error"):
        stats = _load_stats()
        stats["scriptsGenerated"] = stats.get("scriptsGenerated", 19) + 1
        _save_stats(stats)
    return result


@mcp.tool()
async def get_script_list(protocolId: int, protoType: int) -> dict:
    """查询脚本列表。

    Args:
        protocolId: 规约 ID
        protoType: 规约类型
    """
    session = _require_session()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.get_script_list, protocolId, protoType)


@mcp.tool()
async def get_json_detail(data: dict) -> dict:
    """获取脚本 JSON 内容。

    Args:
        data: 请求参数字典（含脚本 ID 等）
    """
    session = _require_session()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.get_json_detail, data)


@mcp.tool()
async def del_script(data: dict) -> dict:
    """删除脚本。

    Args:
        data: 删除参数字典
    """
    session = _require_super()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.del_script, data)


@mcp.tool()
async def export_data(protocolId: int) -> dict:
    """导出协议数据项（文件流，返回 Base64 内容）。

    Args:
        protocolId: 规约 ID
    """
    session = _require_session()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.export_data, protocolId)


# ── 系数管理 ──


@mcp.tool()
async def get_coeff_list(protocolId: int, dataItemId: int) -> dict:
    """查询数据项系数列表。

    Args:
        protocolId: 规约 ID
        dataItemId: 数据项 ID
    """
    session = _require_session()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.get_coeff_list, protocolId, dataItemId)


@mcp.tool()
async def add_coeff(data: dict) -> dict:
    """新增数据项系数。

    Args:
        data: 系数参数字典
    """
    session = _require_super()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.add_coeff, data)


@mcp.tool()
async def update_coeff(data: dict) -> dict:
    """更新数据项系数。

    Args:
        data: 系数参数字典
    """
    session = _require_super()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.update_coeff, data)


@mcp.tool()
async def del_coeff(data: dict) -> dict:
    """删除数据项系数。

    Args:
        data: 系数参数字典
    """
    session = _require_super()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.del_coeff, data)


# ── 感知管理 ──


@mcp.tool()
async def get_sense_list(data: dict) -> dict:
    """查询感知结构列表。

    Args:
        data: 请求参数字典
    """
    session = _require_session()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.get_sense_list, data)


@mcp.tool()
async def add_sense(data: dict) -> dict:
    """新增感知结构。

    Args:
        data: 感知参数字典
    """
    session = _require_super()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.add_sense, data)


@mcp.tool()
async def update_sense(data: dict) -> dict:
    """更新感知结构。

    Args:
        data: 感知参数字典
    """
    session = _require_super()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.update_sense, data)


@mcp.tool()
async def del_sense(data: dict) -> dict:
    """删除感知结构。

    Args:
        data: 感知参数字典
    """
    session = _require_super()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.del_sense, data)


# ── 规约类型（字典） ──


@mcp.tool()
async def get_protocol_type_list(
    name: str = "",
    dictItemCode: str = "",
    dictTypeCode: str = "protocolType",
    pageIndex: int = 1,
    pageSize: int = 9999) -> dict:
    """查询规约类型字典分页列表。

    Args:
        name: 字典项名称（模糊搜索，为空查全部）
        dictItemCode: 字典项编码
        dictTypeCode: 字典类型编码，规约类型固定 protocolType
        pageIndex: 当前页码
        pageSize: 每页条数
    """
    session = _require_session()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.get_protocol_type_list, name, dictItemCode, dictTypeCode, pageIndex, pageSize
    )


@mcp.tool()
async def save_protocol_type(
    name: str, dictItemCode: str, dictTypeCode: str = "protocolType",
    type_id: int = 0) -> dict:
    """保存规约类型字典项（新增/编辑共用）。

    Args:
        name: 字典项名称
        dictItemCode: 字典项编码
        dictTypeCode: 字典类型编码，固定 protocolType
        type_id: 字典项 ID，新增时为 0
    """
    session = _require_super()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.save_protocol_type, name, dictItemCode, dictTypeCode, type_id
    )


@mcp.tool()
async def del_protocol_type(type_id: int) -> dict:
    """删除规约类型字典项。

    Args:
        type_id: 字典项 ID
    """
    session = _require_super()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.del_protocol_type, type_id)


# ── 功能项管理（原子标签查询入口，API-E10） ──


@mcp.tool()
async def get_function_type_list(
    functionTypeName: str = "",
    functionCode: str = "",
    pageIndex: int = 1,
    pageSize: int = 9999) -> dict:
    """查询功能项列表（原子标签查询入口，API-E10 GetProtocoFunctionTypeList）。

    MODBUS 原子标签匹配应优先使用本工具查询平台功能项候选，
    而不是 get_data_item_list。

    Args:
        functionTypeName: 功能项名称（模糊搜索，为空查全部）
        functionCode: 功能码
        pageIndex: 当前页码
        pageSize: 每页条数
    """
    session = _require_session()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.get_function_type_list, functionTypeName, functionCode, pageIndex, pageSize
    )


@mcp.tool()
async def save_function_item(data: dict) -> dict:
    """保存功能项（新增/编辑共用）。

    Args:
        data: 功能项参数字典
    """
    session = _require_super()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.save_function_item, data)


@mcp.tool()
async def del_function_item(functionId: int) -> dict:
    """删除功能项。

    Args:
        functionId: 功能项 ID
    """
    session = _require_super()
    if isinstance(session, dict):
        return session
    return await _call_platform(api_client.del_function_item, functionId)


# ── 写操作日志：trace 会话窗、采集与内联（云端写工具 + login） ──

_op_store = default_store()

# 需在 server 侧包裹记录的写工具：协议管理层 write 类 + login。
# 边缘 edge_write 类由 edge_tools._tracked_action 内部记录，避免重复。
_CLOUD_WRITE_TOOL_NAMES = frozenset(
    d["name"] for d in TOOL_DEFINITIONS if d.get("type") == "write"
) | {"login"}


def _current_owner_id_server() -> str:
    """由当前 MCP 接入 Token 派生归属身份摘要。"""
    return derive_owner_id(mcp_token_var.get(""))


def _classify_write_result(result: Any) -> tuple[str, str]:
    """从工具返回体判定写操作状态与业务码。

    Args:
        result: 工具返回（通常为 dict）。

    Returns:
        ``(status, code)``，status 取值 SUCCESS/ERROR/PARTIAL/UNVERIFIED/UNKNOWN。
    """
    if not isinstance(result, dict):
        return "UNKNOWN", ""
    stage = str(result.get("stage_state") or "")
    if stage:
        mapping = {
            "SUCCEEDED": "SUCCESS", "PARTIAL": "PARTIAL", "FAILED": "ERROR",
            "BLOCKED": "ERROR", "UNVERIFIED": "UNVERIFIED",
        }
        return mapping.get(stage, "UNKNOWN"), stage
    if result.get("success") is True:
        return "SUCCESS", ""
    if result.get("success") is False or result.get("error") is True:
        return "ERROR", str(result.get("code") or result.get("error") or "")
    if result.get("error") is False or result.get("ok") is True:
        return "SUCCESS", ""
    if result.get("ok") is False:
        return "ERROR", str(result.get("code") or "")
    return "UNKNOWN", ""


def _record_write_call(
    tool_name: str, arguments: dict, result: Any,
    started_at: str, duration_ms: int, secrets_: tuple[str, ...] = (),
) -> dict:
    """记录一次写操作并返回用于内联的摘要；失败时 fail-open 返回空。"""
    try:
        status, code = _classify_write_result(result)
        entry = _op_store.record(
            mcp_token=mcp_token_var.get(""),
            tool=tool_name, status=status, code=code,
            args=arguments, result=result,
            source=source_var.get(), access_level=access_level_var.get(),
            duration_ms=duration_ms, started_at=started_at, secrets_=secrets_,
        )
        return {
            "entry_id": entry.entry_id, "trace_id": entry.trace_id,
            "status": entry.status, "code": entry.code,
            "duration_ms": entry.duration_ms,
        }
    except Exception as exc:  # noqa: BLE001 - 日志子系统不得影响业务
        print(f"[WARNING] 写操作日志记录失败({tool_name}): {exc}")
        return {}


def _wrap_logged_tool(name: str, fn, is_async: bool):
    """按原函数同步/异步属性包裹一层写操作记录逻辑。"""
    if is_async:
        @functools.wraps(fn)
        async def wrapper(**kwargs):
            started_at = datetime.now(timezone.utc).isoformat()
            t0 = time.perf_counter()
            result = await fn(**kwargs)
            duration_ms = int((time.perf_counter() - t0) * 1000)
            inline = _record_write_call(name, kwargs, result, started_at, duration_ms)
            if inline and isinstance(result, dict):
                result.setdefault("operation_log", inline)
            return result
        return wrapper

    @functools.wraps(fn)
    def wrapper(**kwargs):
        started_at = datetime.now(timezone.utc).isoformat()
        t0 = time.perf_counter()
        result = fn(**kwargs)
        duration_ms = int((time.perf_counter() - t0) * 1000)
        inline = _record_write_call(name, kwargs, result, started_at, duration_ms)
        if inline and isinstance(result, dict):
            result.setdefault("operation_log", inline)
        return result
    return wrapper


def install_write_operation_logging() -> int:
    """为云端写工具与 login 装配记录 handler，返回被包裹的工具数。"""
    tool_manager = getattr(mcp, "_tool_manager", None)
    if tool_manager is None:
        print("[WARNING] 无法访问工具管理器，写操作日志未启用。")
        return 0
    wrapped = 0
    for name in _CLOUD_WRITE_TOOL_NAMES:
        tool = tool_manager.get_tool(name)
        if tool is None or getattr(tool, "fn", None) is None:
            continue
        tool.fn = _wrap_logged_tool(name, tool.fn, bool(tool.is_async))
        wrapped += 1
    return wrapped


# 本模块所有 @mcp.tool() 已注册，装配云端写工具的记录 handler。
install_write_operation_logging()


# ── ASGI 鉴权中间件 ──


class AuthMiddleware:
    """纯 ASGI 中间件，负责 MCP 接入 Token 验证。

    - Token 验证：所有 /mcp 请求必须携带 Authorization: Bearer <TOKEN>
    - 接入级别：一律 user；localhost / 本机 IP 不再自动获得云端写权限
    - 使用 contextvars 传递接入级别与来源信息到工具函数
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
        # 存储原始 MCP Token 供 SessionRegistry 查询
        mcp_token_var.set(token)
        self.token_manager.touch_ip_last_seen(client_ip)
        # 旧 contextvar 保留兼容，过渡后删除
        access_level_var.set("user")
        source_var.set(
            "localhost" if _is_local_ip(client_ip)
            else _sanitize_ip_for_display(client_ip)
        )

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
    """ASGI 复合路由：展示页面 + 接入页面 + API + 鉴权 MCP。

    路由规则：
      /                         -> 价值展示页面 HTML（无需鉴权）
      /showcase                 -> 价值展示页面 HTML（无需鉴权）
      /access                   -> 接入工具页面 HTML（无需鉴权）
      /api/access-info          -> 自动检测的接入信息 JSON（无需鉴权）
      /api/showcase/data         -> 成果展示页数据 JSON（无需鉴权，含降级状态）
      /api/docs/export-skills-package -> Skills ZIP 下载（无需鉴权）
      /api/docs/export-skills   -> Skills Markdown 摘要（无需鉴权）
      /api/archive/templates/<id> -> 空白模板下载（票据验证）
      /api/archive/uploads      -> 已填 XLSX 上传（Bearer Token 鉴权）
      /mcp 及其它                -> 鉴权 MCP 端点（需要 Bearer Token）
    """

    def __init__(
        self,
        mcp_app,
        html_content,
        token_manager: TokenManager,
        showcase_content: str = ""):
        self.mcp_app = mcp_app
        self.auth = AuthMiddleware(mcp_app, token_manager)
        self.html_content = html_content
        self.showcase_content = showcase_content or html_content
        self.token_manager = token_manager

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.mcp_app(scope, receive, send)
            return

        path = scope.get("path", "")

        # 静态页面：/ 与 /showcase 为价值展示页，/access 为接入工具页
        if path in ("/", "/showcase", "/access"):
            if path == "/access":
                body = self.html_content.encode("utf-8")
            else:
                body = self.showcase_content.encode("utf-8")
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

        # 成果展示页数据 API（本地事实源 + 平台统计降级）
        if path == "/api/showcase/data":
            await self._handle_showcase_data(scope, send)
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

        # 空白模板下载（票据验证）
        if path.startswith("/api/archive/templates/"):
            await self._handle_template_download(scope, send)
            return

        # 已填 XLSX 上传（Bearer Token 鉴权）
        if path == "/api/archive/uploads":
            await self._handle_archive_upload(scope, receive, send)
            return

        # 本次操作日志回读（按接入 Token 定向，仅返回该身份自己的日志）
        if path == "/api/logs" or path.startswith("/api/logs?"):
            await self._handle_operation_logs(scope, send)
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

        server_version = _load_server_version()
        package_manifest = _load_package_manifest()
        body = json.dumps(
            {
                "baseUrl": base_url,
                "token": token_info["token"],
                "accessLevel": token_info["accessLevel"],
                "source": token_info["source"],
                "serverIPs": server_ips,
                "serverVersion": server_version["version"],
                "packageVersion": package_manifest.get("version", "unknown"),
                "packageName": package_manifest.get("name", "xlpa-agent-assets"),
                "cloudWriteSource": "业务登录账号命中超级账号配置",
                "clients": CLIENT_DEFINITIONS,
            },
            ensure_ascii=False).encode("utf-8")

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

    async def _handle_showcase_data(self, scope, send):
        """返回 showcase 页面展示数据（本地事实源 + 平台统计降级）。"""
        data = await _build_showcase_data()
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
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

    async def _handle_operation_logs(self, scope, send):
        """返回当前接入 Token 身份本次会话窗内的写操作日志（脱敏）。

        仅凭 Token 派生 owner_id 定向返回其自己的日志；无 Token/非法 Token
        返回空集合，不泄露他人数据。
        """
        headers = {
            name.decode().lower(): value.decode()
            for name, value in scope.get("headers", [])
        }
        query = scope.get("query_string", b"").decode("utf-8")
        params = dict(
            part.split("=", 1) for part in query.split("&") if "=" in part
        )

        token = ""
        auth = headers.get("authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
        token = token or params.get("token", "")
        cursor = params.get("cursor", "")

        owner_id = derive_owner_id(token) if token else ""
        if owner_id:
            entries, next_cursor = _op_store.list_current(owner_id, cursor=cursor)
            trace_id = _op_store.get_current_trace(owner_id)
        else:
            entries, next_cursor, trace_id = [], "", ""
        data = {
            "ok": True,
            "trace_id": trace_id,
            "next_cursor": next_cursor,
            "count": len(entries),
            "logs": [entry.to_dict() for entry in entries],
        }
        await self._send_json(send, 200, data)

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

    @staticmethod
    async def _send_json(send, status: int, data):
        """发送 JSON 响应。"""
        if isinstance(data, str):
            payload = {"error": data}
        else:
            payload = data
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    [b"content-type", b"application/json; charset=utf-8"],
                    [b"content-length", str(len(body)).encode()],
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def _handle_template_download(self, scope, send):
        """空白模板下载（票据验证）。

        从 URL 路径提取 file_id，通过 SnapshotStore 验证归属与有效期，
        返回模板字节。无需 Bearer Token，file_id 本身即为票据。
        """
        path = scope.get("path", "")
        file_id = path.split("/")[-1].split("?")[0]
        if not file_id:
            await self._send_json(send, 400, "缺少 file_id")
            return
        # 从查询参数获取 owner_id（由 MCP 工具生成下载链接时嵌入）
        query = scope.get("query_string", b"").decode()
        params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
        owner_id = params.get("owner", "")
        if not owner_id:
            await self._send_json(
                send, 400, "缺少 owner 查询参数"
            )
            return
        try:
            from edge_tools import template_store
            tpl_bytes = template_store.read_template_bytes(
                file_id, owner_id=owner_id
            )
            record = template_store.load(file_id, owner_id=owner_id)
        except Exception as exc:
            await self._send_json(send, 404, f"模板不可用: {exc}")
            return
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    [b"content-type",
                     b"application/vnd.openxmlformats-officedocument"
                     b".spreadsheetml.sheet"],
                    [b"content-disposition",
                     f'attachment; filename="{record.template_name}"'
                     .encode()],
                    [b"content-length", str(len(tpl_bytes)).encode()],
                ],
            }
        )
        await send({"type": "http.response.body", "body": tpl_bytes})

    async def _handle_archive_upload(self, scope, receive, send):
        """已填 XLSX 上传（Bearer Token 鉴权）。

        验证 Token 后读取请求体，校验 OOXML 结构，存储到快照存储，
        返回 file_id。配置 XLPA_PUBLIC_BASE_URL 时远程上传强制 HTTPS。
        """
        # HTTPS 入口检查（配置公网 URL 时强制）
        client_ip = _get_client_ip(scope)
        if XLPA_PUBLIC_BASE_URL and not _is_local_ip(client_ip):
            if not XLPA_PUBLIC_BASE_URL.startswith("https://"):
                await self._send_json(
                    send, 500,
                    "XLPA_PUBLIC_BASE_URL 必须为 HTTPS",
                )
                return
        # 验证 Bearer Token
        headers = {}
        for name, value in scope.get("headers", []):
            headers[name.decode().lower()] = value.decode()
        auth = headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            await self._send_json(send, 401, "Bearer token required")
            return
        token = auth[7:]
        if not self.token_manager.is_valid(token):
            await self._send_json(send, 401, "Invalid token")
            return
        # 读取请求体（有界）
        max_upload = 10 * 1024 * 1024  # 10 MB
        body = b""
        while True:
            message = await receive()
            if message["type"] != "http.request":
                break
            body += message.get("body", b"")
            if len(body) > max_upload:
                await self._send_json(
                    send, 413, f"文件过大，上限 {max_upload} 字节"
                )
                return
            if not message.get("more_body", False):
                break
        if not body:
            await self._send_json(send, 400, "请求体为空")
            return
        # OOXML 结构校验
        from archiving.ooxml_validator import (
            validate_ooxml, OOXMLValidationError,
        )
        try:
            zf = validate_ooxml(body)
            zf.close()
        except OOXMLValidationError as exc:
            await self._send_json(send, 400, f"工作簿校验失败: {exc}")
            return
        # 存储到快照存储
        import hashlib
        from archiving.snapshot_store import derive_owner_id
        from archiving.templates.generator import TEMPLATE_VERSION
        from edge_tools import template_store
        from archiving.models import TemplateSnapshot
        owner_id = derive_owner_id(token)
        if not owner_id:
            await self._send_json(send, 401, "无法确定归属")
            return
        snapshot = TemplateSnapshot(version=TEMPLATE_VERSION)
        try:
            record = template_store.save(
                snapshot, owner_id=owner_id,
                template_bytes=body, template_name="upload.xlsx",
            )
        except Exception as exc:
            await self._send_json(send, 500, f"存储失败: {exc}")
            return
        result = {
            "ok": True,
            "file_id": record.snapshot_id,
            "sha256": hashlib.sha256(body).hexdigest(),
            "size_bytes": len(body),
        }
        await self._send_json(send, 200, result)


# ── 启动入口 ──
if __name__ == "__main__":
    import webbrowser
    import uvicorn

    token_manager = TokenManager(admin_token=AUTH_TOKEN)

    if not AUTH_TOKEN:
        print("[WARNING] MCP_AUTH_TOKEN not set - auto-generating tokens for all IPs.")
        print("[WARNING] Set MCP_AUTH_TOKEN env var for a stable admin token.")
    else:
        print("[INFO] Admin token authentication enabled.")

    # ── 服务端系统 Token 初始化 ──
    print("[INFO] 初始化 SystemTokenManager...")
    token_ok = system_token_mgr.init()
    if token_ok:
        print("[INFO] 系统 Token 获取成功。")
    else:
        print(f"[WARNING] 系统 Token 获取失败: {system_token_mgr.last_error}")

    # ── 保留事件计数，完整回归独立后台执行 ──
    stats = _load_stats()
    _save_stats(stats)
    print(f"[INFO] Stats: scriptsGenerated={stats['scriptsGenerated']}")
    threading.Thread(target=_refresh_startup_test_report, daemon=True).start()

    get_app = getattr(mcp, "streamable_http_app", None) or getattr(
        mcp, "http_app", None
    )
    if get_app is None:
        raise RuntimeError(
            "Cannot find ASGI app method on FastMCP instance. "
            "Expected 'streamable_http_app' or 'http_app'."
        )
    app = get_app()

    wrapped_app = CompositeApp(
        app, ACCESS_HTML, token_manager, showcase_content=SHOWCASE_HTML
    )

    server_ips = _get_server_ips()
    display = "localhost" if HOST in ("0.0.0.0", "::") else HOST
    access_url = f"http://localhost:{PORT}/"
    print(f"[INFO] MCP Server starting on http://{display}:{PORT}")
    print(f"[INFO]   Showcase Page: {access_url}")
    print(f"[INFO]   Access Page:  http://localhost:{PORT}/access")
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
