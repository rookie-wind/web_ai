"""8163 网关 profile。

网关建档需要 deviceAddress（12 位）与 proxyCommType（代理通信方式）。
proxyCommType 取已填写的已知名称或码值，不预置默认代理方式。
缺失或未知时计划报错，不执行建档、保存或通信。
"""

from __future__ import annotations

__all__ = ["Gateway8163Profile"]

from ..converter import AddressConversionError, convert_comm_address, validate_device_address
from .base import (
    GATEWAY_8163_TYPE_ID,
    DeviceProfile,
    ProfileResult,
)

# 网关明细声明支持的列（按名称关联，条码列为关联键不入 detail）
_DECLARED_COLUMNS = {"deviceBarcode", "proxyCommType", "deviceName"}
# 建档时通讯地址重复策略（来源 Path B create_device 实测取值）
_COMM_ADDR_REPETITION = "2"


class Gateway8163Profile(DeviceProfile):
    """8163 网关（deviceTypeId=100009）建档 profile。"""

    device_type = "8163网关"
    device_type_id = GATEWAY_8163_TYPE_ID
    profile_name = "gateway_8163"
    is_gateway = True

    def resolve(self, node, task_config, detail: dict) -> ProfileResult:
        """解析网关节点，生成建档 payload 与 proxyCommType 校验结果。

        Args:
            node: 拓扑节点。
            task_config: 任务配置。
            detail: 网关明细行字段。

        Returns:
            ProfileResult，含建档 base_payload、proxy_comm_type 与错误/提示。
        """
        result = ProfileResult()
        detail = detail or {}

        # 未声明列提示
        for col in self._undeclared_columns(detail, _DECLARED_COLUMNS):
            if detail[col] is not None and str(detail[col]).strip():
                result.errors.append(f"网关明细列 {col!r} 未声明落点，禁止忽略已填值")

        # ── 通讯地址：明细/总览显式值优先，否则按条码转换 ──
        address = str(node.comm_address or "").strip()
        identifier = str(node.identifier or "").strip()
        if address:
            try:
                address = validate_device_address(address)
            except AddressConversionError as exc:
                result.errors.append(f"网关 {node.node_key} 通讯地址非法: {exc}")
                address = ""
        elif identifier:
            try:
                address = convert_comm_address(identifier)
            except AddressConversionError as exc:
                result.errors.append(f"网关 {node.node_key} 条码转换失败: {exc}")
        else:
            result.errors.append(
                f"网关 {node.node_key} 缺少通讯地址与条码，无法生成 deviceAddress"
            )

        # ── proxyCommType：从网关明细获取，翻译友好名→后端码值 ──
        # 不预置默认代理方式；未填写时不阻止建档，仅告警并标记联通前置缺失
        # （link_blocked 作信息位，下发/召测不因此拦截，见主规格）。
        proxy_raw = str(detail.get("proxyCommType", "") or "").strip()
        if not proxy_raw:
            result.warnings.append(
                f"网关 {node.node_key} 未填写 proxyCommType（网关明细未提供），"
                "建档照常执行，但可能无法联通，下发/召测请复核"
            )
            result.link_blocked = True
        # 只接受已知名称或字典已有的码值。
        from ..field_contract import _COMM_MODE_CODE_MAP
        proxy = _COMM_MODE_CODE_MAP.get(proxy_raw, "")
        if proxy_raw in _COMM_MODE_CODE_MAP.values():
            proxy = proxy_raw
        if proxy_raw and not proxy:
            result.errors.append(f"proxyCommType 未知名称或码值: {proxy_raw!r}")
            result.link_blocked = True
        proxy_source = "网关明细"
        result.proxy_comm_type = proxy

        # ── 建档 payload ──
        if not node.device_name:
            result.errors.append(f"网关 {node.node_key} 缺少设备名称")
        base_payload = {
            "deviceName": node.device_name,
            "deviceTypeId": self.device_type_id,
            "deviceAddress": address,
            "commAddrRepetition": _COMM_ADDR_REPETITION,
        }
        if proxy:
            base_payload["proxyCommType"] = proxy
        if node.identifier:
            base_payload["identifier"] = str(node.identifier).strip()
        if node.device_id:
            base_payload["deviceId"] = node.device_id
        result.base_payload = base_payload
        if proxy_raw:
            result.warnings.append(
                f"网关 {node.node_key} proxyCommType={proxy}（{proxy_raw}，来源：{proxy_source}）"
            )
        return result
