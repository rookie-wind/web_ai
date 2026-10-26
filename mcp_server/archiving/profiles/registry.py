"""设备类型 profile 注册表。

以设备类型中文名与 deviceTypeId 双通道注册 profile，供引擎按 Excel
「设备类型」或 deviceId 查表。未支持类型返回可读错误并建议补充 profile；
虚拟网关登记为二期占位，绝不映射到 8163 网关或 XLBA 电表。
"""

from __future__ import annotations

__all__ = [
    "ProfileRegistry",
    "VirtualGatewayPlaceholderProfile",
    "default_registry",
    "ProfileLookupError",
]

from .base import (
    VIRTUAL_GATEWAY_TYPE_ID,
    DeviceProfile,
    ProfileResult,
)
from .gateway_8163 import Gateway8163Profile
from .meter_lighting import MeterLightingProfile
from .meter_pdb import MeterPdbProfile
from .meter_xlba import MeterXlbaProfile
from ..models import TypeSheetSpec


class ProfileLookupError(Exception):
    """设备类型无法解析为可用 profile。"""


class VirtualGatewayPlaceholderProfile(DeviceProfile):
    """虚拟网关二期占位 profile（当前不可用）。

    登记 deviceTypeId=100015，仅用于给出「二期实现」的明确提示，
    不生成任何建档或下发结构，也不回退到其它类型。
    """

    device_type = "虚拟网关"
    device_type_id = VIRTUAL_GATEWAY_TYPE_ID
    profile_name = "virtual_gateway_placeholder"
    is_gateway = True
    #: 标记为二期占位，未实现
    supported = False

    def resolve(self, node, task_config, detail: dict) -> ProfileResult:
        """返回二期未实现错误，绝不映射到其它设备类型。

        Args:
            node: 拓扑节点。
            task_config: 任务配置。
            detail: 明细字段（忽略）。

        Returns:
            含致命错误的 ProfileResult。
        """
        result = ProfileResult()
        result.errors.append(
            f"虚拟网关（deviceTypeId={self.device_type_id}）profile 留作二期实现，"
            f"节点 {getattr(node, 'node_key', '')} 暂不支持自动建档；"
            "系统不会将其当作 8163 网关或 XLBA 电表处理"
        )
        result.link_blocked = True
        return result


class ProfileRegistry:
    """设备类型 profile 注册表。

    支持按中文设备类型名或 deviceTypeId 查询 profile。查询失败时抛
    ``ProfileLookupError`` 或返回可读错误，绝不猜测字段结构。
    """

    def __init__(self) -> None:
        """初始化空注册表。"""
        self._by_name: dict[str, DeviceProfile] = {}
        self._by_id: dict[str, DeviceProfile] = {}

    def register(self, profile: DeviceProfile) -> None:
        """注册一个 profile（按名称与 deviceTypeId 双通道）。

        Args:
            profile: 设备类型 profile 实例。
        """
        if profile.device_type:
            self._by_name[profile.device_type] = profile
        if profile.device_type_id:
            self._by_id[str(profile.device_type_id)] = profile

    def get(
        self, device_type: str = "", device_type_id: str = ""
    ) -> DeviceProfile | None:
        """按名称或 deviceTypeId 查询 profile。

        Args:
            device_type: 中文设备类型名。
            device_type_id: 后端 deviceTypeId。

        Returns:
            命中的 profile；未命中返回 None。名称优先于 ID。
        """
        if device_type and device_type in self._by_name:
            return self._by_name[device_type]
        if device_type_id and str(device_type_id) in self._by_id:
            return self._by_id[str(device_type_id)]
        return None

    def resolve(
        self, device_type: str = "", device_type_id: str = ""
    ) -> tuple[DeviceProfile | None, str]:
        """解析设备类型并返回 profile 或可读错误。

        Args:
            device_type: 中文设备类型名。
            device_type_id: 后端 deviceTypeId。

        Returns:
            二元组 ``(profile, error)``。命中且可用时 error 为空；
            虚拟网关或未支持类型时 profile 为 None 或占位，error 为可读文案。
        """
        profile = self.get(device_type, device_type_id)
        if profile is None:
            label = device_type or device_type_id or "<空>"
            return None, (
                f"不支持的设备类型 {label!r}：未登记对应 profile，"
                "请补充该 deviceTypeId 的 profile 后重试，系统不会猜测其字段结构"
            )
        if getattr(profile, "supported", True) is False:
            # 虚拟网关等二期占位：返回占位 profile 与明确提示
            return profile, (
                f"设备类型 {profile.device_type}（deviceTypeId={profile.device_type_id}）"
                "留作二期实现，暂不支持自动建档"
            )
        return profile, ""

    def sheet_spec(
        self, device_type: str = "", device_type_id: str = ""
    ) -> TypeSheetSpec | None:
        """按设备类型名或 deviceTypeId 查 sheet／接口能力契约。

        契约与生成、解析、payload、回读共用同一来源（field_contract），
        注册表不重复维护名称码值表。

        Args:
            device_type: 中文设备类型名。
            device_type_id: 后端 deviceTypeId。

        Returns:
            命中的 TypeSheetSpec；未声明契约时返回 None。
        """
        # 延迟导入避免 field_contract ↔ profiles 包的循环导入
        from ..field_contract import get_sheet_spec

        return get_sheet_spec(device_type, device_type_id)

    def supported_types(self) -> list[dict]:
        """列出全部已登记设备类型及其支持状态与 sheet 契约。

        Returns:
            含 device_type / device_type_id / profile_name / supported /
            sheet_name / interface_capabilities / unverified_fields 的字典列表。
        """
        seen: set[str] = set()
        out: list[dict] = []
        # 延迟导入避免 field_contract ↔ profiles 包的循环导入
        from ..field_contract import get_sheet_spec

        for profile in list(self._by_name.values()) + list(self._by_id.values()):
            if profile.profile_name in seen:
                continue
            seen.add(profile.profile_name)
            spec = get_sheet_spec(profile.device_type, profile.device_type_id)
            out.append(
                {
                    "device_type": profile.device_type,
                    "device_type_id": profile.device_type_id,
                    "profile_name": profile.profile_name,
                    "supported": getattr(profile, "supported", True),
                    "sheet_name": spec.sheet_name if spec else "",
                    "interface_capabilities": (
                        dict(spec.interface_capabilities) if spec else {}
                    ),
                    "unverified_fields": (
                        spec.unverified_fields() if spec else []
                    ),
                }
            )
        return out


def _build_default_registry() -> ProfileRegistry:
    """构建含首期 profile 的默认注册表。

    Returns:
        已注册 8163 网关、XLBA 电表、照明/配电房监测点与虚拟网关占位的
        ProfileRegistry。
    """
    registry = ProfileRegistry()
    registry.register(Gateway8163Profile())
    registry.register(MeterXlbaProfile())
    registry.register(MeterLightingProfile())
    registry.register(MeterPdbProfile())
    registry.register(VirtualGatewayPlaceholderProfile())
    return registry


# 模块级默认注册表，供引擎直接引用
default_registry = _build_default_registry()
