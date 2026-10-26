"""v15-engineer 模板解析器（类型保真 + 版本化元数据）。

将面向工程人员的 v15 工作簿解析为结构化 ``ArchiveTemplate``：任务配置、
拓扑节点（以条码为主键）、网关明细、监测点明细，并收集版本不符 / 缺列 /
空条码 / 重复条码等可读错误。reader 只做提取与结构性校验，字段级业务校验
交给 profile 与引擎。

类型保真语义：
  - 整数不转浮点（``9600`` 保持 ``"9600"``，非 ``"9600.0"``）
  - ``0`` / ``False`` 不误判为空（合法填写值）
  - 文本条码保留前导零（``"001234"`` 不截断）
  - 密码原文保留（``to_dict`` 默认脱敏，但解析阶段不丢失）
"""

from __future__ import annotations

__all__ = ["ArchiveTemplate", "read_archive_template", "TemplateReadError"]

from dataclasses import dataclass, field
from pathlib import Path

from openpyxl import load_workbook

from .models import TaskConfig, TopologyNode
from .field_contract import monitor_sheet_specs
from .templates.generator import (
    FIELD_CONTRACT_VERSION,
    GW_HEADER_MAP,
    GW_KEY_COLUMN,
    KNOWN_COLUMNS,
    MAX_DATA_ROWS,
    METER_HEADER_MAP,
    METER_KEY_COLUMN,
    REQUIRED_COLUMNS,
    SHEET_GW_8163,
    SHEET_MAPPING,
    SHEET_SYSTEM_CONNECTION,
    SHEET_TOPO,
    TEMPLATE_VERSION,
)

# 任务配置键 -> TaskConfig 字段（中文配置项名，小写匹配）。
# 目标系统IP/后端端口 由 reader 组合成 edge_base_url（http://ip:port）。
_TASK_KEY_MAP = {
    "账号": "login_name",
    "密码": "password",
    "手机号": "phone",
    "验证码": "captcha",
}
# 网关设备类型（多级子网关识别用；与 gateway_8163 profile 同源，单一真源）
_GW_DEVICE_TYPE = "8163网关"
# 布尔真值集合
_TRUE_VALUES = {"true", "1", "yes", "y", "是", "允许", "on"}
# 连接参数必填配置项（中文键，小写匹配）
_TASK_REQUIRED_KEYS = ("目标系统ip", "账号")
# 必填 sheet
_REQUIRED_SHEETS = (SHEET_SYSTEM_CONNECTION, SHEET_TOPO)
# 系统连接 sheet 中元数据键前缀
_META_PREFIX = "__"


class TemplateReadError(Exception):
    """模板文件无法读取（缺失、损坏或非法格式）。"""


@dataclass
class ArchiveTemplate:
    """解析后的自动建档任务模板。"""

    task_config: TaskConfig = field(default_factory=TaskConfig)
    nodes: list[TopologyNode] = field(default_factory=list)
    # 条码 -> 网关明细字段（proxyCommType 等）
    gateway_details: dict[str, dict] = field(default_factory=dict)
    # 条码 -> 监测点明细字段（roadNo / 抄表 propertyCode）
    meter_details: dict[str, dict] = field(default_factory=dict)
    # 元数据（模板版本/快照 ID 等）
    metadata: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """是否无致命解析错误。"""
        return not self.errors

    def node_map(self) -> dict[str, TopologyNode]:
        """返回条码（节点主键）到拓扑节点的映射。"""
        return {node.node_key: node for node in self.nodes if node.node_key}

    def to_dict(self, *, redact: bool = True) -> dict:
        """序列化为字典。

        Args:
            redact: 是否对 password 脱敏，默认 True。

        Returns:
            含任务配置、节点、明细、元数据、错误与提示的字典。
        """
        return {
            "task_config": self.task_config.to_dict(redact=redact),
            "nodes": [node.to_dict() for node in self.nodes],
            "gateway_details": dict(self.gateway_details),
            "meter_details": dict(self.meter_details),
            "metadata": dict(self.metadata),
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "ok": self.ok,
        }


