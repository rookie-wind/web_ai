"""v15-engineer 模板生成器（六表 + 每类监测点各自一张明细表 + 版本化元数据）。

面向工程人员的自包含工作簿，按 design §5 与 field_contract（2.1）生成：
  - 系统连接：目标 IP/端口/账号/密码 + 执行策略（**不预置 175/23**）
  - 字典：一列一池（设备类型/协议代号/用户大分类号/抄表间隔/代理通信方式/
    波特率/停止位/校验位/数据位/品牌 + 每品牌型号级联）
  - 挂载关系：挂载点/监测点/网关类型（只表拓扑不存条码）
  - 网关·8163：设备名称/设备条码/代理通信方式（下拉）
  - 监测点·XLBA / 监测点·照明 / 监测点·配电房：每类监测点各自一张
    20 列明细表（契约均取自 field_contract 对应 spec，列集相同）
  - 映射：字段/下拉选项/后端字段/实际写入值/出处

新增监测点类型 = 加 profile + 加一条 TypeSheetSpec（明表自动纳入）。
"""

from __future__ import annotations

__all__ = [
    "generate_template",
    "TEMPLATE_VERSION",
    "FIELD_CONTRACT_VERSION",
    "SHEET_SYSTEM_CONNECTION",
    "SHEET_DICT",
    "SHEET_TOPO",
    "SHEET_GW_8163",
    "SHEET_METER_XLBA",
    "SHEET_METER_LIGHTING",
    "SHEET_METER_PDB",
    "MONITOR_SHEET_NAMES",
    "SHEET_MAPPING",
    "MAX_DATA_ROWS",
    "SNAPSHOT_TTL_DAYS",
]

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter, quote_sheetname
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.worksheet import Worksheet

from ..field_contract import (
    COMM_PORT_CODE_MAP,
    LIGHTING_SHEET_SPEC,
    PDB_SHEET_SPEC,
    XLBA_METER_SHEET_SPEC,
    monitor_sheet_specs,
)

# 模板与契约版本（reader 校验，防止现场误用旧表）
TEMPLATE_VERSION = "v15-engineer"
FIELD_CONTRACT_VERSION = "fc-v1"

# ── sheet 名称（reader/profile 共享契约）──
SHEET_SYSTEM_CONNECTION = "系统连接"
SHEET_DICT = "字典"
SHEET_TOPO = "挂载关系"
SHEET_GW_8163 = "网关·8163"
SHEET_METER_XLBA = XLBA_METER_SHEET_SPEC.sheet_name
SHEET_METER_LIGHTING = LIGHTING_SHEET_SPEC.sheet_name
SHEET_METER_PDB = PDB_SHEET_SPEC.sheet_name
# 全部监测点类型 sheet 名（由 field_contract 契约驱动，新增类型自动纳入）
MONITOR_SHEET_NAMES = [spec.sheet_name for spec in monitor_sheet_specs()]
SHEET_MAPPING = "映射"

# 工程输入最大行数（design §5：第 2～10001 行）
MAX_DATA_ROWS = 10000
# 快照有效期（design §2）
SNAPSHOT_TTL_DAYS = 30

# ── 系统连接：全中文配置项（`配置项/值/说明`，不预置现场地址）──
_CONN_KEYS = [
    ("目标系统IP", "边缘建档后端主机 IP（必填）"),
    ("后端端口", "边缘建档后端端口（如 7500）"),
    ("账号", "边缘后端登录名（必填）"),
    ("密码", "边缘后端登录密码（输出脱敏）"),
    ("手机号", "联网验证手机号（可选）"),
    ("验证码", "联网验证码（可选）"),
]

# ── 网关·8163 三列（按 field_contract GATEWAY_8163_SHEET_SPEC）──
_GW_COLUMNS = ["设备名称", "设备条码", "代理通信方式"]

