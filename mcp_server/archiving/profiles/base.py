"""设备类型 profile 基类与 deviceTypeId 常量。

profile 描述一个 deviceTypeId 的基础字段、派生字段、extInfos、data item
字段、必填校验和下发结构。引擎只依赖本基类接口，新增设备类型时扩展
profile 而不改引擎。
"""

from __future__ import annotations

__all__ = [
    "DeviceProfile",
    "ProfileResult",
    "GATEWAY_8163_TYPE_ID",
    "METER_XLBA_TYPE_ID",
    "METER_LIGHTING_TYPE_ID",
    "METER_PDB_TYPE_ID",
    "VIRTUAL_GATEWAY_TYPE_ID",
    "METER_DEPLOY_ITEM_ID",
    "assemble_auth_param",
    "encode_auth_param_hex",
    "normalize_auth_param_for_deploy",
    "AUTH_PARAM_PLACEHOLDER",
]

from dataclasses import dataclass, field

#: 下发 authParam 的页面占位默认（12 个 E，即 6 字节未赋值占位）。
#: 2026-10-21 现场定稿：无 IP+端口来源时一律用它。
AUTH_PARAM_PLACEHOLDER = "EEEEEEEEEEEE"

# 已确认的 deviceTypeId（来源 Path B 175 实测 + 10.0.17.23 建档实测）
GATEWAY_8163_TYPE_ID = "100009"
METER_XLBA_TYPE_ID = "100019"
# 照明 / 配电房监测点（10.0.17.23 实测建档成功，getDeviceTypeSelect 同源）
METER_LIGHTING_TYPE_ID = "100023"
METER_PDB_TYPE_ID = "100024"
# 虚拟网关留作二期，仅登记 ID，不提供可用 profile
VIRTUAL_GATEWAY_TYPE_ID = "100015"

# XLBA 抄表参数下发数据项 ID（来源 Path B b6 实测）
METER_DEPLOY_ITEM_ID = "20200002"


@dataclass
class ProfileResult:
    """profile 解析与校验的结果。

    Attributes:
        errors: 阻止建档/联通的致命错误（可读文案）。
        warnings: 非致命提示（如未声明列被忽略）。
        base_payload: 建档 modifyDevice 的基础字段。
        ext_infos: extInfos 字段字典。
        deploy_item_body: 下发数据项 itemBody（无下发能力时为 None）。
        proxy_comm_type: 网关代理通信方式（非网关为空）。
        link_blocked: 是否因缺字段阻止联通类操作。
    """

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    base_payload: dict = field(default_factory=dict)
    ext_infos: dict = field(default_factory=dict)
    deploy_item_body: dict | None = None
    proxy_comm_type: str = ""
    link_blocked: bool = False

    @property
    def ok(self) -> bool:
        """是否无致命错误。"""
        return not self.errors


def assemble_auth_param(
    ip: str,
    port: str,
    comm_port: str,
    ip_ports: frozenset[str],
    password: str = "",
) -> str:
    """端口驱动组装 authParam（10.0.17.23 实测坐实的多态落点）。

    authParam 是 extInfos 中的多态字段：

    - ETH/MQTT 等 IP 型端口（``comm_port`` ∈ ``ip_ports``）：承载
      「通信IP端口号」，恒为 5 段逗号串 ``ip1,ip2,ip3,ip4,port``；
      IP/端口均未填时返回空串（不写入，由前端保持 ``",,,,"`` 默认形态）。
    - RS485 等串口端口：承载电表密码，原样透传 ``password``；
      此时禁止填写 IP/端口列（抛 ``ValueError`` 阻断）。

    Args:
        ip: IPv4 点分十进制串（可空）。
        port: IP 端口号（可空）。
        comm_port: 已翻译为码值的 proxyCommPort。
        ip_ports: 承载 IP+端口的端口码值集合（如 {"40","41","50"}）。
        password: RS485 端口下的电表密码（extInfos.authParam 透传值）。

    Returns:
        组装后的 authParam 串；空串表示不写入。

    Raises:
        ValueError: IP 非 4 段数字、端口非数字、IP/端口只填其一，
            或串口端口下填写了 IP/端口列。
    """
    ip = (ip or "").strip()
    port = (port or "").strip()
    if str(comm_port) in ip_ports:
        if password.strip():
            raise ValueError(
                "ETH/MQTT 端口的 authParam 承载通信IP端口号，"
                "不得同时填写电表密码"
            )
        if not ip and not port:
            return ""
        if not ip or not port:
            raise ValueError(
                f"IP 型端口需同时填写 IP地址 与 IP端口号（实际 ip={ip!r} port={port!r}）"
            )
        parts = ip.split(".")
        if len(parts) != 4 or not all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
            raise ValueError(f"IP地址必须是合法 4 段 IPv4，实际为 {ip!r}")
        if not port.isdigit():
            raise ValueError(f"IP端口号必须是数字，实际为 {port!r}")
        return ",".join(parts) + f",{port}"
    if ip or port:
        raise ValueError(
            f"端口 {comm_port} 非 IP 型端口，authParam 承载电表密码；"
            "「IP地址/IP端口号」列仅 ETH/MQTT 端口可填"
        )
    return password.strip()


