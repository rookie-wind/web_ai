"""task 4.1 验收：v14-engineer 六表结构、版本化元数据与无历史凭据/样例设备。

覆盖验收标准：六表名正确、列名正确、元数据完整、无历史凭据（175/23）、
无样例设备、字典池与映射表一致性。
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.formula.translate import Translator
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

_MCP_DIR = Path(__file__).parent.parent
if str(_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_MCP_DIR))

from archiving.engine import build_existing_index, build_plan  # noqa: E402
from archiving.excel_reader import read_archive_template  # noqa: E402
from archiving.field_contract import XLBA_METER_SHEET_SPEC  # noqa: E402
from archiving.models import InputType, TaskConfig, TopologyNode  # noqa: E402
from archiving.profiles.meter_xlba import MeterXlbaProfile  # noqa: E402
from archiving.templates import generator  # noqa: E402
from archiving.templates.generator import (  # noqa: E402
    FIELD_CONTRACT_VERSION,
    SHEET_DICT,
    SHEET_GW_8163,
    SHEET_MAPPING,
    SHEET_METER_XLBA,
    SHEET_SYSTEM_CONNECTION,
    SHEET_TOPO,
    TEMPLATE_VERSION,
    generate_template,
)

_SAMPLE_DEVICE_TYPES = [
    {"name": "8163网关", "code": "100009"},
    {"name": "XLBA", "code": "100019"},
]
_SAMPLE_USER_BIG_NOS = [{"name": "电表类", "code": "11"}]
_SAMPLE_COMM_MODES = [
    {"name": "MQTT", "code": "13"},
    {"name": "RS485端口1", "code": "3"},
]
_SAMPLE_BRANDS = [
    {"name": "安科瑞", "code": "1"},
    {"name": "美的", "code": "6"},
]
_SAMPLE_MODELS = {
    "安科瑞": [{"name": "DTZ341", "code": "33"}],
    "美的": [{"name": "DTZ123", "code": "44"}],
}
# 独立记录前端已核实的顺序和码值，不用生产常量生成期望值。
_EXPECTED_COMM_PORTS = [
    ("RS485-1", "1"), ("RS485-2", "2"), ("RS485-3", "3"), ("RS485-4", "4"),
    ("AC485-1", "11"), ("AC485-2", "12"), ("ETH-1", "40"), ("ETH-2", "41"),
    ("LoRa-1", "31"), ("LoRa-2", "32"), ("LoRa-3", "33"), ("LoRa-4", "34"),
    ("LoRa-5", "35"), ("LoRa-6", "36"), ("4438-1", "28"), ("4438-2", "29"),
    ("MQTT", "50"), ("控制模块", "43"), ("脉冲/告警模块", "44"),
    ("监听RS485-1", "51"), ("监听RS485-2", "52"),
]


@pytest.fixture
def v14_workbook(tmp_path):
    """生成 v14 模板并返回 openpyxl Workbook。"""
    out = tmp_path / "test_v14.xlsx"
    generate_template(
        out,
        device_types=_SAMPLE_DEVICE_TYPES,
        user_big_nos=_SAMPLE_USER_BIG_NOS,
        comm_modes=_SAMPLE_COMM_MODES,
        brands=_SAMPLE_BRANDS,
        models_by_brand=_SAMPLE_MODELS,
        snapshot_id="test-snapshot-id",
        source_time="2026-01-01T00:00:00+00:00",
        fetched_at="2026-01-01T00:00:00+00:00",
    )
    return load_workbook(out)


# ── 六表结构 ──


class TestSheetStructure:
    """六表名称与顺序。"""

    def test_six_sheets(self, v14_workbook):
        """工作簿含系统连接/字典/挂载关系/网关与各监测点类型表/映射。"""
        expected = {
            SHEET_SYSTEM_CONNECTION,
            SHEET_DICT,
            SHEET_TOPO,
            SHEET_GW_8163,
            SHEET_METER_XLBA,
            *generator.MONITOR_SHEET_NAMES,
            SHEET_MAPPING,
        }
        assert set(v14_workbook.sheetnames) == expected

    def test_sheet_order(self, v14_workbook):
        """表顺序：系统连接/字典/挂载关系/网关·8163/各监测点类型表/映射。"""
        assert v14_workbook.sheetnames == [
            SHEET_SYSTEM_CONNECTION,
            SHEET_DICT,
            SHEET_TOPO,
            SHEET_GW_8163,
            *generator.MONITOR_SHEET_NAMES,
            SHEET_MAPPING,
        ]


# ── 系统连接：元数据与无历史凭据 ──


class TestSystemConnection:
    """系统连接 sheet 的元数据与无预置现场地址。"""

    def test_metadata_present(self, v14_workbook):
        """元数据行含模板版本/契约版本/快照 ID/来源时间/最大行数/有效期。"""
        ws = v14_workbook[SHEET_SYSTEM_CONNECTION]
        keys = [ws.cell(row=r, column=1).value for r in range(1, ws.max_row + 1)]
        assert "__template_version" in keys
        assert "__field_contract_version" in keys
        assert "__snapshot_id" in keys
        assert "__source_time" in keys
        assert "__max_data_rows" in keys
        assert "__snapshot_ttl_days" in keys

    def test_version_values(self, v14_workbook):
        """版本值与常量一致。"""
        ws = v14_workbook[SHEET_SYSTEM_CONNECTION]
        for r in range(1, ws.max_row + 1):
            key = ws.cell(row=r, column=1).value
            if key == "__template_version":
                assert ws.cell(row=r, column=2).value == TEMPLATE_VERSION
            elif key == "__field_contract_version":
                assert ws.cell(row=r, column=2).value == FIELD_CONTRACT_VERSION

    def test_no_preset_field_address(self, v14_workbook):
        """不预置 175/23 等现场地址。"""
        ws = v14_workbook[SHEET_SYSTEM_CONNECTION]
        for r in range(1, ws.max_row + 1):
            for c in range(1, ws.max_column + 1):
                val = ws.cell(row=r, column=c).value
                if val is None:
                    continue
                val_str = str(val)
                assert "175" not in val_str or "192.168.1.175" not in val_str
                assert "10.0.11.23" not in val_str

    def test_target_connection_keys_blank(self, v14_workbook):
        """中文配置项（目标系统IP/后端端口/账号/密码/手机号/验证码）值为空。"""
        ws = v14_workbook[SHEET_SYSTEM_CONNECTION]
        for r in range(1, ws.max_row + 1):
            key = ws.cell(row=r, column=1).value
            if key in (
                "目标系统IP", "后端端口", "账号", "密码", "手机号", "验证码",
            ):
                assert ws.cell(row=r, column=2).value in (None, "")


# ── 网关·8163 与 监测点·XLBA：列名与无示例 ──


class TestDeviceSheets:
    """网关与监测点 sheet 的列名与无示例设备。"""

    def test_gateway_columns(self, v14_workbook):
        """网关·8163 三列：设备名称/设备条码/代理通信方式。"""
        ws = v14_workbook[SHEET_GW_8163]
        headers = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
        assert headers == ["设备名称", "设备条码", "代理通信方式"]

    def test_meter_columns(self, v14_workbook):
        """监测点·XLBA 20 列（按 field_contract）。"""
        ws = v14_workbook[SHEET_METER_XLBA]
        headers = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
        expected = [
            "设备名称", "设备条码", "测量点号", "分路号",
            "协议代号", "用户大分类号", "品牌", "型号", "抄表间隔",
            "代理通信方式", "通信端口号", "波特率", "停止位", "校验位",
            "数据位", "IP地址", "IP端口号", "采集器地址", "电流变比", "电压变比",
        ]
        assert headers == expected == XLBA_METER_SHEET_SPEC.headers()

    @pytest.mark.parametrize("measur_no,road_no", [("17", "29"), ("0", "0"), ("", "29")])
    def test_column_order_preserves_payload(
        self, v14_workbook: Workbook, tmp_path: Path, measur_no: str, road_no: str,
    ) -> None:
        """比较新旧及逆序表头的解析与字段落点，保留零值和空测量点号。"""
        wb = v14_workbook
        topo = wb[SHEET_TOPO]
        topo["A2"] = "测试网关"
        topo["B2"] = "测试监测点"
        topo["B3"] = None
        wb[SHEET_GW_8163].append(["测试网关", "224356000099", "MQTT"])
        ws = wb[SHEET_METER_XLBA]
        current = [cell.value for cell in ws[1]]
        legacy = [name for name in current if name not in ("测量点号", "分路号")]
        legacy.extend(["分路号", "测量点号"])
        values = {
            "设备名称": "测试监测点", "设备条码": "001234000007",
            "测量点号": measur_no, "分路号": road_no,
            "协议代号": "新联MQTT协议", "用户大分类号": "电表类",
            "品牌": "安科瑞", "型号": "DTZ341", "抄表间隔": "不抄表",
            "通信端口号": "2", "波特率": "9600", "停止位": "1位停止位",
            "校验位": "无校验", "数据位": "8位", "采集器地址": "001234000008",
            "电流变比": "100", "电压变比": "10",
        }
        results = []
        for index, headers in enumerate((current, legacy, list(reversed(current)))):
            for column, header in enumerate(headers, start=1):
                ws.cell(1, column).value = header
                ws.cell(2, column).value = values.get(header, "")
            out = tmp_path / f"order_{index}.xlsx"
            wb.save(out)
            parsed = read_archive_template(out)
            detail = parsed.meter_details["测试监测点"]
            node = parsed.node_map()["测试监测点"]
            result = MeterXlbaProfile().resolve(node, parsed.task_config, detail)
            assert not result.errors, result.errors
            assert result.base_payload["identifier"] == "001234000007"
            assert result.base_payload["agentNum"] == road_no
            assert result.base_payload["measuredPointNum"] == measur_no
            assert result.deploy_item_body["roadNo"] == int(road_no)
            if measur_no:
                assert result.deploy_item_body["measurNo"] == int(measur_no)
            else:
                assert "measurNo" not in result.deploy_item_body
            results.append((detail, result.base_payload, result.ext_infos, result.deploy_item_body))
        assert results[0] == results[1] == results[2]

    def test_no_example_devices(self, v14_workbook):
        """网关与监测点 sheet 无示例设备行（仅表头）。"""
        ws_gw = v14_workbook[SHEET_GW_8163]
        assert ws_gw.max_row == 1  # 仅表头
        ws_meter = v14_workbook[SHEET_METER_XLBA]
        assert ws_meter.max_row == 1  # 仅表头


# ── 字典与映射：一致性 ──


class TestDictAndMapping:
    """字典池与映射表的一致性。"""

    def test_dict_pools_present(self, v14_workbook):
        """字典 sheet 含设备类型/品牌/型号池。"""
        ws = v14_workbook[SHEET_DICT]
        headers = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
        assert "设备类型" in headers
        assert "品牌" in headers
        assert "型号·安科瑞" in headers
        assert "型号·美的" in headers

    def test_mapping_consistency(self, v14_workbook):
        """映射表含设备类型/品牌/型号行且码值一致。"""
        ws = v14_workbook[SHEET_MAPPING]
        rows = []
        for r in range(2, ws.max_row + 1):
            field = ws.cell(row=r, column=1).value
            option = ws.cell(row=r, column=2).value
            backend = ws.cell(row=r, column=3).value
            code = ws.cell(row=r, column=4).value
            rows.append((field, option, backend, code))
        # 设备类型
        dt_rows = [r for r in rows if r[0] == "设备类型"]
        assert len(dt_rows) == 2
        assert ("设备类型", "8163网关", "deviceTypeId", "100009") in dt_rows
        # 品牌
        brand_rows = [r for r in rows if r[0] == "品牌"]
        assert len(brand_rows) == 2
        assert ("品牌", "安科瑞", "extInfos.brand", "1") in brand_rows
        # 型号
        model_rows = [r for r in rows if r[0] == "型号"]
        assert len(model_rows) == 2
        assert ("型号", "安科瑞 / DTZ341", "extInfos.decimalNum", "33") in model_rows


class TestCommPortDropdown:
    """验证通信端口的实际下拉、码值转换和原有安全边界。"""

    def test_options_and_mapping(self, v14_workbook: Workbook) -> None:
        """逐项核对下拉和映射表，保留数字输入与原有列结构。"""
        ws = v14_workbook[SHEET_METER_XLBA]
        validations = [
            dv for dv in ws.data_validations.dataValidation
            if str(dv.sqref) == "K2:K10001"
        ]
        assert len(validations) == 1
        dv = validations[0]
        names = [name for name, _ in _EXPECTED_COMM_PORTS]
        assert dv.type == "list"
        assert dv.formula1 == '"' + ",".join(names) + '"'
        assert len(dv.formula1) < 255
        assert dv.allow_blank is True
        assert dv.showDropDown is False
        assert dv.showErrorMessage is False
        assert dv.showInputMessage is True
        assert "43/44" in dv.prompt
        spec = XLBA_METER_SHEET_SPEC.field("proxyCommPort")
        assert spec.input_type is InputType.ENUM
        assert spec.dropdown_options() == names
        assert list(spec.code_map.items()) == _EXPECTED_COMM_PORTS
        rows = [
            row for row in v14_workbook[SHEET_MAPPING].iter_rows(min_row=2, values_only=True)
            if row[0] == "通信端口号"
        ]
        assert [row[:4] for row in rows] == [
            ("通信端口号", name, "proxyCommPort", code)
            for name, code in _EXPECTED_COMM_PORTS
        ]
        assert all("源码核实" in row[4] for row in rows)
        assert "代理通信端口" not in [cell.value for cell in ws[1]]

    def test_only_port_validation_and_mapping_added(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """对照未加端口下拉的模板，确认其余数据、区域与下拉不变。"""
        options = {
            "brands": _SAMPLE_BRANDS,
            "models_by_brand": _SAMPLE_MODELS,
            "snapshot_id": "same-snapshot",
            "source_time": "2026-09-23T00:00:00+00:00",
            "fetched_at": "2026-09-23T00:00:00+00:00",
        }
        with monkeypatch.context() as patch:
            patch.setattr(generator, "COMM_PORT_CODE_MAP", {})
            before = load_workbook(generate_template(tmp_path / "before.xlsx", **options))
        after = load_workbook(generate_template(tmp_path / "after.xlsx", **options))
        assert before.sheetnames == after.sheetnames
        assert before.defined_names == after.defined_names
        for name in before.sheetnames:
            old_ws, new_ws = before[name], after[name]
            assert old_ws.max_column == new_ws.max_column
            extra_rows = 21 if name == SHEET_MAPPING else 0
            assert new_ws.max_row == old_ws.max_row + extra_rows
            assert list(old_ws.values) == list(new_ws.iter_rows(
                max_row=old_ws.max_row, max_col=old_ws.max_column, values_only=True,
            ))
            assert old_ws.merged_cells == new_ws.merged_cells
            # 比较列属性，不比较绑定不同工作簿的对象实例。
            assert {
                key: dict(dimension) for key, dimension in old_ws.column_dimensions.items()
            } == {
                key: dict(dimension) for key, dimension in new_ws.column_dimensions.items()
            }
            new_validations = [
                dv for dv in new_ws.data_validations.dataValidation
                if not (
                    name in generator.MONITOR_SHEET_NAMES
                    and str(dv.sqref) == "K2:K10001"
                )
            ]
            assert old_ws.data_validations.dataValidation == new_validations
        before.close()
        after.close()

    @pytest.mark.parametrize("name,code", _EXPECTED_COMM_PORTS)
    def test_template_roundtrip_and_plan(
        self, v14_workbook: Workbook, tmp_path: Path, name: str, code: str,
    ) -> None:
        """实际工作簿逐项解析，与数字输入对照，专用模式仍阻断计划。"""
        wb = v14_workbook
        wb[SHEET_SYSTEM_CONNECTION].append(["目标系统IP", "test.invalid", ""])
        wb[SHEET_SYSTEM_CONNECTION].append(["账号", "test", ""])
        topo = wb[SHEET_TOPO]
        topo["A2"] = "测试网关"
        topo["B2"] = "端口测试监测点"
        topo["B3"] = None
        wb[SHEET_GW_8163].append(["测试网关", "224356000099", "MQTT"])
        ws = wb[SHEET_METER_XLBA]
        values = {
            "设备名称": "端口测试监测点", "设备条码": "001234000007",
            "分路号": "1", "测量点号": "7", "通信端口号": name,
            "波特率": "9600", "停止位": "1位停止位", "校验位": "无校验",
            "数据位": "8位",
        }
        ws.append([values.get(cell.value, "") for cell in ws[1]])
        out = tmp_path / "comm_port.xlsx"
        wb.save(out)
        parsed = read_archive_template(out)
        assert parsed.ok, parsed.errors
        detail = parsed.meter_details["端口测试监测点"]
        assert detail["comPort"] == name
        node = parsed.node_map()["端口测试监测点"]
        profile = MeterXlbaProfile()
        actual = profile.resolve(node, parsed.task_config, detail)
        numeric = profile.resolve(node, parsed.task_config, {**detail, "comPort": code})
        assert actual == numeric
        assert actual.base_payload["proxyCommPort"] == code
        assert actual.deploy_item_body["comPort"] == int(code)
        assert actual.ext_infos["feeNum"] == "195"
        assert "comPort" not in actual.base_payload
        plan = build_plan(parsed, build_existing_index([]))
        item = next(item for item in plan.items if item.node_key == node.node_key)
        if code in ("43", "44"):
            assert any("专用周期编码" in error for error in actual.errors)
            assert item.action.value == "conflict"
        else:
            assert not actual.errors, actual.errors
            assert item.action.value == "create", item.reason

    @pytest.mark.parametrize("raw,expected", [
        (None, ""), ("", ""), ("  ", ""), (0, "0"), ("0", "0"),
        ("001", "1"), (1, "1"), (" 50 ", "50"), (52, "52"),
        (21, "21"), (42, "42"), (999, "999"),
    ])
    def test_legacy_numeric_and_blank(self, raw: object, expected: str) -> None:
        """保留旧数字输入的校验范围、零值及空白不补默认的行为。"""
        node = TopologyNode(
            node_key="测试电表", device_name="测试电表", device_type="XLBA电表",
            identifier="001234000007", road_no="1",
        )
        for key in ("comPort", "proxyCommPort"):
            result = MeterXlbaProfile().resolve(node, TaskConfig(), {key: raw})
            assert not result.errors, result.errors
            assert result.base_payload["proxyCommPort"] == expected
            if expected:
                assert result.deploy_item_body["comPort"] == int(expected)
            else:
                assert "comPort" not in result.deploy_item_body

    @pytest.mark.parametrize("raw", ["未知端口", "CAN", "INFRARED", -1, 1.5, True])
    def test_invalid_input_still_blocked(self, raw: object) -> None:
        """未声明名称及非法数字不得进入档案或报文。"""
        node = TopologyNode(
            node_key="测试电表", device_name="测试电表", device_type="XLBA电表",
            identifier="001234000007", road_no="1",
        )
        result = MeterXlbaProfile().resolve(node, TaskConfig(), {"comPort": raw})
        assert any("proxyCommPort" in error for error in result.errors)
        assert not result.base_payload
        assert result.deploy_item_body is None

    @pytest.mark.parametrize("code,conflict", [("50", False), ("1", True)])
    def test_alias_conflicts_checked_after_mapping(self, code: str, conflict: bool) -> None:
        """友好名先转码，再检查同字段输入是否冲突。"""
        node = TopologyNode(
            node_key="测试电表", device_name="测试电表", device_type="XLBA电表",
            identifier="001234000007", road_no="1",
        )
        result = MeterXlbaProfile().resolve(
            node, TaskConfig(), {"comPort": "MQTT", "proxyCommPort": code},
        )
        if conflict:
            assert any("输入不一致" in error for error in result.errors)
            assert not result.base_payload
        else:
            assert not result.errors, result.errors
            assert result.base_payload["proxyCommPort"] == "50"
            assert result.deploy_item_body["comPort"] == 50


# ── 4.2 四串口项命名区域与下拉 ──


class TestSerialNamedRanges:
    """四串口项（波特率/停止位/校验位/数据位）命名区域与 INDIRECT 下拉。"""

    def test_named_ranges_exist(self, v14_workbook):
        """工作簿含四串口项命名区域。"""
        defined_names = {dn.name for dn in v14_workbook.defined_names.values()}
        assert "BAUD_RATE" in defined_names
        assert "STOP_DIGIT" in defined_names
        assert "CHECK_DIGIT" in defined_names
        assert "DATA_DIGIT" in defined_names

    def test_indirect_formulas(self, v14_workbook):
        """监测点·XLBA 的四串口项列使用 INDIRECT 公式。"""
        ws = v14_workbook[SHEET_METER_XLBA]
        # 查找数据验证
        baud_dv = None
        for dv in ws.data_validations.dataValidation:
            # 波特率列（第 12 列）
            if str(dv.sqref) == "L2:L10001":
                baud_dv = dv
                break
        assert baud_dv is not None
        assert baud_dv.type == "list"
        assert baud_dv.allow_blank is True
        assert "INDIRECT" in baud_dv.formula1
        assert "BAUD_RATE" in baud_dv.formula1

    def test_tail_row_coverage(self, v14_workbook):
        """下拉覆盖第 2～10001 行（尾部选项可选）。"""
        ws = v14_workbook[SHEET_METER_XLBA]
        # 波特率列（第 12 列）数据验证范围
        for dv in ws.data_validations.dataValidation:
            if "L2:L10001" in str(dv.sqref):
                assert str(dv.sqref) == "L2:L10001"
                break
        else:
            pytest.fail("未找到波特率列的数据验证")


# ── 4.3 品牌型号级联与长列表处理 ──


def _named_rows(wb: Workbook, name: str) -> list[tuple]:
    """读取单一区域名称的实际单元格，不模拟 Excel 公式计算。"""
    destinations = list(wb.defined_names[name].destinations)
    assert len(destinations) == 1
    sheet, address = destinations[0]
    return [tuple(cell.value for cell in row) for row in wb[sheet][address]]


def _model_validation(wb: Workbook) -> DataValidation:
    """获取覆盖完整型号输入列的唯一数据验证。"""
    validations = [
        dv for dv in wb[SHEET_METER_XLBA].data_validations.dataValidation
        if str(dv.sqref) == "H2:H10001"
    ]
    assert len(validations) == 1
    return validations[0]


class TestBrandModelCascade:
    """验证有界型号区域、显式品牌映射及原有下拉契约。"""

    def test_brand_named_ranges(self, v14_workbook: Workbook) -> None:
        """逐品牌检查区域内容，避免仅断言公式中存在函数名。"""
        mapping = dict(_named_rows(v14_workbook, "XLPA_MODEL_MAP"))
        assert set(mapping) == {"安科瑞", "美的"}
        for brand, range_name in mapping.items():
            assert re.fullmatch(r"XLPA_MODEL_\d+", range_name)
            expected = [(model["name"],) for model in _SAMPLE_MODELS[brand]]
            assert _named_rows(v14_workbook, range_name) == expected
        assert _named_rows(v14_workbook, "XLPA_MODEL_EMPTY") == [(None,)]

    @pytest.mark.parametrize("models", [{}, {"空品牌": []}])
    def test_empty_brand_models(self, tmp_path: Path, models: dict) -> None:
        """缺失型号键与空型号列表均映射到真实空白单元格。"""
        out = generate_template(
            tmp_path / "empty.xlsx",
            brands=[{"name": "空品牌", "code": "99"}],
            models_by_brand=models,
        )
        wb = load_workbook(out)
        assert _named_rows(wb, "XLPA_MODEL_MAP") == [("空品牌", "XLPA_MODEL_EMPTY")]
        assert _named_rows(wb, "XLPA_MODEL_EMPTY") == [(None,)]
        wb.close()

    def test_no_brands(self, tmp_path: Path) -> None:
        """空字典仍生成合法的有界查找区域和空白回退区域。"""
        wb = load_workbook(generate_template(tmp_path / "no_brands.xlsx"))
        assert _named_rows(wb, "XLPA_MODEL_MAP") == [(None, None)]
        assert _named_rows(wb, "XLPA_MODEL_EMPTY") == [(None,)]
        assert _model_validation(wb).allow_blank is True
        wb.close()

    def test_large_reordered_model_pools(self, tmp_path: Path) -> None:
        """覆盖特殊品牌名、重复品牌、长列表与 Z 之后的倒序型号列。"""
        names = ["安 科 瑞", "福州创安恒业(局放)", "AI2000", "123", "AB*", "A?B", "A~B"]
        names.extend(f"测试品牌{index}" for index in range(153))
        brands = [{"name": name, "code": str(index)} for index, name in enumerate(names)]
        models = {
            name: [{"name": f"{name}-型号-{index}", "code": str(index)} for index in range(5)]
            for name in reversed(names)
        }
        models[names[0]] = [
            {"name": f"长列表型号{index:03}", "code": str(index)} for index in range(300)
        ]
        out = generate_template(
            tmp_path / "large.xlsx", brands=brands + [brands[0]], models_by_brand=models,
        )
        wb = load_workbook(out)
        mapping = dict(_named_rows(wb, "XLPA_MODEL_MAP"))
        assert set(mapping) == set(names)
        for brand in names:
            assert _named_rows(wb, mapping[brand]) == [(m["name"],) for m in models[brand]]
        ws = wb[SHEET_DICT]
        for column in range(1, 171):
            assert not ws.column_dimensions[get_column_letter(column)].hidden
        for column in range(171, ws.max_column + 1):
            assert ws.column_dimensions[get_column_letter(column)].hidden
        wb.close()

    def test_cascade_formula_and_row_scope(self, v14_workbook: Workbook) -> None:
        """固定品牌列但不固定行，并转义精确查找中的通配符。"""
        dv = _model_validation(v14_workbook)
        expected = (
            'INDIRECT(IF($G2="","XLPA_MODEL_EMPTY",IFERROR(VLOOKUP('
            'SUBSTITUTE(SUBSTITUTE(SUBSTITUTE($G2,"~","~~"),"*","~*"),"?","~?"),'
            'XLPA_MODEL_MAP,2,FALSE),"XLPA_MODEL_EMPTY")))'
        )
        assert dv.formula1 == expected
        assert len(expected) < 255
        assert dv.type == "list" and dv.allow_blank is True
        assert dv.showDropDown is False
        for target in ("H3", "H10001", "I3"):
            translated = Translator("=" + expected, origin="H2").translate_formula(target)
            row = "10001" if target == "H10001" else "3"
            assert f"$G{row}" in translated
            assert "$H" not in translated

    def test_other_validations_unchanged(self, v14_workbook: Workbook) -> None:
        """保留原有下拉与命名区域，只增加通信端口下拉与 IP地址/IP端口号提示。"""
        actual = {
            str(dv.sqref): dv.formula1
            for dv in v14_workbook[SHEET_METER_XLBA].data_validations.dataValidation
            if str(dv.sqref) != "H2:H10001"
        }
        assert actual == {
            "E2:E10001": '"新联MQTT协议,上海MQTT协议"',
            "F2:F10001": '"电表类"',
            "I2:I10001": '"15秒,1分钟,5分钟,15分钟,60分钟,24小时,不抄表"',
            "K2:K10001": '"' + ",".join(name for name, _ in _EXPECTED_COMM_PORTS) + '"',
            "G2:G10001": 'INDIRECT("BRAND")',
            "L2:L10001": 'INDIRECT("BAUD_RATE")',
            "M2:M10001": 'INDIRECT("STOP_DIGIT")',
            "N2:N10001": 'INDIRECT("CHECK_DIGIT")',
            "O2:O10001": 'INDIRECT("DATA_DIGIT")',
            # IP地址/IP端口号：文本长度校验仅作输入提示，无公式（不阻断合法值）
            "P2:P10001": None,
            "Q2:Q10001": None,
        }
        for name, column in (
            ("BRAND", "J"), ("BAUD_RATE", "F"), ("STOP_DIGIT", "G"),
            ("CHECK_DIGIT", "H"), ("DATA_DIGIT", "I"),
        ):
            assert v14_workbook.defined_names[name].attr_text == f"'字典'!${column}$2:${column}$9"
        assert not v14_workbook[SHEET_GW_8163].data_validations.dataValidation

    def test_auxiliary_ranges_leave_existing_data_unchanged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """对照禁用辅助区域的生成结果，逐单元格检查原有六表不变。"""

        def omit_model_ranges(*args: object) -> None:
            """仅禁用本次新增的辅助区域，作为原有数据的对照。"""
            return None

        options = {
            "device_types": _SAMPLE_DEVICE_TYPES,
            "user_big_nos": _SAMPLE_USER_BIG_NOS,
            "comm_modes": _SAMPLE_COMM_MODES,
            "brands": _SAMPLE_BRANDS,
            "models_by_brand": _SAMPLE_MODELS,
            "snapshot_id": "same-snapshot",
            "source_time": "2026-09-23T00:00:00+00:00",
            "fetched_at": "2026-09-23T00:00:00+00:00",
        }
        with monkeypatch.context() as patch:
            patch.setattr(generator, "_write_model_ranges", omit_model_ranges)
            before = load_workbook(generate_template(tmp_path / "before.xlsx", **options))
        after = load_workbook(generate_template(tmp_path / "after.xlsx", **options))
        assert before.sheetnames == after.sheetnames
        for name in before.sheetnames:
            old_ws, new_ws = before[name], after[name]
            assert old_ws.max_row == new_ws.max_row
            expected_columns = old_ws.max_column + (3 if name == SHEET_DICT else 0)
            assert new_ws.max_column == expected_columns
            assert list(old_ws.values) == list(new_ws.iter_rows(
                max_row=old_ws.max_row, max_col=old_ws.max_column, values_only=True,
            ))
            assert old_ws.merged_cells == new_ws.merged_cells
        for name, definition in before.defined_names.items():
            assert after.defined_names[name] == definition
        before.close()
        after.close()

    def test_saved_xml_and_mapping(self, tmp_path: Path) -> None:
        """保存重读后保留数据验证和零码值，不改变解析端的业务映射。"""
        out = generate_template(
            tmp_path / "roundtrip.xlsx",
            user_big_nos=[{"name": "电表类", "code": "11"}],
            brands=[{"name": "测试品牌", "code": "0"}],
            models_by_brand={"测试品牌": [{"name": "测试型号", "code": "0"}]},
        )
        with ZipFile(out) as archive:
            ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            root = ElementTree.fromstring(archive.read("xl/worksheets/sheet5.xml"))
            model = root.find("s:dataValidations/s:dataValidation[@sqref='H2:H10001']", ns)
            assert model is not None
            assert model.get("showDropDown") == "0"
            assert "XLPA_MODEL_MAP" in model.find("s:formula1", ns).text
            port = root.find("s:dataValidations/s:dataValidation[@sqref='K2:K10001']", ns)
            assert port is not None
            assert port.get("showDropDown") == "0"
            assert port.find("s:formula1", ns).text == (
                '"' + ",".join(name for name, _ in _EXPECTED_COMM_PORTS) + '"'
            )
        parsed = read_archive_template(out)
        assert parsed.task_config.brand_name_to_code == {"测试品牌": "0"}
        assert parsed.task_config.model_code_by_brand == {"测试品牌": {"测试型号": "0"}}
        assert parsed.task_config.user_big_no_name_to_code == {"电表类": "11"}


@pytest.mark.skipif(
    not os.environ.get("PCA_SPREADSHEET_COM"),
    reason="需显式设置 PCA_SPREADSHEET_COM 才启动本机表格程序进行兼容验证",
)
def test_model_dropdown_in_spreadsheet(tmp_path: Path) -> None:
    """通过真实表格引擎验证生成文件的列表、逐行有效性及保存重开。"""
    client = pytest.importorskip("win32com.client")
    names = [
        "安科瑞", "福州创安恒业(局放)", "AI2000", "安 科 瑞", "123",
        "ABX", "AB*", "A?B", "A~B",
    ]
    names.extend(f"测试品牌{index}" for index in range(151))
    brands = [{"name": name, "code": str(index)} for index, name in enumerate(names)]
    brands.extend([{"name": "空型号", "code": "998"}, {"name": "缺失型号", "code": "999"}])
    models = {
        name: [{"name": f"{name}-型号{index}", "code": str(index)} for index in range(5)]
        for name in reversed(names)
    }
    models["安科瑞"] = [
        {"name": name, "code": str(index)}
        for index, name in enumerate(["ADW300", "APM5", "PZ", "如皋八院电表", "AMC"])
    ]
    models[names[-1]] = [
        {"name": f"长型号{index}", "code": str(index)} for index in range(300)
    ]
    models["空型号"] = []
    out = generate_template(tmp_path / "spreadsheet.xlsx", brands=brands, models_by_brand=models)
    loaded = load_workbook(out)
    formula = _model_validation(loaded).formula1
    loaded.close()
    app = client.DispatchEx(os.environ["PCA_SPREADSHEET_COM"])
    if app.Workbooks.Count:
        pytest.skip("表格程序复用了已有工作簿的实例，不操作用户会话")
    book = None
    try:
        app.Visible = False
        app.DisplayAlerts = False
        app.AutomationSecurity = 3
        print(f"表格引擎：{app.Name} {app.Version}；路径：{app.Path}")
        book = app.Workbooks.Open(str(out.resolve()), UpdateLinks=0)
        ws = book.Worksheets(SHEET_METER_XLBA)
        ws.Activate()

        def calculate(expressions: list[str]) -> list[object]:
            """用测试副本中的单元格计算，规避 WPS Evaluate 的引用差异。"""
            target = ws.Range(f"V1:V{len(expressions)}")
            target.Formula = tuple(("=" + expression,) for expression in expressions)
            ws.Calculate()
            return [row[0] for row in target.Value]

        for index, name in enumerate(names):
            row = index + 2
            ws.Range(f"G{row}").Value = name
            translated = Translator("=" + formula, origin="H2").translate_formula(f"H{row}")
            expression = translated.removeprefix("=")
            expected = [model["name"] for model in models[name]]
            values = calculate(
                [f"ROWS({expression})", f"COLUMNS({expression})"]
                + [f"INDEX({expression},{i},1)" for i in range(1, len(expected) + 1)]
            )
            assert values[:2] == [len(expected), 1], name
            assert values[2:] == expected, name
            cell = ws.Range(f"H{row}")
            cell.Value = expected[-1]
            assert cell.Validation.Value is True, name
            cell.Value = "不属于该品牌的型号"
            assert cell.Validation.Value is False, name
            cell.Value = expected[0]
        for name in ("", "不存在的品牌", "空型号", "缺失型号"):
            ws.Range("G10001").Value = name
            translated = Translator("=" + formula, origin="H2").translate_formula("H10001")
            expression = translated.removeprefix("=")
            values = calculate([f"ROWS({expression})", f"ISBLANK(INDEX({expression},1,1))"])
            assert values[0] == 1
            assert values[1] is True
        ws.Range("G10001").Value = "安科瑞"
        ws.Range("H10001").Value = "AMC"
        assert ws.Range("H10001").Validation.Value is True
        ws.Range("G2").Value = "AI2000"
        assert ws.Range("H2").Validation.Value is False
        ws.Range("H2").Value = models["AI2000"][0]["name"]
        assert ws.Range("H2").Validation.Value is True
        for name, _ in _EXPECTED_COMM_PORTS:
            ws.Range("K2").Value = name
            assert ws.Range("K2").Validation.Value is True, name
        ws.Range("K10001").Value = "未知端口"
        assert ws.Range("K10001").Validation.Value is False
        ws.Range("K10001").Value = "监听RS485-2"
        assert ws.Range("K10001").Validation.Value is True
        ws.Range("V1:V302").ClearContents()
        book.Save()
        cell = None
        ws = None
        book.Close(False)
        book = None
        book = app.Workbooks.Open(str(out.resolve()), UpdateLinks=0)
        ws = book.Worksheets(SHEET_METER_XLBA)
        assert ws.Range("H2").Validation.Value is True
        assert ws.Range("H10001").Validation.Value is True
        assert ws.Range("H10001").Validation.InCellDropdown is True
        assert ws.Range("H2").Validation.Type == 3
        assert ws.Range("K2").Validation.Value is True
        assert ws.Range("K10001").Validation.Value is True
        assert ws.Range("K10001").Validation.InCellDropdown is True
        assert ws.Range("K2").Validation.Type == 3
    finally:
        cell = None
        ws = None
        try:
            if book is not None:
                book.Close(False)
        finally:
            book = None
            app.Quit()
            app = None
