"""环境变量配置解析。

所有配置均可由环境变量覆盖，键名与默认值：

- WEBCHAT_SESSION_TTL: 会话票据 TTL（秒），默认 43200（12 小时）。
- WEBCHAT_LOGIN_RATE_LIMIT: 限流参数 "<窗口秒>,<失败阈值>"，默认 "60,5"。
- WEBCHAT_ACCOUNTS_PATH: 账号库文件路径（默认包根下 webchat_accounts.json）。
- WEBCHAT_PERMISSIONS_PATH: 超级账号配置路径（默认仓库根 mcp_server/permissions.json）。
- PCA_API_BASE_URL: 平台 API 基地址（沿用既有语义）。
- WEBCHAT_HOST / WEBCHAT_PORT: 服务监听地址与端口，默认 0.0.0.0:8800。
  与 MCP Server 的 MCP_HOST 同源，默认监听全部网卡，局域网内其它
  机器可与本机一样访问；webchat 走账号口令鉴权（非 IP 信任），
  如需仅本机可显式设为 127.0.0.1。
- WEBCHAT_MINT_SECRET: mint 端点密钥（与 MCP Server 侧一致）。
- WEBCHAT_MINT_URL: MCP Server 基地址，默认 http://127.0.0.1:8765。
- WEBCHAT_MAX_INSTANCES: 全局活跃实例上限，默认 100。
- WEBCHAT_MAX_SESSIONS_PER_USER: 每用户并发会话上限，默认 5。
- WEBCHAT_MAX_TURNS: 单轮工具迭代上限，默认 25。
- WEBCHAT_SESSION_IDLE_TTL: 会话空闲自动结束阈值（秒），默认 1800；
  空闲且无执行中轮次的会话会被 close（不删除工作区与产物）。
- WEBCHAT_IDLE_SWEEP_INTERVAL: 空闲扫描周期（秒），默认 60。
- WEBCHAT_MAX_CONCURRENT_TURNS: 并发执行轮次上限，默认 16；超出时
  发送消息返回"系统繁忙"（不排队、不拉起新 CLI 子进程）。
- WEBCHAT_WORKSPACES_DIR: 会话工作区根目录。
- WEBCHAT_EVENTS_DIR: 事件存储根目录。
- WEBCHAT_LEASE_TTL: 写租约 TTL（秒），默认 45。
- WEBCHAT_GRANT_TTL: 写入门禁授权票据窗口（秒），默认 300。
- WEBCHAT_GATE_AUDIT_PATH: 门禁审计台账 JSONL 路径（默认数据根下
  gate_audit.jsonl；独立于会话生命周期，不随会话清理）。
- WEBCHAT_UPLOAD_MAX_TABLE_MB / _IMAGE_MB / _DOC_MB: 三通道上传大小上限
  （MB），默认 10 / 10 / 20（对齐 snapshot_store 既有上限口径）。
- WEBCHAT_RETENTION_INPUT_DAYS / _RESULT_DAYS / _TEMPLATE_DAYS /
  _SENSITIVE_TEMP_DAYS: 保留天数（默认 30 / 30 / 30 / 7，沿用 cleanup.py
  分类语义；temp 会话销毁即清、audit 不清）。
- WEBCHAT_RETENTION_SWEEP_INTERVAL: 保留期后台扫描间隔（秒），默认 3600。
- WEBCHAT_OCR_ENABLED: 截图通道 OCR 开关，默认 1（关闭后截图通道明确
  提示不可用，不影响其他通道）。
- WEBCHAT_OCR_PROVIDER: OCR provider 选择，默认 rapidocr（可插拔）。
- WEBCHAT_DOWNLOAD_GRANT_TTL: 一次性产物下载 grant TTL（秒），默认 120
  （消费即作废，与写入门禁的窗口可复用票据语义不同）。
- WEBCHAT_LOGIN_SOURCE_MAX: 登录来源级（不区分账号）失败阈值，默认 60
  （显著高于账号级 WEBCHAT_LOGIN_RATE_LIMIT 阈值，避免同反代互锁）。
- WEBCHAT_TRUSTED_PROXY: 可信反向代理地址清单（逗号分隔）。仅当直连
  来源命中该清单时，登录限流才采信 X-Forwarded-For 最左值；未配置时
  一律用直连地址，伪造转发头不改变计数维度。
- WEBCHAT_AGENT_MODEL: 会话模型名（传入 CLI --model），默认
  "Qwen3.8-Flash"；置空则回落 CLI 自身默认模型。
- WEBCHAT_SKILLS_ROOT: 技能母本目录，默认仓库 `agent_assets/skills`；
  索引进入系统提示，内置 Read 仅允许读取该目录与会话工作区。
- WEBCHAT_READ_EXTRA_ROOTS: 额外 Read 白名单目录（逗号或分号分隔）。默认
  已加入 CLI 大结果落盘目录 `%TEMP%/qoder-mcp-outputs` 与
  `~/.qoder-cn/tmp`，此变量用于继续追加，适用于以后新增的合法目录。
"""