# ── 监测点·XLBA 20 列（按 field_contract XLBA_METER_SHEET_SPEC）──
_METER_COLUMNS = [
    "设备名称", "设备条码", "测量点号", "分路号",
    "协议代号", "用户大分类号", "品牌", "型号", "抄表间隔",
    "代理通信方式", "通信端口号", "波特率", "停止位", "校验位",
    "数据位", "IP地址", "IP端口号", "采集器地址", "电流变比", "电压变比",
]

# 协议固定枚举（来自 field_contract，不属平台字典）
_BAUD_RATES = ["38400", "115200", "1200", "2400", "4800", "7200", "9600", "19200"]
_STOP_DIGITS = ["1位停止位", "2位停止位"]
_CHECK_DIGITS = ["无校验", "偶校验", "奇校验"]
_DATA_DIGITS = ["5位", "6位", "7位", "8位"]
_INTERVALS = ["15秒", "1分钟", "5分钟", "15分钟", "60分钟", "24小时", "不抄表"]
_PROTOCOL_NUMBERS = ["新联MQTT协议", "上海MQTT协议"]


def _write_header(ws, columns: list[str]) -> None:
    """写入加粗表头行并设置列宽。

    Args:
        ws: openpyxl 工作表。
        columns: 列名列表。
    """
    ws.append(columns)
    for idx in range(1, len(columns) + 1):
        ws.cell(row=1, column=idx).font = Font(bold=True)
        ws.column_dimensions[get_column_letter(idx)].width = 18


def _write_rows(ws, rows: list[list]) -> None:
    """写入数据行。

    Args:
        ws: openpyxl 工作表。
        rows: 行数据列表。
    """
    for row in rows:
        ws.append(row)


def _write_system_connection(
    ws,
    *,
    snapshot_id: str,
    source_time: str,
    fetched_at: str,
) -> None:
    """写入系统连接 sheet（目标连接 + 元数据，不预置现场地址）。

    Args:
        ws: 系统连接 openpyxl 工作表。
        snapshot_id: 快照 ID。
        source_time: 字典来源时间。
        fetched_at: 获取时间。
    """
    _write_header(ws, ["配置项", "值", "说明"])
    # 元数据（只读，工程人员不修改；整行隐藏，reader 仍可读）
    meta = [
        ("__template_version", TEMPLATE_VERSION, "模板结构版本（reader 校验）"),
        ("__field_contract_version", FIELD_CONTRACT_VERSION, "字段契约版本"),
        ("__snapshot_id", snapshot_id, "服务端权威快照 ID"),
        ("__source_time", source_time, "字典来源时间（ISO）"),
        ("__fetched_at", fetched_at, "模板生成时间（ISO）"),
        ("__max_data_rows", str(MAX_DATA_ROWS), "工程输入最大行数"),
        ("__snapshot_ttl_days", str(SNAPSHOT_TTL_DAYS), "快照有效期（天）"),
    ]
    start = ws.max_row + 1
    _write_rows(ws, [list(row) for row in meta])
    for r in range(start, start + len(meta)):
        ws.row_dimensions[r].hidden = True
    # 空行分隔
    ws.append([])
    # 目标现场连接（初始空白，工程人员填写）
    _write_rows(ws, [["# 目标现场连接（工程人员填写）", "", ""]])
    for key, desc in _CONN_KEYS:
        ws.append([key, "", desc])
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 30
    ws.column_dimensions["C"].width = 50


