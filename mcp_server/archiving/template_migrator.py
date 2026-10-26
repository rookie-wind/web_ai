"""服务端建档模板版本迁移器。

当 server 模板结构因新增设备类型 sheet 而演进（TEMPLATE_VERSION 递增）后，
本模块提供确定性的"旧版→当前版"结构迁移能力：
- 保留旧文件中用户已填的数据行；
- 以当前版骨架补入新增 sheet（空表头）；
- 更新版本标签为当前 TEMPLATE_VERSION。

仅处理纯新增 sheet 场景（前提：已有 sheet 列布局不变）。
不负责业务值校验（由后续 read/plan 处理）。
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from enum import Enum

from openpyxl import load_workbook

from archiving.templates.generator import (
    SHEET_SYSTEM_CONNECTION,
    TEMPLATE_VERSION,
)

# ── 已知版本列表（从旧到新），末项必须等于 TEMPLATE_VERSION ──
SUPPORTED_MIGRATIONS: list[str] = [
    "v14-engineer",
    "v15-engineer",
]


# 断言：末项必须与 generator 导出的 TEMPLATE_VERSION 一致
assert SUPPORTED_MIGRATIONS[-1] == TEMPLATE_VERSION, (
    f"SUPPORTED_MIGRATIONS 末项 {SUPPORTED_MIGRATIONS[-1]!r} "
    f"!= TEMPLATE_VERSION {TEMPLATE_VERSION!r}"
)


class MigrateStatus(str, Enum):
    """迁移结果状态。"""

    OK = "OK"
    ALREADY_CURRENT = "ALREADY_CURRENT"
    REJECTED = "REJECTED"


@dataclass
class MigrateResult:
    """迁移操作返回值。

    Args:
        status: 迁移状态。
        from_version: 旧文件的版本标签。
        to_version: 目标版本（当前 TEMPLATE_VERSION）。
        migrated_bytes: 迁移产物（仅 status=OK 时非 None）。
        added_sheets: 本次新增补入的 sheet 名称列表。
        reason: 拒绝或补充说明。
    """

    status: MigrateStatus
    from_version: str
    to_version: str = TEMPLATE_VERSION
    migrated_bytes: bytes | None = None
    added_sheets: list[str] = field(default_factory=list)
    reason: str = ""


def _read_version(wb) -> str:
    """从工作簿的系统连接 sheet 读取 __template_version 值。"""
    if SHEET_SYSTEM_CONNECTION not in wb.sheetnames:
        return ""
    ws = wb[SHEET_SYSTEM_CONNECTION]
    for row in ws.iter_rows(min_row=2, max_col=2, values_only=True):
        key = str(row[0]).strip() if row[0] else ""
        if key == "__template_version":
            return str(row[1]).strip() if row[1] else ""
    return ""


def _classify(file_version: str) -> MigrateStatus:
    """根据文件版本标签判定迁移状态。"""
    if file_version == TEMPLATE_VERSION:
        return MigrateStatus.ALREADY_CURRENT
    if file_version in SUPPORTED_MIGRATIONS:
        # 在列表中但不是末项 → 比当前旧，可迁移
        if SUPPORTED_MIGRATIONS.index(file_version) < len(SUPPORTED_MIGRATIONS) - 1:
            return MigrateStatus.OK
    # 未知版本 或 高于当前（不在列表或列表后无对应）
    return MigrateStatus.REJECTED


def _copy_sheet_data(old_ws, new_ws, skip_meta: bool = False) -> None:
    """按表头名匹配列位置，拷贝旧 sheet 数据行到新 sheet。

    Args:
        old_ws: 旧工作表。
        new_ws: 新工作表（骨架，已含正确表头行）。
        skip_meta: 若 True，跳过 A 列以 __ 开头的行（系统连接 sheet）。
    """
    # 构建新 sheet 的 表头名 → 列索引（1-based）映射
    new_header: dict[str, int] = {}
    for cell in new_ws[1]:
        name = str(cell.value).strip() if cell.value else ""
        if name:
            new_header[name] = cell.column
    # 构建旧 sheet 的 表头名 → 列索引
    old_header: dict[str, int] = {}
    for cell in old_ws[1]:
        name = str(cell.value).strip() if cell.value else ""
        if name:
            old_header[name] = cell.column
    # 列映射：旧列位置 → 新列位置（仅同名列）
    col_map: dict[int, int] = {}
    for name, old_idx in old_header.items():
        if name in new_header:
            col_map[old_idx] = new_header[name]
    # 逐行拷贝数据（row 2+）
    new_row_idx = 2
    for row in old_ws.iter_rows(min_row=2):
        # skip_meta: 跳过 A 列值以 __ 开头的元数据行
        if skip_meta:
            a_val = str(row[0].value).strip() if row[0].value else ""
            if a_val.startswith("__"):
                continue
        # 检查是否整行皆空（跳过空行）
        if all(c.value is None or str(c.value).strip() == "" for c in row):
            continue
        # 按列映射搬运
        for old_col, new_col in col_map.items():
            src_idx = old_col - 1  # 0-based index in row tuple
            if src_idx < len(row):
                new_ws.cell(
                    row=new_row_idx, column=new_col,
                    value=row[src_idx].value,
                )
        new_row_idx += 1


def migrate_template(
    old_bytes: bytes,
    skeleton_bytes: bytes,
) -> MigrateResult:
    """将旧版模板迁移为当前版本。

    Args:
        old_bytes: 旧版模板 XLSX 字节。
        skeleton_bytes: 当前版空白骨架 XLSX 字节（由 generator 产出）。

    Returns:
        MigrateResult，status=OK 时 migrated_bytes 非 None。
    """
    # 1) 打开旧文件读取版本
    old_wb = load_workbook(io.BytesIO(old_bytes), data_only=True)
    file_version = _read_version(old_wb)
    status = _classify(file_version)

    if status == MigrateStatus.ALREADY_CURRENT:
        old_wb.close()
        return MigrateResult(
            status=MigrateStatus.ALREADY_CURRENT,
            from_version=file_version,
            to_version=TEMPLATE_VERSION,
            reason="已是当前版本，无需迁移",
        )

    if status == MigrateStatus.REJECTED:
        old_wb.close()
        return MigrateResult(
            status=MigrateStatus.REJECTED,
            from_version=file_version,
            to_version=TEMPLATE_VERSION,
            reason=(
                f"文件版本 {file_version!r} 高于或不在已知迁移路径内，"
                f"请升级服务端"
            ),
        )

    # 2) 可迁移：打开骨架，逐表拷贝
    new_wb = load_workbook(io.BytesIO(skeleton_bytes))
    old_sheets = set(old_wb.sheetnames)
    new_sheets = set(new_wb.sheetnames)

    for sheet_name in old_wb.sheetnames:
        if sheet_name not in new_sheets:
            continue  # 旧多余 sheet 忽略
        old_ws = old_wb[sheet_name]
        new_ws = new_wb[sheet_name]
        is_sys_conn = (sheet_name == SHEET_SYSTEM_CONNECTION)
        _copy_sheet_data(old_ws, new_ws, skip_meta=is_sys_conn)

    # 3) 保存迁移产物
    buf = io.BytesIO()
    new_wb.save(buf)
    migrated_bytes = buf.getvalue()
    new_wb.close()
    old_wb.close()

    # 4) 计算新增 sheet（排除旧文件已有的）
    added = sorted(new_sheets - old_sheets)

    return MigrateResult(
        status=MigrateStatus.OK,
        from_version=file_version,
        to_version=TEMPLATE_VERSION,
        migrated_bytes=migrated_bytes,
        added_sheets=added,
    )