from __future__ import annotations

__all__ = ["Settings", "SettingsError", "load_settings"]

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

# 包根 = webchat/（webchat/webchat/config.py 的上两级）
PACKAGE_ROOT: Path = Path(__file__).resolve().parents[1]
DEFAULT_ACCOUNTS_PATH = PACKAGE_ROOT / "webchat_accounts.json"
DEFAULT_PERMISSIONS_PATH = PACKAGE_ROOT.parent / "mcp_server" / "permissions.json"
DEFAULT_PLATFORM_BASE_URL = "https://18091.chinadny.com"
DEFAULT_DATA_ROOT = PACKAGE_ROOT / "webchat_data"
# canonical 技能母本（仓库根下 agent_assets/skills）
DEFAULT_SKILLS_ROOT = PACKAGE_ROOT.parent / "agent_assets" / "skills"
# CLI 大工具结果落盘目录（默认加入 Read 白名单）：qoder-mcp-outputs 为
# MCP 结果溢出目录，.qoder-cn/tmp 为 CLI tool-outputs 目录。
DEFAULT_CLI_READ_ROOTS: tuple[Path, ...] = (
    Path(tempfile.gettempdir()) / "qoder-mcp-outputs",
    Path.home() / ".qoder-cn" / "tmp",
)


class SettingsError(ValueError):
    """配置项非法时抛出。"""


@dataclass(frozen=True)
class Settings:
    """服务配置集合。"""

    session_ttl: int
    rate_window: int
    rate_max_failures: int
    accounts_path: Path
    permissions_path: Path
    platform_base_url: str
    host: str
    port: int
    mint_secret: str
    mint_url: str
    max_instances: int
    max_sessions_per_user: int
    max_turns: int
    workspaces_dir: Path
    events_dir: Path
    lease_ttl: int
    grant_ttl: int
    gate_audit_path: Path
    # ── C5 产物与上传（默认值保证既有构造点无需改动）──
    upload_max_table_bytes: int = 10 * 1024 * 1024
    upload_max_image_bytes: int = 10 * 1024 * 1024
    upload_max_document_bytes: int = 20 * 1024 * 1024
    retention_input_days: int = 30
    retention_result_days: int = 30
    retention_template_days: int = 30
    retention_sensitive_temp_days: int = 7
    retention_sweep_interval: int = 3600
    ocr_enabled: bool = True
    ocr_provider: str = "rapidocr"
    download_grant_ttl: int = 120
    # ── C7 登录限流：来源级阈值与可信代理（design D11）──
    # 来源级（不区分账号）阈值，默认显著高于账号级，避免同反代下互锁
    rate_source_max_failures: int = 60
    # 可信反向代理地址清单：仅直连来源命中时才采信 X-Forwarded-For 最左值
    trusted_proxies: tuple[str, ...] = ()
    # 会话模型名（传入 CLI --model）；默认 Qwen3.8-Flash，可经
    # WEBCHAT_AGENT_MODEL 覆盖（置空则回落 CLI 默认）
    agent_model: str = "Qwen3.8-Flash"
    # ── 容量与生命周期（默认值保证既有构造点无需改动）──
    session_idle_ttl: int = 1800
    idle_sweep_interval: int = 60
    max_concurrent_turns: int = 16
    # 技能母本目录（agent_assets/skills）；索引进系统提示，Read 白名单根之一
    skills_root: Path = DEFAULT_SKILLS_ROOT
    # Read 额外白名单目录（默认 CLI 落盘目录 + WEBCHAT_READ_EXTRA_ROOTS）
    read_extra_roots: tuple[Path, ...] = DEFAULT_CLI_READ_ROOTS


def _parse_int(name: str, raw: str) -> int:
    """解析正整数配置，非法即抛 SettingsError。"""
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise SettingsError(f"{name} 必须是整数，当前值: {raw!r}") from exc
    if value <= 0:
        raise SettingsError(f"{name} 必须为正整数，当前值: {raw!r}")
    return value


def _parse_bool(name: str, raw: str) -> bool:
    """解析布尔配置（1/0/true/false/yes/no），非法即抛 SettingsError。"""
    text = raw.strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise SettingsError(f"{name} 必须是布尔值（1/0/true/false），当前值: {raw!r}")