def _write_dict_sheet(
    wb,
    ws,
    *,
    device_types: list[dict],
    user_big_nos: list[dict],
    comm_modes: list[dict],
    brands: list[dict],
    models_by_brand: dict[str, list[dict]],
) -> None:
    """写入字典 sheet（一列一池 + 四串口项命名区域 + 品牌型号级联列结构）。

    Args:
        wb: openpyxl 工作簿（用于创建命名区域）。
        ws: 字典 openpyxl 工作表。
        device_types: 设备类型列表 [{name, code}]。
        user_big_nos: 用户大分类列表 [{name, code}]。
        comm_modes: 代理通信方式列表 [{name, code}]。
        brands: 品牌列表 [{name, code}]。
        models_by_brand: 品牌名到型号列表的映射 {brand_name: [{name, code}]}。
    """
    # 列顺序（design §4）：设备类型/协议代号/用户大分类号/抄表间隔/代理通信方式/
    # 波特率/停止位/校验位/数据位/品牌 + 每品牌型号
    pools = [
        ("设备类型", device_types),
        ("协议代号", [{"name": n, "code": ""} for n in _PROTOCOL_NUMBERS]),
        ("用户大分类号", user_big_nos),
        ("抄表间隔", [{"name": n, "code": ""} for n in _INTERVALS]),
        ("代理通信方式", comm_modes),
        ("波特率", [{"name": n, "code": ""} for n in _BAUD_RATES]),
        ("停止位", [{"name": n, "code": ""} for n in _STOP_DIGITS]),
        ("校验位", [{"name": n, "code": ""} for n in _CHECK_DIGITS]),
        ("数据位", [{"name": n, "code": ""} for n in _DATA_DIGITS]),
        ("品牌", brands),
    ]
    # 写表头
    headers = [name for name, _ in pools]
    for brand_name in models_by_brand:
        headers.append(f"型号·{brand_name}")
    _write_header(ws, headers)
    # 写池数据（每列独立，空位留空）
    max_len = max((len(items) for _, items in pools), default=0)
    for brand_name, models in models_by_brand.items():
        max_len = max(max_len, len(models))
    for row_idx in range(max_len):
        row = []
        for _, items in pools:
            if row_idx < len(items):
                row.append(items[row_idx]["name"])
            else:
                row.append("")
        for brand_name in models_by_brand:
            models = models_by_brand[brand_name]
            if row_idx < len(models):
                row.append(models[row_idx]["name"])
            else:
                row.append("")
        ws.append(row)
    # 为下拉列创建命名区域（品牌 + 四串口项）
    col_index = {name: idx + 1 for idx, name in enumerate(headers)}
    # 命名区域使用英文名（Excel 兼容）
    named_pools = [
        ("品牌", "BRAND"),
        ("波特率", "BAUD_RATE"),
        ("停止位", "STOP_DIGIT"),
        ("校验位", "CHECK_DIGIT"),
        ("数据位", "DATA_DIGIT"),
    ]
    for pool_name, range_name in named_pools:
        col_idx = col_index[pool_name]
        letter = get_column_letter(col_idx)
        # 命名区域引用字典 sheet 的数据列（第 2 行到 max_len+1 行）
        formula = f"'{ws.title}'!${letter}$2:${letter}${max_len + 1}"
        defn = DefinedName(range_name, attr_text=formula)
        wb.defined_names.add(defn)
    _write_model_ranges(
        wb, ws, brands, models_by_brand,
        {name: col_index[f"型号·{name}"] for name in models_by_brand},
    )


