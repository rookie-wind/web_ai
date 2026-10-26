"""template_migrator 单元测试。

覆盖：旧→新迁移成功、数据保留、no-op、拒绝、多余 sheet 忽略。
"""
from __future__ import annotations

import io

from openpyxl import load_workbook

from archiving.excel_reader import read_archive_template
from archiving.template_migrator import (
    MigrateStatus,
    SUPPORTED_MIGRATIONS,
    migrate_template,
)
from archiving.templates.generator import (
    SHEET_SYSTEM_CONNECTION,
    TEMPLATE_VERSION,
)


def _generate_skeleton() -> bytes:
    """生成当前版空白骨架字节。"""
    from edge_tools import _generate_template_bytes
    return _generate_template_bytes()


def _make_old_fixture(
    *,
    drop_sheets: list[str] | None = None,
    add_sheet: str | None = None,
    extra_rows: dict[str, list[list]] | None = None,
    stamp_version: str = "v14-engineer",
) -> bytes:
    """构造一份模拟旧版模板。

    Args:
        drop_sheets: 要删除的 sheet 名（模拟新增表在旧版不存在）。
        add_sheet: 要添加的额外 sheet（模拟废弃表）。
        extra_rows: {sheet_name: [[cell_val, ...], ...]}，注入数据行。
        stamp_version: 写入的版本标签。
    """
    raw = _generate_skeleton()
    wb = load_workbook(io.BytesIO(raw))
    # 删除指定 sheet
    for name in (drop_sheets or []):
        if name in wb.sheetnames:
            del wb[name]
    # 添加废弃 sheet
    if add_sheet:
        ws = wb.create_sheet(add_sheet)
        ws.append(["废弃列1", "废弃列2"])
        ws.append(["垃圾数据", "垃圾数据2"])
    # 注入自定义数据行
    for sheet_name, rows in (extra_rows or {}).items():
        if sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            for row_data in rows:
                ws.append(row_data)
    # 修改版本标签
    if SHEET_SYSTEM_CONNECTION in wb.sheetnames:
        ws = wb[SHEET_SYSTEM_CONNECTION]
        for row in ws.iter_rows(min_row=2, max_col=2):
            if row[0].value and "__template_version" in str(row[0].value):
                row[1].value = stamp_version
                break
    buf = io.BytesIO()
    wb.save(buf)
    wb.close()
    return buf.getvalue()


class TestMigrateSuccess:
    """4.1 旧版迁移成功，产物可被 reader 正常解析。"""

    def test_basic_migration(self):
        skeleton = _generate_skeleton()
        old = _make_old_fixture(
            drop_sheets=["监测点·照明"],
            stamp_version="v14-engineer",
        )
        result = migrate_template(old, skeleton)
        assert result.status == MigrateStatus.OK
        assert result.migrated_bytes is not None
        assert "监测点·照明" in result.added_sheets
        # 迁移产物可被 reader 正常打开，且无版本错误
        import tempfile
        from pathlib import Path
        tmp = Path(tempfile.mktemp(suffix=".xlsx"))
        tmp.write_bytes(result.migrated_bytes)
        tpl = read_archive_template(str(tmp))
        tmp.unlink(missing_ok=True)
        # 不应有版本相关错误
        version_errors = [e for e in tpl.errors if "版本" in e]
        assert version_errors == []
        # 监测点·照明 sheet 存在
        wb = load_workbook(io.BytesIO(result.migrated_bytes))
        assert "监测点·照明" in wb.sheetnames
        wb.close()

    def test_data_preservation(self):
        """4.2 数据保留：网关和监测点 sheet 行数和内容一致。"""
        gateway_rows = [
            ["GW01", "BAR001", "以太网", "10.0.0.1", "7500", "admin", "pwd"],
            ["GW02", "BAR002", "串口", "", "", "", ""],
        ]
        meter_rows = [
            ["电表A", "MB01", "1", "", "", "", "", "", "", "",
             "", "", "", "", "", "", "", "", "", ""],
        ]
        extra = {
            "网关·8163": gateway_rows,
            "监测点·XLBA": meter_rows,
        }
        skeleton = _generate_skeleton()
        old = _make_old_fixture(
            drop_sheets=["监测点·配电房"],
            extra_rows=extra,
            stamp_version="v14-engineer",
        )
        result = migrate_template(old, skeleton)
        assert result.status == MigrateStatus.OK
        # 验证迁移后 sheet 数据行数
        wb = load_workbook(io.BytesIO(result.migrated_bytes))
        ws_gw = wb["网关·8163"]
        gw_data_rows = [
            r for r in ws_gw.iter_rows(min_row=2, values_only=True)
            if any(v for v in r if v is not None and str(v).strip())
        ]
        assert len(gw_data_rows) == 2
        # 首行第一格 = GW01
        assert str(gw_data_rows[0][0]).strip() == "GW01"
        # 验证 监测点·XLBA
        ws_xlba = wb["监测点·XLBA"]
        xlba_rows = [
            r for r in ws_xlba.iter_rows(min_row=2, values_only=True)
            if any(v for v in r if v is not None and str(v).strip())
        ]
        assert len(xlba_rows) == 1
        assert str(xlba_rows[0][0]).strip() == "电表A"
        wb.close()

    def test_already_current(self):
        """4.3 no-op：已是当前版本。"""
        skeleton = _generate_skeleton()
        result = migrate_template(skeleton, skeleton)
        assert result.status == MigrateStatus.ALREADY_CURRENT
        assert result.migrated_bytes is None

    def test_rejected_higher_version(self):
        """4.4 拒绝：高于当前版本。"""
        skeleton = _generate_skeleton()
        old = _make_old_fixture(stamp_version="v99-engineer")
        result = migrate_template(old, skeleton)
        assert result.status == MigrateStatus.REJECTED
        assert result.migrated_bytes is None

    def test_extra_sheet_ignored(self):
        """4.5 多余旧 sheet 被忽略，不出现在产物中。"""
        skeleton = _generate_skeleton()
        old = _make_old_fixture(
            add_sheet="已废弃·旧类型",
            stamp_version="v14-engineer",
        )
        result = migrate_template(old, skeleton)
        assert result.status == MigrateStatus.OK
        wb = load_workbook(io.BytesIO(result.migrated_bytes))
        assert "已废弃·旧类型" not in wb.sheetnames
        wb.close()