def encode_auth_param_hex(ip: str, port: str) -> str:
    """将通信 IP 与端口编码为下发 authParam 的 12 位十六进制串。

    现场抓包实证（2026-10-21，ETH-1／comPort=40）：页面「通信IP端口号」
    192.168.23.150 : 21883 下发为 ``c0a81796557b``，即 IP 四段各 1 字节
    加端口 16 位大端，共 6 字节小写十六进制。档案侧 extInfos 仍用
    五段逗号串（10.0.17.23 建档实测），两种形态分属不同落点。

    Args:
        ip: IPv4 点分十进制串（4 段，每段 0-255）。
        port: IP 端口号（0-65535）。

    Returns:
        12 位小写十六进制串。

    Raises:
        ValueError: IP 非合法 4 段、端口非数字或超出 16 位。
    """
    parts = (ip or "").strip().split(".")
    if len(parts) != 4 or not all(
        p.isdigit() and 0 <= int(p) <= 255 for p in parts
    ):
        raise ValueError(f"IP地址必须是合法 4 段 IPv4，实际为 {ip!r}")
    port_text = (port or "").strip()
    if not port_text.isdigit():
        raise ValueError(f"IP端口号必须是数字，实际为 {port!r}")
    port_num = int(port_text)
    if port_num > 0xFFFF:
        raise ValueError(f"IP端口号超出 16 位可编码范围：{port_num}")
    return "".join(f"{int(p):02x}" for p in parts) + f"{port_num:04x}"


def normalize_auth_param_for_deploy(value: str) -> str:
    """将任意来源的 authParam 归一为下发侧 12 位十六进制形态。

    规则（2026-10-21 现场定稿，所有监测点类型统一、不按类型特殊处理）：
    - 空/缺失 → 占位默认 ``EEEEEEEEEEEE``；
    - 五段逗号串 ``ip1,ip2,ip3,ip4,port`` → 编码为 hex(IP 4B)+hex(port 2B)；
    - 已是 12 位十六进制 → 小写原样保留；
    - 其他形态无法按 IP+端口编码 → 退回占位默认。

    Args:
        value: 待归一的 authParam 串（可空）。

    Returns:
        12 位小写十六进制串。
    """
    text = (value or "").strip()
    if not text:
        return AUTH_PARAM_PLACEHOLDER
    if "," in text:
        parts = text.split(",")
        if len(parts) == 5:
            try:
                return encode_auth_param_hex(".".join(parts[:4]), parts[4])
            except ValueError:
                return AUTH_PARAM_PLACEHOLDER
        return AUTH_PARAM_PLACEHOLDER
    if len(text) == 12 and all(c in "0123456789abcdefABCDEF" for c in text):
        return text.lower()
    return AUTH_PARAM_PLACEHOLDER


class DeviceProfile:
    """设备类型 profile 基类。

    子类需声明 ``device_type``、``device_type_id``、``profile_name``，
    并覆写 ``resolve`` 生成建档/下发结构。基类提供通用工具方法。
    """

    #: 中文设备类型名（Excel「设备类型」列取值）
    device_type: str = ""
    #: 后端 deviceTypeId
    device_type_id: str = ""
    #: profile 名称（registry 键之一）
    profile_name: str = ""
    #: 是否为网关（需要 proxyCommType 前置）
    is_gateway: bool = False
    #: 是否已实现可用（二期占位 profile 置 False）
    supported: bool = True
    #: 监测点在线判定方法："monitor_debug"（运维召测）或
    #: "smart_event"（感知事件 getSmartEventData）。新类型可按需覆写；
    #: 未覆写即默认运维召测。仅用于诊断报告，不阻塞四操作。
    online_check_method: str = "monitor_debug"

    def resolve(self, node, task_config, detail: dict) -> ProfileResult:
        """解析节点并生成建档/下发结构与校验结果。

        Args:
            node: ``TopologyNode`` 拓扑节点。
            task_config: ``TaskConfig`` 任务配置。
            detail: 类型明细行字段字典（网关明细 / 电表明细）。

        Returns:
            ProfileResult，含 errors / warnings / payload / itemBody。
        """
        raise NotImplementedError

    @staticmethod
    def _undeclared_columns(detail: dict, declared: set[str]) -> list[str]:
        """找出明细中未被 profile 声明的列，用于 dry-run 提示。

        Args:
            detail: 明细行字段字典。
            declared: profile 声明支持的列名集合。

        Returns:
            未声明列名列表（忽略空键）。
        """
        return sorted(
            key for key in detail if key and key not in declared
        )