def _write_model_ranges(
    wb: Workbook,
    ws: Worksheet,
    brands: list[dict],
    models_by_brand: dict[str, list[dict]],
    model_columns: dict[str, int],
) -> None:
    """为型号下拉建立有界区域与隐藏的品牌到区域名映射。

    型号区域按品牌键定位，不依赖品牌列表与型号列的排列顺序。
    内部名称只含 ASCII 编号，避免品牌中的括号、空格等影响引用。
    仅在字典末尾追加隐藏辅助列，不改动已有列和业务码值映射。
    """
    first_col = ws.max_column + 1
    for offset, header in enumerate(("__model_brand", "__model_range", "__model_empty")):
        column = first_col + offset
        ws.cell(row=1, column=column, value=header)
        ws.column_dimensions[get_column_letter(column)].hidden = True
    sheet = quote_sheetname(ws.title)
    empty_col = get_column_letter(first_col + 2)
    wb.defined_names.add(DefinedName(
        "XLPA_MODEL_EMPTY", attr_text=f"{sheet}!${empty_col}$2:${empty_col}$2",
    ))
    brand_names = list(dict.fromkeys(item["name"] for item in brands))
    for index, brand_name in enumerate(brand_names, start=1):
        models = models_by_brand.get(brand_name, [])
        range_name = "XLPA_MODEL_EMPTY"
        if models:
            letter = get_column_letter(model_columns[brand_name])
            range_name = f"XLPA_MODEL_{index}"
            wb.defined_names.add(DefinedName(
                range_name, attr_text=f"{sheet}!${letter}$2:${letter}${len(models) + 1}",
            ))
        cell = ws.cell(row=index + 1, column=first_col, value=brand_name)
        cell.data_type = "s"
        ws.cell(row=index + 1, column=first_col + 1, value=range_name)
    start = get_column_letter(first_col)
    end = get_column_letter(first_col + 1)
    last_row = max(len(brand_names), 1) + 1
    wb.defined_names.add(DefinedName(
        "XLPA_MODEL_MAP", attr_text=f"{sheet}!${start}$2:${end}${last_row}",
    ))


def _write_topo(ws) -> None:
    """写入挂载关系 sheet（名称驱动 3 列，只表达拓扑不存条码）。

    列顺序：``挂载点``（网关）/``监测点``/``网关类型``。一个挂载点（网关）
    可挂多个监测点；同一挂载点的相邻行做**合并居中**（A 列与 C 列按块合并，
    B 列逐行写监测点）。首行为示例块，示范合并写法，工程人员可覆盖。
    监测点类型不再由本表列决定，而是由监测点名称所在的 监测点·X 明细表确定。

    Args:
        ws: 挂载关系 openpyxl 工作表。
    """
    _write_header(ws, ["挂载点", "监测点", "网关类型"])
    # 示例：同一挂载点（网关）挂两个监测点，挂载点/网关类型合并居中
    ws.append(["示例网关", "示例电表1", "8163网关"])
    ws.append(["", "示例电表2", ""])
    ws.merge_cells("A2:A3")
    ws.merge_cells("C2:C3")
    for r in (2, 3):
        ws.cell(row=r, column=1).alignment = Alignment(
            horizontal="center", vertical="center"
        )
        ws.cell(row=r, column=3).alignment = Alignment(
            horizontal="center", vertical="center"
        )


def _write_gateway_8163(ws, comm_mode_names: list[str]) -> None:
    """写入网关·8163 sheet（三列；代理通信方式为自由填写，无下拉）。

    Args:
        ws: 网关 openpyxl 工作表。
        comm_mode_names: 代理通信方式友好名列表（保留参数以便调用方不变）。
    """
    _write_header(ws, _GW_COLUMNS)