def _parse_mb(name: str, raw: str) -> int:
    """解析 MB 为字节（正整数）。"""
    return _parse_int(name, raw) * 1024 * 1024


def load_settings(environ: dict[str, str] | None = None) -> Settings:
    """从环境变量加载配置。

    Args:
        environ: 环境变量字典，默认取 os.environ（便于测试注入）。

    Returns:
        解析完成的 Settings。

    Raises:
        SettingsError: 任一配置项非法时。
    """
    env = os.environ if environ is None else environ
    session_ttl = _parse_int("WEBCHAT_SESSION_TTL", env.get("WEBCHAT_SESSION_TTL", "43200"))
    rate_raw = env.get("WEBCHAT_LOGIN_RATE_LIMIT", "60,5")
    try:
        window_raw, max_raw = rate_raw.split(",", 1)
    except ValueError as exc:
        raise SettingsError(
            f"WEBCHAT_LOGIN_RATE_LIMIT 格式应为 \"窗口秒,失败阈值\"，当前值: {rate_raw!r}"
        ) from exc
    rate_window = _parse_int("WEBCHAT_LOGIN_RATE_LIMIT(窗口)", window_raw.strip())
    rate_max = _parse_int("WEBCHAT_LOGIN_RATE_LIMIT(阈值)", max_raw.strip())
    accounts_path = Path(env.get("WEBCHAT_ACCOUNTS_PATH", str(DEFAULT_ACCOUNTS_PATH)))
    permissions_path = Path(
        env.get("WEBCHAT_PERMISSIONS_PATH", str(DEFAULT_PERMISSIONS_PATH))
    )
    platform_base_url = env.get("PCA_API_BASE_URL", DEFAULT_PLATFORM_BASE_URL).rstrip("/")
    if not platform_base_url:
        raise SettingsError("PCA_API_BASE_URL 不能为空")
    host = env.get("WEBCHAT_HOST", "0.0.0.0")
    port = _parse_int("WEBCHAT_PORT", env.get("WEBCHAT_PORT", "8800"))
    if port > 65535:
        raise SettingsError(f"WEBCHAT_PORT 超出范围: {port}")
    mint_secret = env.get("WEBCHAT_MINT_SECRET", "")
    if not mint_secret:
        raise SettingsError("WEBCHAT_MINT_SECRET 未配置")
    mint_url = env.get("WEBCHAT_MINT_URL", "http://127.0.0.1:8765").rstrip("/")
    max_instances = _parse_int("WEBCHAT_MAX_INSTANCES", env.get("WEBCHAT_MAX_INSTANCES", "100"))
    max_sessions = _parse_int(
        "WEBCHAT_MAX_SESSIONS_PER_USER",
        env.get("WEBCHAT_MAX_SESSIONS_PER_USER", "5"),
    )
    max_turns = _parse_int("WEBCHAT_MAX_TURNS", env.get("WEBCHAT_MAX_TURNS", "25"))
    workspaces_dir = Path(
        env.get("WEBCHAT_WORKSPACES_DIR", str(DEFAULT_DATA_ROOT / "workspaces"))
    )
    events_dir = Path(
        env.get("WEBCHAT_EVENTS_DIR", str(DEFAULT_DATA_ROOT / "events"))
    )
    lease_ttl = _parse_int("WEBCHAT_LEASE_TTL", env.get("WEBCHAT_LEASE_TTL", "45"))
    grant_ttl = _parse_int("WEBCHAT_GRANT_TTL", env.get("WEBCHAT_GRANT_TTL", "300"))
    gate_audit_path = Path(
        env.get("WEBCHAT_GATE_AUDIT_PATH", str(DEFAULT_DATA_ROOT / "gate_audit.jsonl"))
    )
    upload_max_table = _parse_mb(
        "WEBCHAT_UPLOAD_MAX_TABLE_MB", env.get("WEBCHAT_UPLOAD_MAX_TABLE_MB", "10")
    )
    upload_max_image = _parse_mb(
        "WEBCHAT_UPLOAD_MAX_IMAGE_MB", env.get("WEBCHAT_UPLOAD_MAX_IMAGE_MB", "10")
    )
    upload_max_document = _parse_mb(
        "WEBCHAT_UPLOAD_MAX_DOC_MB", env.get("WEBCHAT_UPLOAD_MAX_DOC_MB", "20")
    )
    retention_input_days = _parse_int(
        "WEBCHAT_RETENTION_INPUT_DAYS", env.get("WEBCHAT_RETENTION_INPUT_DAYS", "30")
    )
    retention_result_days = _parse_int(
        "WEBCHAT_RETENTION_RESULT_DAYS", env.get("WEBCHAT_RETENTION_RESULT_DAYS", "30")
    )
    retention_template_days = _parse_int(
        "WEBCHAT_RETENTION_TEMPLATE_DAYS", env.get("WEBCHAT_RETENTION_TEMPLATE_DAYS", "30")
    )
    retention_sensitive_temp_days = _parse_int(
        "WEBCHAT_RETENTION_SENSITIVE_TEMP_DAYS",
        env.get("WEBCHAT_RETENTION_SENSITIVE_TEMP_DAYS", "7"),
    )
    retention_sweep_interval = _parse_int(
        "WEBCHAT_RETENTION_SWEEP_INTERVAL",
        env.get("WEBCHAT_RETENTION_SWEEP_INTERVAL", "3600"),
    )
    ocr_enabled = _parse_bool(
        "WEBCHAT_OCR_ENABLED", env.get("WEBCHAT_OCR_ENABLED", "1")
    )
    ocr_provider = env.get("WEBCHAT_OCR_PROVIDER", "rapidocr").strip()
    if not ocr_provider:
        raise SettingsError("WEBCHAT_OCR_PROVIDER 不能为空")
    download_grant_ttl = _parse_int(
        "WEBCHAT_DOWNLOAD_GRANT_TTL", env.get("WEBCHAT_DOWNLOAD_GRANT_TTL", "120")
    )
    rate_source_max = _parse_int(
        "WEBCHAT_LOGIN_SOURCE_MAX", env.get("WEBCHAT_LOGIN_SOURCE_MAX", "60")
    )
    trusted_raw = env.get("WEBCHAT_TRUSTED_PROXY", "")
    trusted_proxies = tuple(
        ip.strip() for ip in trusted_raw.split(",") if ip.strip()
    )
    agent_model = env.get("WEBCHAT_AGENT_MODEL", "Qwen3.8-Flash").strip()
    session_idle_ttl = _parse_int(
        "WEBCHAT_SESSION_IDLE_TTL", env.get("WEBCHAT_SESSION_IDLE_TTL", "1800")
    )
    idle_sweep_interval = _parse_int(
        "WEBCHAT_IDLE_SWEEP_INTERVAL", env.get("WEBCHAT_IDLE_SWEEP_INTERVAL", "60")
    )
    max_concurrent_turns = _parse_int(
        "WEBCHAT_MAX_CONCURRENT_TURNS",
        env.get("WEBCHAT_MAX_CONCURRENT_TURNS", "16"),
    )
    skills_root = Path(
        env.get("WEBCHAT_SKILLS_ROOT", str(DEFAULT_SKILLS_ROOT))
    )
    extra_raw = env.get("WEBCHAT_READ_EXTRA_ROOTS", "")
    extras = list(DEFAULT_CLI_READ_ROOTS)
    for raw in re.split(r"[,;]", extra_raw):
        raw = raw.strip()
        if raw:
            extras.append(Path(os.path.expandvars(raw)).expanduser())
    read_extra_roots = tuple(dict.fromkeys(extras))
    return Settings(
        session_ttl=session_ttl,
        rate_window=rate_window,
        rate_max_failures=rate_max,
        accounts_path=accounts_path,
        permissions_path=permissions_path,
        platform_base_url=platform_base_url,
        host=host,
        port=port,
        mint_secret=mint_secret,
        mint_url=mint_url,
        max_instances=max_instances,
        max_sessions_per_user=max_sessions,
        max_turns=max_turns,
        workspaces_dir=workspaces_dir,
        events_dir=events_dir,
        lease_ttl=lease_ttl,
        grant_ttl=grant_ttl,
        gate_audit_path=gate_audit_path,
        upload_max_table_bytes=upload_max_table,
        upload_max_image_bytes=upload_max_image,
        upload_max_document_bytes=upload_max_document,
        retention_input_days=retention_input_days,
        retention_result_days=retention_result_days,
        retention_template_days=retention_template_days,
        retention_sensitive_temp_days=retention_sensitive_temp_days,
        retention_sweep_interval=retention_sweep_interval,
        ocr_enabled=ocr_enabled,
        ocr_provider=ocr_provider,
        download_grant_ttl=download_grant_ttl,
        rate_source_max_failures=rate_source_max,
        trusted_proxies=trusted_proxies,
        agent_model=agent_model,
        session_idle_ttl=session_idle_ttl,
        idle_sweep_interval=idle_sweep_interval,
        max_concurrent_turns=max_concurrent_turns,
        skills_root=skills_root,
        read_extra_roots=read_extra_roots,
    )
