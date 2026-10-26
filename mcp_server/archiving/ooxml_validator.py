"""OOXML 工作簿结构校验与解压安全检查。

对上传的 XLSX 文件执行轻量级结构校验，在进入解析工作池之前拒绝
明显非法或危险的输入。校验不触发任何后端调用。

拒绝条件：
  - 非 ZIP 格式或无法打开
  - 缺少 ``[Content_Types].xml``（非 OOXML 工作簿）
  - 含 VBA 宏（xl/vbaProject.bin）
  - 加密文件（xl/encryptedKey 等）
  - 路径穿越条目（``..`` 或绝对路径）
  - 重复条目名
  - 压缩膨胀比超过阈值（zip bomb 防护）
  - 解压后总大小超过上限
"""

from __future__ import annotations

__all__ = [
    "OOXMLValidationError",
    "validate_ooxml",
    "DEFAULT_MAX_UNCOMPRESSED_BYTES",
    "DEFAULT_MAX_COMPRESSION_RATIO",
]

import zipfile
from io import BytesIO

# 解压后总字节上限（默认 50 MB）
DEFAULT_MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
# 压缩膨胀比上限（压缩前 / 压缩后）
DEFAULT_MAX_COMPRESSION_RATIO = 100
# 宏文件标记（小写比较）
_VBA_MARKER = "xl/vbaproject.bin"
# 加密文件标记前缀（小写比较）
_ENCRYPTED_PREFIXES = ("xl/encryptedkey", "xl/encryption")
# OOXML 必需条目
_CONTENT_TYPES = "[Content_Types].xml"


class OOXMLValidationError(ValueError):
    """工作簿结构校验失败。"""


def validate_ooxml(
    data: bytes,
    *,
    max_uncompressed: int = DEFAULT_MAX_UNCOMPRESSED_BYTES,
    max_ratio: int = DEFAULT_MAX_COMPRESSION_RATIO,
) -> zipfile.ZipFile:
    """校验字节数据为合法 OOXML 工作簿。

    Args:
        data: 原始文件字节。
        max_uncompressed: 解压后总大小上限。
        max_ratio: 最大压缩膨胀比。

    Returns:
        已打开的 ZipFile 对象（调用方负责关闭）。

    Raises:
        OOXMLValidationError: 任一校验条件不满足。
    """
    if not data:
        raise OOXMLValidationError("文件为空")

    # 检查 ZIP 魔数（PK\x03\x04 或 PK\x05\x06 空归档）
    if data[:2] not in (b"PK",):
        raise OOXMLValidationError("非 ZIP 格式")

    try:
        zf = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise OOXMLValidationError(f"损坏的 ZIP: {exc}") from exc

    names = zf.namelist()

    # 必需条目
    if _CONTENT_TYPES not in names:
        zf.close()
        raise OOXMLValidationError(
            f"缺少 {_CONTENT_TYPES}，非 OOXML 工作簿"
        )

    # 宏检测
    for name in names:
        if name.lower() == _VBA_MARKER:
            zf.close()
            raise OOXMLValidationError("含 VBA 宏，拒绝接受")

    # 加密检测
    for name in names:
        lower = name.lower()
        if any(lower.startswith(p) for p in _ENCRYPTED_PREFIXES):
            zf.close()
            raise OOXMLValidationError("文件已加密，拒绝接受")

    # 路径穿越检测
    for name in names:
        if name.startswith("/") or name.startswith("\\"):
            zf.close()
            raise OOXMLValidationError(f"绝对路径条目: {name}")
        if ".." in name.split("/"):
            zf.close()
            raise OOXMLValidationError(f"路径穿越条目: {name}")

    # 重复条目检测
    seen: set[str] = set()
    for name in names:
        if name in seen:
            zf.close()
            raise OOXMLValidationError(f"重复条目: {name}")
        seen.add(name)

    # 压缩膨胀检查（zip bomb 防护）
    total_uncompressed = sum(info.file_size for info in zf.infolist())
    total_compressed = sum(info.compress_size for info in zf.infolist())

    if total_uncompressed > max_uncompressed:
        zf.close()
        raise OOXMLValidationError(
            f"解压后大小 {total_uncompressed} 超过上限 {max_uncompressed}"
        )

    if total_compressed > 0:
        ratio = total_uncompressed / total_compressed
        if ratio > max_ratio:
            zf.close()
            raise OOXMLValidationError(
                f"压缩膨胀比 {ratio:.1f} 超过上限 {max_ratio}"
            )

    return zf