def _write_meter_sheet(
    ws,
    *,
    protocol_names: list[str],
    user_big_names: list[str],
    brand_names: list[str],
    interval_names: list[str],
    comm_mode_names: list[str],
    baud_names: list[str],
    stop_names: list[str],
    check_names: list[str],
    data_names: list[str],
) -> None:
    """写入一张监测点明细 sheet（20 列 + 下拉，无示例）。

    照明/配电房与 XLBA 列集完全一致，故共用本写入器；调用方按
    field_contract 监测点契约逐张建表。

    Args:
        ws: 监测点明细 openpyxl 工作表。
        protocol_names: 协议代号选项。
        user_big_names: 用户大分类号选项。
        brand_names: 品牌选项。
        interval_names: 抄表间隔选项。
        comm_mode_names: 代理通信方式选项。
        baud_names: 波特率选项。
        stop_names: 停止位选项。
        check_names: 校验位选项。
        data_names: 数据位选项。
    """
    _write_header(ws, _METER_COLUMNS)
    col_index = {name: idx + 1 for idx, name in enumerate(_METER_COLUMNS)}
    # 直接列表下拉（选项少，不超 255 字符限制）
    # 代理通信方式继续自由填写；通信端口号使用前端实际的 21 项。
    direct_dropdowns = [
        ("协议代号", protocol_names),
        ("用户大分类号", user_big_names),
        ("抄表间隔", interval_names),
        ("通信端口号", list(COMM_PORT_CODE_MAP)),
    ]
    for col_name, options in direct_dropdowns:
        idx = col_index.get(col_name)
        if not idx or not options:
            continue
        letter = get_column_letter(idx)
        dv = DataValidation(
            type="list",
            allow_blank=True,
            formula1='"' + ",".join(options) + '"',
        )
        dv.error = "请从下拉列表选择"
        if col_name == "通信端口号":
            dv.showInputMessage = True
            dv.promptTitle = "通信端口号"
            dv.prompt = "可选前端端口名称；兼容原数字输入。43/44专用模式暂不支持。"
        ws.add_data_validation(dv)
        dv.add(f"{letter}2:{letter}{MAX_DATA_ROWS + 1}")
    # IP地址/IP端口号：经 ETH/MQTT 端口时拼入 extInfos.authParam（5 段逗号串）；
    # 串口端口下承载电表密码，禁止填写这两列（profile 阻断）。
    for ip_col, ip_prompt_title in (("IP地址", "IP地址"), ("IP端口号", "IP端口号")):
        idx = col_index.get(ip_col)
        if not idx:
            continue
        dv_ip = DataValidation(type="textLength", allow_blank=True)
        dv_ip.error = None
        dv_ip.showErrorMessage = False
        dv_ip.showInputMessage = True
        dv_ip.promptTitle = ip_prompt_title
        dv_ip.prompt = (
            "仅 ETH-1/ETH-2/MQTT 端口填写；与另一列拼为 "
            "ip1,ip2,ip3,ip4,port 写入 authParam。RS485 等串口端口请留空。"
        )
        ws.add_data_validation(dv_ip)
        letter = get_column_letter(idx)
        dv_ip.add(f"{letter}2:{letter}{MAX_DATA_ROWS + 1}")
    # INDIRECT 引用命名区域下拉（品牌 / 四串口项）
    # 品牌选项超过 255 字符时无法使用内联逗号分隔，必须引用命名区域。
    indirect_dropdowns = [
        ("品牌", "BRAND"),
        ("波特率", "BAUD_RATE"),
        ("停止位", "STOP_DIGIT"),
        ("校验位", "CHECK_DIGIT"),
        ("数据位", "DATA_DIGIT"),
    ]
    for col_name, range_name in indirect_dropdowns:
        idx = col_index.get(col_name)
        if not idx:
            continue
        letter = get_column_letter(idx)
        # INDIRECT 引用命名区域
        dv = DataValidation(
            type="list",
            allow_blank=True,
            formula1=f"INDIRECT(\"{range_name}\")",
        )
        dv.error = "请从下拉列表选择"
        ws.add_data_validation(dv)
        dv.add(f"{letter}2:{letter}{MAX_DATA_ROWS + 1}")
    # 型号列只引用有界命名区域，避免二维 MATCH 与整列 OFFSET 越界。
    model_idx = col_index["型号"]
    brand_idx = col_index["品牌"]
    brand_letter = get_column_letter(brand_idx)
    model_letter = get_column_letter(model_idx)
    brand_cell = f"${brand_letter}2"
    # VLOOKUP 精确模式仍解释通配符，先转义 ~、*、?，按品牌原文查找。
    lookup = (
        f'SUBSTITUTE(SUBSTITUTE(SUBSTITUTE({brand_cell},"~","~~"),'
        '"*","~*"),"?","~?")'
    )
    formula = (
        f'INDIRECT(IF({brand_cell}="","XLPA_MODEL_EMPTY",'
        f'IFERROR(VLOOKUP({lookup},XLPA_MODEL_MAP,2,FALSE),"XLPA_MODEL_EMPTY")))'
    )
    dv_model = DataValidation(type="list", allow_blank=True, formula1=formula)
    dv_model.error = "请先选择品牌"
    ws.add_data_validation(dv_model)
    dv_model.add(f"{model_letter}2:{model_letter}{MAX_DATA_ROWS + 1}")


