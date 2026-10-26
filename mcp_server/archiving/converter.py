"""XLPA 自动建档：通讯地址转换与校验。

转换规则来自175参数组件 convertCommAddr：
  identifier[2:6] + "000" + identifier[7:]，得到12位地址。
  例：224356000200 -> 435600000200。
该地址同时用于基本档案与网关参数项20100024；其它设备类型不套用。
XLBA 电表叶子的 ``identifier`` 通常直接等于 ``deviceAddress``，
是否走转换由设备 profile 决定，不在本模块强制。
"""

from __future__ import annotations

__all__ = [
    "convert_comm_address",
    "validate_device_address",
    "AddressConversionError",
    "DEVICE_ADDRESS_LENGTH",
    "BARCODE_LENGTH",
]

# 通讯地址与条码固定长度
DEVICE_ADDRESS_LENGTH = 12
BARCODE_LENGTH = 12
# 去掉的 1-based 位置（第 1、2、7 位）对应的 0-based 索引
_REMOVED_INDEXES = (0, 1, 6)
# 前端在去位后的第4位之后插入3个零。
_KEPT_HEAD_LENGTH = 4
_PADDING_ZEROS = "000"


class AddressConversionError(ValueError):
    """通讯地址转换或校验失败。"""


def convert_comm_address(identifier: str) -> str:
    """从条码 identifier 生成 12 位通讯地址 deviceAddress。

    规则：去掉条码第 1、2、7 位（1-based），在中间补 3 个 0。
    样本 ``224356000099`` 生成 ``435600000099``。

    Args:
        identifier: 12 位纯数字条码。

    Returns:
        12 位通讯地址字符串。

    Raises:
        AddressConversionError: 当 identifier 非 12 位纯数字，
            或转换结果长度不为 12 位时。
    """
    if identifier is None:
        raise AddressConversionError("条码 identifier 不能为空")
    barcode = str(identifier).strip()
    if not barcode.isdigit():
        raise AddressConversionError(f"条码必须为纯数字: {barcode!r}")
    if len(barcode) != BARCODE_LENGTH:
        raise AddressConversionError(
            f"条码必须为 {BARCODE_LENGTH} 位，当前 {len(barcode)} 位: {barcode!r}"
        )
    # 去掉第 1、2、7 位（0-based 索引 0、1、6），保留其余 9 位
    kept = "".join(
        ch for idx, ch in enumerate(barcode) if idx not in _REMOVED_INDEXES
    )
    if len(kept) != BARCODE_LENGTH - len(_REMOVED_INDEXES):
        raise AddressConversionError(f"条码去位后长度异常: {barcode!r}")
    # 对齐175 convertCommAddr 的 substring(0, 4) 拼接规则。
    result = kept[:_KEPT_HEAD_LENGTH] + _PADDING_ZEROS + kept[_KEPT_HEAD_LENGTH:]
    if len(result) != DEVICE_ADDRESS_LENGTH:
        raise AddressConversionError(
            f"转换结果必须为 {DEVICE_ADDRESS_LENGTH} 位，当前 {len(result)} 位"
        )
    return result


def validate_device_address(device_address: str) -> str:
    """校验通讯地址为 12 位纯数字。

    Args:
        device_address: 待校验的通讯地址。

    Returns:
        规范化后的通讯地址字符串。

    Raises:
        AddressConversionError: 当通讯地址非 12 位纯数字时。
    """
    if device_address is None:
        raise AddressConversionError("通讯地址不能为空")
    addr = str(device_address).strip()
    if not addr.isdigit():
        raise AddressConversionError(f"通讯地址必须为纯数字: {addr!r}")
    if len(addr) != DEVICE_ADDRESS_LENGTH:
        raise AddressConversionError(
            f"通讯地址必须为 {DEVICE_ADDRESS_LENGTH} 位，当前 {len(addr)} 位: {addr!r}"
        )
    return addr