def _cell_str(value) -> str:
    """将单元格值转为字符串，类型保真。

    - None 转空串
    - 整数浮点（如 9600.0）转整数字符串（"9600"）
    - 布尔值转小写（"true"/"false"）
    - 其余转字符串并去首尾空白（保留内部空格与前导零）

    Args:
        value: 单元格原始值。

    Returns:
        字符串表示。
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, int):
        return str(value)
    # 字符串：去首尾空白，保留内部空格与前导零
    return str(value).strip()


def _col_letter(col_idx: int) -> str:
    """将 1-based 列索引转为 Excel 列字母（A、B、...、Z、AA、AB...）。

    Args:
        col_idx: 1-based 列索引。

    Returns:
        Excel 列字母。
    """
    result: list[str] = []
    while col_idx > 0:
        col_idx, remainder = divmod(col_idx - 1, 26)
        result.append(chr(65 + remainder))
    return "".join(reversed(result))


def _header_index(ws) -> dict[str, int]:
    """读取首行表头，返回列名到列索引（0-based）的映射。"""
    headers: dict[str, int] = {}
    first_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())
    for idx, cell in enumerate(first_row):
        name = _cell_str(cell)
        if name:
            headers[name] = idx
    return headers


def _rows_as_dicts(ws, headers: dict[str, int]) -> list[dict]:
    """将数据行按表头映射为字典列表，跳过全空行。"""
    out: list[dict] = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        record = {name: _cell_str(row[idx]) if idx < len(row) else ""
                  for name, idx in headers.items()}
        # 跳过全空行（但 0/"0"/"false" 不算空）
        if any(v or v == "0" or v == "false" for v in record.values()):
            out.append(record)
    return out


def _parse_bool(value: str) -> bool:
    """将字符串解析为布尔值。"""
    return str(value).strip().lower() in _TRUE_VALUES


def _check_version_and_metadata(wb, template: ArchiveTemplate) -> None:
    """校验系统连接 sheet 中的元数据（模板版本/契约版本/快照 ID）。

    Args:
        wb: 已打开的工作簿。
        template: 待收集错误的模板对象。
    """
    if SHEET_SYSTEM_CONNECTION not in wb.sheetnames:
        template.errors.append(f"缺少元数据所在的 {SHEET_SYSTEM_CONNECTION} sheet")
        return
    ws = wb[SHEET_SYSTEM_CONNECTION]
    # 读取键/值列
    metadata: dict[str, str] = {}
    for row in ws.iter_rows(min_row=1, values_only=True):
        if not row or len(row) < 2:
            continue
        key = _cell_str(row[0])
        if key.startswith(_META_PREFIX):
            metadata[key] = _cell_str(row[1])
    template.metadata = metadata
    # 校验模板版本
    file_version = metadata.get("__template_version", "")
    if not file_version:
        template.errors.append(f"{SHEET_SYSTEM_CONNECTION} 未声明 __template_version")
    elif file_version != TEMPLATE_VERSION:
        template.errors.append(
            f"模板版本不符：文件为 {file_version!r}，当前要求 {TEMPLATE_VERSION!r}"
        )
    # 校验契约版本
    file_contract = metadata.get("__field_contract_version", "")
    if file_contract and file_contract != FIELD_CONTRACT_VERSION:
        template.warnings.append(
            f"字段契约版本不符：文件为 {file_contract!r}，当前为 {FIELD_CONTRACT_VERSION!r}"
        )


def _validate_sheet_headers(
    wb, template: ArchiveTemplate,
    sheet_name: str,
    expected_headers: list[str],
) -> dict[str, int] | None:
    """校验 sheet 表头：检查重复、缺失和未知列。

    Args:
        wb: 已打开的工作簿。
        template: 待收集错误的模板对象。
        sheet_name: 目标 sheet 名。
        expected_headers: 期望的表头列表。

    Returns:
        表头名到列索引的映射；校验失败时返回 None。
    """
    if sheet_name not in wb.sheetnames:
        return None
    ws = wb[sheet_name]
    # 读取第一行表头
    raw_headers: list[str] = []
    for cell in next(ws.iter_rows(min_row=1, max_row=1), []):
        val = _cell_str(cell.value)
        if val:
            raw_headers.append(val)
    # 检查重复表头
    seen: dict[str, int] = {}
    for idx, name in enumerate(raw_headers):
        if name in seen:
            col_letter = _col_letter(idx + 1)
            template.errors.append(
                f"{sheet_name}!{col_letter}1: 重复表头 {name!r}"
            )
        seen[name] = idx
    # 检查缺失列
    expected_set = set(expected_headers)
    for name in expected_headers:
        if name not in seen:
            template.errors.append(f"{sheet_name}: 缺少必需列 {name!r}")
    # 检查未知非空列（只警告，不阻止）
    known_set = KNOWN_COLUMNS.get(sheet_name, expected_set)
    for name in raw_headers:
        if name not in known_set:
            template.warnings.append(
                f"{sheet_name}: 未知列 {name!r}（将被忽略）"
            )
    # 只有重复或缺失时才返回 None
    if template.errors:
        return None
    return seen


def _validate_no_formulas_in_data(
    wb, template: ArchiveTemplate,
    sheet_name: str,
    data_start_row: int,
    data_end_row: int,
    data_cols: set[str],
) -> None:
    """校验数据区域无工程公式（避免 data_only=True 误判）。

    Args:
        wb: 已打开的工作簿。
        template: 待收集错误的模板对象。
        sheet_name: 目标 sheet 名。
        data_start_row: 数据起始行（含）。
        data_end_row: 数据结束行（含）。
        data_cols: 数据列名集合（用于匹配列索引）。
    """
    if sheet_name not in wb.sheetnames:
        return
    ws = wb[sheet_name]
    # 获取表头映射
    headers: dict[str, int] = {}
    for idx, cell in enumerate(next(ws.iter_rows(min_row=1, max_row=1), [])):
        val = _cell_str(cell.value)
        if val:
            headers[val] = idx
    # 遍历数据行检查公式
    for row_idx, row in enumerate(
        ws.iter_rows(min_row=data_start_row, max_row=data_end_row),
        start=data_start_row,
    ):
        for col_name in data_cols:
            if col_name not in headers:
                continue
            col_idx = headers[col_name]
            if col_idx >= len(row):
                continue
            cell = row[col_idx]
            # 检查是否有公式（value 以 = 开头）
            if isinstance(cell.value, str) and cell.value.startswith("="):
                col_letter = _col_letter(col_idx + 1)
                template.errors.append(
                    f"{sheet_name}!{col_letter}{row_idx}: "
                    f"工程输入单元格不允许公式（{col_name}）"
                )


def _validate_beyond_declared_range(
    wb, template: ArchiveTemplate,
    sheet_name: str,
    max_data_rows: int,
    header_row: int = 1,
) -> None:
    """校验声明数据范围以外无粘贴的非空行。

    Args:
        wb: 已打开的工作簿。
        template: 待收集错误的模板对象。
        sheet_name: 目标 sheet 名。
        max_data_rows: 声明的最大数据行数。
        header_row: 表头所在行（默认 1）。
    """
    if sheet_name not in wb.sheetnames:
        return
    ws = wb[sheet_name]
    data_start = header_row + 1
    data_end = header_row + max_data_rows
    # 检查超出声明范围的行
    for row_idx, row in enumerate(
        ws.iter_rows(min_row=data_end + 1),
        start=data_end + 1,
    ):
        # 检查是否有非空单元格
        has_content = any(
            cell.value is not None and _cell_str(cell.value)
            for cell in row
        )
        if has_content:
            template.errors.append(
                f"{sheet_name}!A{row_idx}: "
                f"超出声明数据范围（最大 {max_data_rows} 行）"
            )
            break  # 只报第一处


def _parse_task_config(rows: list[dict], template: ArchiveTemplate) -> None:
    """解析系统连接 sheet 行到 TaskConfig（跳过元数据键）。

    中文配置项（`配置项/值`）：账号→login_name、密码→password、
    手机号→phone、验证码→captcha；目标系统IP + 后端端口 组合为
    ``edge_base_url``（http://ip:port）。元数据键（``__``）跳过。

    连接模式按目标 IP 段自动判定：
      - ``10.*.*.*`` → 直连模式（默认）。
      - ``20.*.*.*`` → 门户代理模式（``proxy_mode=True``）。

    Args:
        rows: 配置项/值/说明 行字典列表。
        template: 待填充的模板对象（收集错误）。
    """
    raw: dict[str, str] = {}
    for row in rows:
        key = _cell_str(row.get("配置项") or row.get("键"))
        if not key or key.startswith(_META_PREFIX) or key.startswith("#"):
            continue
        raw[key.lower()] = _cell_str(row.get("值"))

    edge_ip = raw.get("目标系统ip", "")
    edge_port = raw.get("后端端口", "")
    if edge_ip or edge_port:
        if "://" in edge_ip:
            edge_base_url = edge_ip
        else:
            edge_base_url = f"http://{edge_ip}"
            if edge_port:
                edge_base_url = f"{edge_base_url}:{edge_port}"
        raw["edge_base_url"] = edge_base_url

    for required in _TASK_REQUIRED_KEYS:
        if not raw.get(required):
            template.errors.append(f"连接参数缺少必填项 {required}")

    cfg = TaskConfig()
    if raw.get("edge_base_url"):
        cfg.edge_base_url = raw["edge_base_url"]
    for key, value in raw.items():
        field_name = _TASK_KEY_MAP.get(key)
        if field_name is None:
            # 非任务配置键（如 edge_base_url 已单独赋 / 未知项），忽略
            continue
        setattr(cfg, field_name, value)

    # 按目标 IP 段自动判定连接模式：20.* 走门户代理，10.* 直连
    if edge_ip:
        ip_str = edge_ip.replace("http://", "").replace("https://", "")
        ip_str = ip_str.split(":")[0].strip()
        if ip_str.startswith("20."):
            cfg.proxy_mode = True
            # 代理模式需要手机号和验证码（getRSAKey 需要 PhoneNum/Code 头）
            if not cfg.phone:
                raise ValueError(
                    "20.* 网段需要门户代理登录，"
                    "模板「手机号」为必填项",
                )
            if not cfg.captcha:
                raise ValueError(
                    "20.* 网段需要门户代理登录，"
                    "模板「验证码」为必填项",
                )

    template.task_config = cfg


def _parse_topology(rows: list[dict], template: ArchiveTemplate) -> None:
    """解析挂载关系行到以名称为主键的 TopologyNode 列表（名称驱动）。

    三列：``挂载点``（网关名）/``监测点``/``网关类型``。网关以 ``挂载点``
    为键（全局唯一），监测点以 ``监测点`` 为键（全局唯一），``parent_key``
    指向网关名。合并单元格的续行在 ``挂载点``/``网关类型`` 列为空，故按行
    **向前填充**归属到当前挂载点。

    监测点不在此处定类型：类型由名字所在的 监测点·X 明细表决定（在读
    完明细表后的回填阶段赋予）。本函数仅置空 device_type 占位。

    Args:
        rows: 挂载关系行字典列表（键为中文列名）。
        template: 待填充的模板对象。
    """
    # 使用统一名称索引确保每个设备名称只创建一个节点
    name_to_node: dict[str, TopologyNode] = {}
    monitor_parents: dict[str, str] = {}  # 跟踪监测点名称及其父级
    cur_gw = ""
    cur_type = ""
    for row in rows:
        gw = _cell_str(row.get("挂载点"))
        mon = _cell_str(row.get("监测点"))
        ty = _cell_str(row.get("网关类型"))
        if gw:
            cur_gw = gw
        if ty:
            cur_type = ty
        if not cur_gw:
            if mon:
                template.errors.append(
                    f"挂载关系存在无归属挂载点的监测点: {mon}"
                )
            continue
        # 处理挂载点（网关）
        if cur_gw not in name_to_node:
            node = TopologyNode(
                node_key=cur_gw, device_name=cur_gw,
                device_type=cur_type or "", parent_key="",
            )
            name_to_node[cur_gw] = node
            template.nodes.append(node)
        else:
            # 已有节点：用当前块的网关类型回填（合并单元格续行 type 为空）
            existing = name_to_node[cur_gw]
            if cur_type:
                existing.device_type = cur_type
        # 处理监测点
        if mon:
            if mon in monitor_parents:
                # 监测点名称已作为监测点出现过
                prev_parent = monitor_parents[mon]
                if prev_parent == cur_gw:
                    # 同一网关下重复
                    template.errors.append(f"挂载关系监测点名重复: {mon}")
                else:
                    # 不同网关下出现，多父冲突
                    template.errors.append(
                        f"挂载关系监测点名多父冲突: {mon} "
                        f"(已有父级 {prev_parent}, 当前 {cur_gw})"
                    )
                continue
            monitor_parents[mon] = cur_gw
            if mon not in name_to_node:
                node = TopologyNode(
                    node_key=mon, device_name=mon,
                    device_type="", parent_key=cur_gw,
                )
                name_to_node[mon] = node
                template.nodes.append(node)
            else:
                # 节点已存在（作为挂载点出现过）：设置父关系
                existing = name_to_node[mon]
                if not existing.parent_key:
                    existing.parent_key = cur_gw
                elif existing.parent_key != cur_gw:
                    # 多父冲突检测
                    template.errors.append(
                        f"挂载关系监测点名多父冲突: {mon} "
                        f"(已有父级 {existing.parent_key}, 当前 {cur_gw})"
                    )


def _parse_detail(
    rows: list[dict],
    sheet_name: str,
    key_column: str,
    header_map: dict[str, str],
    template: ArchiveTemplate,
) -> dict[str, dict]:
    """解析类型明细 sheet 为 条码 -> propertyCode 字段字典。

    Args:
        rows: 明细行字典列表。
        sheet_name: sheet 名称，用于错误定位。
        key_column: 主键列名（v14 为"设备名称"，名称驱动）。
        header_map: 中文列名 -> propertyCode 映射。
        template: 待填充的模板对象。

    Returns:
        名称到明细字段字典（键为 propertyCode）的映射。
    """
    details: dict[str, dict] = {}
    for row in rows:
        name = _cell_str(row.get(key_column))
        if not name:
            template.errors.append(f"{sheet_name} 存在缺少设备名称的行")
            continue
        if name in details:
            template.errors.append(f"{sheet_name} 设备名称重复: {name}")
            continue
        detail: dict[str, str] = {}
        for cn, prop in header_map.items():
            val = _cell_str(row.get(cn))
            # 类型保真：0/"0"/"false" 不算空
            if val or val == "0" or val == "false":
                detail[prop] = val
        details[name] = detail
    return details


def _parse_brand_model_mapping(
    ws,
    template: ArchiveTemplate,
) -> None:
    """解析「映射」sheet 中品牌/型号码值 → task_config 的映射。

    品牌行：``[品牌, 名称, extInfos.brand, code]`` → brand_name_to_code
    型号行：``[型号, "品牌 / 型号", extInfos.decimalNum, modelCode]`` →
      model_code_by_brand[品牌][型号] = modelCode

    映射随模板生成已是最新，不需运行时拉平台字典。解析失败不回退、不阻建档。

    Args:
        ws: 「映射」openpyxl 工作表。
        template: 待填充的模板对象（写 task_config 映射字段）。
    """
    brand_map: dict[str, str] = {}
    model_map: dict[str, dict[str, str]] = {}
    user_big_no_map: dict[str, str] = {}
    for row in _rows_as_dicts(ws, _header_index(ws)):
        kind = _cell_str(row.get("字段（下拉列）") or row.get("字段"))
        option = _cell_str(row.get("下拉选项（工程人员所见）") or row.get("名称"))
        raw_code = row.get("实际写入值（码值）")
        code = _cell_str(raw_code if raw_code is not None else row.get("码值"))
        if not option or not code:
            continue
        if kind == "品牌":
            if option in brand_map and brand_map[option] != code:
                template.errors.append(f"品牌映射冲突: {option}")
            brand_map[option] = code
        elif kind == "型号" and "/" in option:
            # 型号行选项形如 "品牌 / 型号"
            brand, _, model = option.partition("/")
            brand = brand.strip()
            model = model.strip()
            if brand and model:
                values = model_map.setdefault(brand, {})
                if model in values and values[model] != code:
                    template.errors.append(f"型号映射冲突: {brand} / {model}")
                values[model] = code
        elif kind == "用户大分类号":
            if option in user_big_no_map and user_big_no_map[option] != code:
                template.errors.append(f"用户大分类号映射冲突: {option}")
            user_big_no_map[option] = code
    template.task_config.brand_name_to_code = brand_map
    template.task_config.model_code_by_brand = model_map
    template.task_config.user_big_no_name_to_code = user_big_no_map


def read_archive_template(path: str | Path) -> ArchiveTemplate:
    """读取并解析 v15-engineer 自动建档 Excel 任务模板。

    Args:
        path: .xlsx 工作簿路径。

    Returns:
        ArchiveTemplate，含任务配置、节点、明细、元数据与错误/提示。

    Raises:
        TemplateReadError: 文件缺失或无法作为 Excel 打开。
    """
    file_path = Path(path)
    if not file_path.exists():
        raise TemplateReadError(f"模板文件不存在: {file_path}")
    try:
        wb = load_workbook(file_path, read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - 归一化 openpyxl 各类打开异常
        raise TemplateReadError(f"无法打开 Excel 模板: {exc}") from exc

    template = ArchiveTemplate()
    sheet_names = set(wb.sheetnames)

    # 必填 sheet 校验
    for required_sheet in _REQUIRED_SHEETS:
        if required_sheet not in sheet_names:
            template.errors.append(f"缺少必填 sheet: {required_sheet}")

    # 元数据与版本校验（系统连接 sheet）
    _check_version_and_metadata(wb, template)

    # 表头校验（重复、缺失、未知列）
    for sheet_name, cols in REQUIRED_COLUMNS.items():
        if sheet_name not in sheet_names:
            continue
        _validate_sheet_headers(wb, template, sheet_name, cols)

    # 工程公式校验（数据区域不允许公式）
    # 需要重新打开工作簿（不带 data_only=True）来检查公式
    max_rows = MAX_DATA_ROWS
    try:
        wb_formula = load_workbook(file_path, read_only=True, data_only=False)
        gw_cols = {"设备条码", "设备名称", "代理通信方式", "IP地址", "端口号",
                   "账号", "密码"}
        _validate_no_formulas_in_data(
            wb_formula, template, SHEET_GW_8163, 2, max_rows + 1, gw_cols,
        )
        meter_cols = {"设备条码", "设备名称", "分路号", "测量点号"}
        for _spec in monitor_sheet_specs():
            _validate_no_formulas_in_data(
                wb_formula, template, _spec.sheet_name, 2, max_rows + 1,
                meter_cols,
            )
        wb_formula.close()
    except Exception:  # noqa: BLE001 - 公式检查失败不影响主流程
        pass

    # 超出声明范围校验
    _checked_sheets = (SHEET_GW_8163,) + tuple(
        s.sheet_name for s in monitor_sheet_specs()
    )
    for sheet_name in _checked_sheets:
        if sheet_name in sheet_names:
            _validate_beyond_declared_range(wb, template, sheet_name, max_rows)

    # 各表必填列校验（存在的 sheet 才校验列）
    for sheet_name, cols in REQUIRED_COLUMNS.items():
        if sheet_name not in sheet_names:
            continue
        headers = _header_index(wb[sheet_name])
        for col in cols:
            if col not in headers:
                template.errors.append(f"{sheet_name} 缺少必填列: {col}")

    # 任务配置（系统连接 sheet，跳过元数据键）
    if SHEET_SYSTEM_CONNECTION in sheet_names:
        ws = wb[SHEET_SYSTEM_CONNECTION]
        _parse_task_config(_rows_as_dicts(ws, _header_index(ws)), template)

    # 品牌/型号码值映射（映射 sheet 已随模板生成最新）
    if SHEET_MAPPING in sheet_names:
        _parse_brand_model_mapping(wb[SHEET_MAPPING], template)

    # 挂载关系
    if SHEET_TOPO in sheet_names:
        ws = wb[SHEET_TOPO]
        _parse_topology(_rows_as_dicts(ws, _header_index(ws)), template)

    # 网关明细（按条码关联）
    if SHEET_GW_8163 in sheet_names:
        ws = wb[SHEET_GW_8163]
        template.gateway_details = _parse_detail(
            _rows_as_dicts(ws, _header_index(ws)),
            SHEET_GW_8163, GW_KEY_COLUMN, GW_HEADER_MAP, template,
        )

    # 监测点明细：每种监测点类型各自一张表，名称为键全局唯一、跨表合并到
    # 单一 meter_details；名字所在表决定该监测点的 device_type。
    meter_type_by_name: dict[str, str] = {}
    meter_sheet_by_name: dict[str, str] = {}
    for spec in monitor_sheet_specs():
        if spec.sheet_name not in sheet_names:
            continue  # 允许缺表（上传文档可只含部分监测点类型表）
        ws = wb[spec.sheet_name]
        details = _parse_detail(
            _rows_as_dicts(ws, _header_index(ws)),
            spec.sheet_name, METER_KEY_COLUMN, METER_HEADER_MAP, template,
        )
        for name, detail in details.items():
            prev_sheet = meter_sheet_by_name.get(name)
            if prev_sheet is not None:
                template.errors.append(
                    f"监测点 {name} 在多张监测点表出现"
                    f"（{prev_sheet} 与 {spec.sheet_name}），类型冲突"
                )
                continue
            template.meter_details[name] = detail
            meter_type_by_name[name] = spec.device_type
            meter_sheet_by_name[name] = spec.sheet_name

    wb.close()

    # 以名称为键：把明细回填到拓扑节点，并按所在 监测点·X 表赋予类型。
    # 名称命中网关明细 → 网关（含子网关）；命中任一监测点表 → 取该表类型。
    node_map = template.node_map()
    for node in template.nodes:
        key = node.node_key
        if key in template.gateway_details:
            node.device_type = _GW_DEVICE_TYPE
            detail = template.gateway_details.get(key, {})
            node.identifier = detail.get("deviceBarcode", "")
            node.detail = detail
        elif key in template.meter_details:
            node.device_type = meter_type_by_name.get(key, "")
            detail = template.meter_details.get(key, {})
            node.identifier = detail.get("deviceBarcode", "")
            node.road_no = detail.get("roadNo", "")
            node.detail = detail
        elif node.parent_key and not node.device_type:
            # 挂载关系里的监测点（无网关身份）却未在任何 监测点·X 表出现
            # → 无法定类型，报错
            template.errors.append(
                f"监测点 {key} 未在任何监测点明细表出现，无法确定监测点类型"
            )

    # 明细名称必须能在挂载关系中（作为挂载点或监测点）找到
    name_keys = set(node_map)
    for name in template.gateway_details:
        if name_keys and name not in name_keys:
            template.errors.append(
                f"{SHEET_GW_8163} 设备名称 {name} 未在挂载关系中定义"
            )
    for name in template.meter_details:
        if name_keys and name not in name_keys:
            sheet = meter_sheet_by_name.get(name, "监测点明细")
            template.errors.append(
                f"{sheet} 设备名称 {name} 未在挂载关系中定义"
            )
    return template