def _write_mapping_sheet(
    ws,
    *,
    device_types: list[dict],
    user_big_nos: list[dict],
    comm_modes: list[dict],
    brands: list[dict],
    models_by_brand: dict[str, list[dict]],
) -> None:
    """写入映射 sheet（字段/下拉选项/后端字段/实际写入值/出处）。

    Args:
        ws: 映射 openpyxl 工作表。
        device_types: 设备类型列表。
        user_big_nos: 用户大分类列表。
        comm_modes: 代理通信方式列表。
        brands: 品牌列表。
        models_by_brand: 品牌名到型号列表的映射。
    """
    _write_header(ws, ["字段（下拉列）", "下拉选项（工程人员所见）", "后端字段", "实际写入值（码值）", "出处"])
    # 设备类型
    for item in device_types:
        ws.append(["设备类型", item["name"], "deviceTypeId", item["code"], "边缘 getDeviceTypeSelect"])
    # 协议代号
    for name in _PROTOCOL_NUMBERS:
        code = "200" if name == "新联MQTT协议" else "202"
        ws.append(["协议代号", name, "protocolNumber", code, "用户指定"])
    # 用户大分类号
    for item in user_big_nos:
        ws.append(["用户大分类号", item["name"], "userBigNo", item["code"], "云端 get_device_type_list"])
    # 抄表间隔
    interval_codes = {"15秒": "9", "1分钟": "1", "5分钟": "2", "15分钟": "4", "60分钟": "8", "24小时": "10", "不抄表": "0"}
    for name in _INTERVALS:
        ws.append(["抄表间隔", name, "userSmallNo", interval_codes[name], "协议备注6 位域"])
    # 代理通信方式
    for item in comm_modes:
        ws.append(["代理通信方式", item["name"], "proxyCommType", item["code"], "边缘 getDictItemList CommunicationMode"])
    # 波特率
    baud_codes = {"38400": "0", "115200": "1", "1200": "2", "2400": "3", "4800": "4", "7200": "5", "9600": "6", "19200": "7"}
    for name in _BAUD_RATES:
        ws.append(["波特率", name, "baudRate", baud_codes[name], "协议备注2"])
    # 停止位
    stop_codes = {"1位停止位": "0", "2位停止位": "1"}
    for name in _STOP_DIGITS:
        ws.append(["停止位", name, "stopDigit", stop_codes[name], "协议备注2"])
    # 校验位
    check_codes = {"无校验": "0", "偶校验": "2", "奇校验": "3"}
    for name in _CHECK_DIGITS:
        ws.append(["校验位", name, "checkDigit", check_codes[name], "协议备注2"])
    # 数据位
    data_codes = {"5位": "0", "6位": "1", "7位": "2", "8位": "3"}
    for name in _DATA_DIGITS:
        ws.append(["数据位", name, "dataDigit", data_codes[name], "协议备注2"])
    # 品牌
    for item in brands:
        ws.append(["品牌", item["name"], "extInfos.brand", item["code"], "云端 get_brand_list"])
    # 型号（按品牌分组）
    for brand_name, models in models_by_brand.items():
        for item in models:
            ws.append(["型号", f"{brand_name} / {item['name']}", "extInfos.decimalNum", item["code"], "云端 get_model_list"])
    # 监测点类型（每类一张 监测点·X 明细表，类型即表身份）→ 建档 deviceTypeId
    # 与固定字典同区写入（在端口映射之前），保证端口映射仍为唯一尾部追加。
    for spec in monitor_sheet_specs():
        ws.append([
            "监测点明细表", spec.sheet_name, "deviceTypeId", spec.device_type_id,
            "边缘 getDeviceTypeSelect 同源（10.0.17.23 实测建档）",
        ])
    # 追加端口映射，不移动已有字典列、型号辅助区域或原有映射行。
    for name, code in COMM_PORT_CODE_MAP.items():
        ws.append([
            "通信端口号", name, "proxyCommPort", code,
            "23前端XLBA枚举（2026-09-23源码核实）",
        ])
    ws.column_dimensions["A"].width = 20
    ws.column_dimensions["B"].width = 35
    ws.column_dimensions["C"].width = 25
    ws.column_dimensions["D"].width = 20
    ws.column_dimensions["E"].width = 35


def generate_template(
    output_path: str | Path,
    *,
    with_examples: bool = False,  # 向后兼容，v14 无示例设备，忽略
    device_types: list[dict] | None = None,
    user_big_nos: list[dict] | None = None,
    comm_modes: list[dict] | None = None,
    brands: list[dict] | None = None,
    models_by_brand: dict[str, list[dict]] | None = None,
    snapshot_id: str = "",
    source_time: str = "",
    fetched_at: str = "",
) -> Path:
    """生成 v14-engineer 六表自动建档 Excel 模板。

    Args:
        output_path: 输出 .xlsx 路径。
        with_examples: 向后兼容参数，v14 无示例设备，忽略。
        device_types: 设备类型列表 [{name, code}]，默认空。
        user_big_nos: 用户大分类列表，默认空。
        comm_modes: 代理通信方式列表，默认空。
        brands: 品牌列表，默认空。
        models_by_brand: 品牌名到型号列表的映射，默认空。
        snapshot_id: 快照 ID（元数据），默认生成随机。
        source_time: 字典来源时间（ISO），默认当前 UTC。
        fetched_at: 模板生成时间（ISO），默认当前 UTC。

    Returns:
        实际写入的文件路径。
    """
    import secrets

    device_types = device_types or []
    user_big_nos = user_big_nos or []
    comm_modes = comm_modes or []
    brands = brands or []
    models_by_brand = models_by_brand or {}
    if not snapshot_id:
        snapshot_id = secrets.token_hex(16)
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    source_time = source_time or now_iso
    fetched_at = fetched_at or now_iso

    wb = Workbook()

    # Sheet 1：系统连接（目标连接 + 元数据，不预置现场地址）
    ws_conn = wb.active
    ws_conn.title = SHEET_SYSTEM_CONNECTION
    _write_system_connection(
        ws_conn,
        snapshot_id=snapshot_id,
        source_time=source_time,
        fetched_at=fetched_at,
    )

    # Sheet 2：字典（一列一池 + 四串口项命名区域 + 品牌型号级联列结构）
    ws_dict = wb.create_sheet(SHEET_DICT)
    _write_dict_sheet(
        wb,
        ws_dict,
        device_types=device_types,
        user_big_nos=user_big_nos,
        comm_modes=comm_modes,
        brands=brands,
        models_by_brand=models_by_brand,
    )

    # Sheet 3：挂载关系（无示例）
    ws_topo = wb.create_sheet(SHEET_TOPO)
    _write_topo(ws_topo)

    # Sheet 4：网关·8163（三列 + 代理通信方式下拉，无示例）
    ws_gw = wb.create_sheet(SHEET_GW_8163)
    _write_gateway_8163(ws_gw, [item["name"] for item in comm_modes])

    # Sheet 5+：每类监测点各自一张 20 列明细表（无示例，列集均同 XLBA）
    meter_kwargs = dict(
        protocol_names=_PROTOCOL_NUMBERS,
        user_big_names=[item["name"] for item in user_big_nos],
        brand_names=[item["name"] for item in brands],
        interval_names=_INTERVALS,
        comm_mode_names=[item["name"] for item in comm_modes],
        baud_names=_BAUD_RATES,
        stop_names=_STOP_DIGITS,
        check_names=_CHECK_DIGITS,
        data_names=_DATA_DIGITS,
    )
    for spec in monitor_sheet_specs():
        ws_meter = wb.create_sheet(spec.sheet_name)
        _write_meter_sheet(ws_meter, **meter_kwargs)

    # Sheet 6：映射（字段/下拉选项/后端字段/实际写入值/出处）
    ws_map = wb.create_sheet(SHEET_MAPPING)
    _write_mapping_sheet(
        ws_map,
        device_types=device_types,
        user_big_nos=user_big_nos,
        comm_modes=comm_modes,
        brands=brands,
        models_by_brand=models_by_brand,
    )

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return out


# ── 向后兼容别名（旧 reader 过渡，4.4 重构后移除）──
# 旧 reader 导入这些常量以通过 import 阶段，但运行时行为需 4.4 适配 v14 结构
SHEET_README = SHEET_SYSTEM_CONNECTION  # 旧名"说明"→新名"系统连接"
SHEET_CONN = SHEET_SYSTEM_CONNECTION  # 旧名"连接参数"→合并入"系统连接"
SHEET_GW = SHEET_GW_8163  # 旧名"网关"→新名"网关·8163"
SHEET_METER = SHEET_METER_XLBA  # 旧名"监测点"→新名"监测点·XLBA"
GW_KEY_COLUMN = "设备名称"  # v14 网关主键列（名称驱动，条码经 deviceBarcode 关联）
GW_HEADER_MAP = {
    "设备条码": "deviceBarcode",  # 名称→条码回查所需的条码
    "代理通信方式": "proxyCommType",
}
METER_KEY_COLUMN = "设备名称"  # v14 监测点主键列（名称驱动，全局唯一）
METER_HEADER_MAP = {
    "设备名称": "deviceName",
    "设备条码": "deviceBarcode",
    "协议代号": "protocolNumber",
    "用户大分类号": "userBigNo",
    "品牌": "brand",
    "型号": "model",
    "抄表间隔": "interval",
    "代理通信方式": "proxyCommType",
    "通信端口号": "comPort",
    "波特率": "baudRate",
    "停止位": "stopDigit",
    "校验位": "checkDigit",
    "数据位": "dataDigit",
    "IP地址": "ipAddress",
    "IP端口号": "ipPort",
    "采集器地址": "collCommAddr",
    "电流变比": "cT",
    "电压变比": "pT",
    "分路号": "roadNo",
    "测量点号": "measurNo",
}
TOPO_HEADER_MAP = {
    "挂载点": "device_name",
    "监测点": "parent_device_name",
    "网关类型": "device_type",
}
REQUIRED_COLUMNS: dict[str, list[str]] = {
    SHEET_SYSTEM_CONNECTION: ["配置项", "值"],
    SHEET_TOPO: ["挂载点", "监测点", "网关类型"],
    SHEET_GW_8163: ["设备名称", "设备条码"],
}
# 全部已知列（含可选列），用于区分“已知可选”与“真正未知”的表头
KNOWN_COLUMNS: dict[str, set[str]] = {
    SHEET_SYSTEM_CONNECTION: {"配置项", "值", "说明"},
    SHEET_TOPO: {"挂载点", "监测点", "网关类型"},
    SHEET_GW_8163: set(_GW_COLUMNS),
}
# 每张监测点类型表列集相同（均同 XLBA 20 列），按契约动态纳入校验范围
for _monitor_sheet in MONITOR_SHEET_NAMES:
    REQUIRED_COLUMNS[_monitor_sheet] = ["设备名称", "设备条码"]
    KNOWN_COLUMNS[_monitor_sheet] = set(_METER_COLUMNS)
