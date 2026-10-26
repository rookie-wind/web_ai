"""版本化字段契约（单一事实源）。

以 ``TypeSheetSpec`` 声明每种设备类型的 sheet 结构、工程列契约、派生字段与
接口能力。generator、reader、profile、payload 构造器与回读比较器均消费本模块，
不再各自维护名称码值表，消除各层独立补默认与映射漂移（design §2）。

码值出处分级（``EvidenceStatus``）：

- ``VERIFIED``：后端实测确认（如 9600→6、cT/pT 透传）。
- ``PROTOCOL``：协议文档为据但端到端未实测（如串口其余档位、抄表间隔位域）。
- ``UNVERIFIED``：落点或码值未确认（如 IP/port 落点、校验位「无」0/1 歧义、
  监测点代理通信方式落点）。此类字段不得进入可执行模板与下发，须现场 G1 核验。

**禁止臆造**：任何未在协议或实测中出现的落点一律标 UNVERIFIED。
"""

from __future__ import annotations

__all__ = [
    "FIELD_CONTRACT_VERSION",
    "TEMPLATE_VERSION",
    "GATEWAY_8163_SHEET_SPEC",
    "XLBA_METER_SHEET_SPEC",
    "LIGHTING_SHEET_SPEC",
    "PDB_SHEET_SPEC",
    "SHEET_SPECS",
    "COMM_PORT_CODE_MAP",
    "IP_PORTS",
    "get_sheet_spec",
    "get_sheet_spec_by_name",
    "monitor_sheet_specs",
]

from .models import (
    EvidenceStatus,
    FieldSource,
    FieldSpec,
    InputType,
    TypeSheetSpec,
)
from .profiles.base import (
    GATEWAY_8163_TYPE_ID,
    METER_DEPLOY_ITEM_ID,
    METER_LIGHTING_TYPE_ID,
    METER_PDB_TYPE_ID,
    METER_XLBA_TYPE_ID,
)

#: 字段契约版本（快照与模板元数据引用）
FIELD_CONTRACT_VERSION = "fc-v1"
#: 模板结构版本（v15：每种监测点类型各自一张 sheet，去掉挂载关系「监测点类型」列）
TEMPLATE_VERSION = "v15-engineer"

# 监测点运维调试召测固定旧协议号（来源 用户指定 + 记忆固化，G5 门槛核验）
_MONITOR_DEBUG_PROTOCOL = "31800006"

# ── 四项串口枚举码值（协议备注2；9600/1位/无/8位→6/0/0/3 监测点3 实测）──
_BAUD_RATE_CODE_MAP = {
    "38400": "0",
    "115200": "1",
    "1200": "2",
    "2400": "3",
    "4800": "4",
    "7200": "5",
    "9600": "6",
    "19200": "7",
}
_STOP_DIGIT_CODE_MAP = {"1位停止位": "0", "2位停止位": "1"}
# 校验位「无」在协议中同时出现 0 与 1（歧义），端到端码值属现场 G1 待核验
_CHECK_DIGIT_CODE_MAP = {"无校验": "0", "偶校验": "2", "奇校验": "3"}
_DATA_DIGIT_CODE_MAP = {"5位": "0", "6位": "1", "7位": "2", "8位": "3"}

# ── 抄表间隔位域（协议备注6「用户小类号配置对照表」；非 0 基顺序）──
_INTERVAL_CODE_MAP = {
    "15秒": "9",
    "1分钟": "1",
    "5分钟": "2",
    "15分钟": "4",
    "60分钟": "8",
    "24小时": "10",
    "不抄表": "0",
}

# ── 协议代号（用户指定，固定 2 项）──
_PROTOCOL_NUMBER_CODE_MAP = {"新联MQTT协议": "200", "上海MQTT协议": "202"}

# ── 代理通信方式（边缘 getDictItemList CommunicationMode；175 实测 18 项）──
_COMM_MODE_CODE_MAP = {
    "RS485端口1": "3",
    "RS485端口2": "8",
    "RS485端口3": "9",
    "RS485端口4": "10",
    "以太网": "2",
    "4G/5G物联网": "1",
    "Lora": "4",
    "小无线": "5",
    "A芯通道": "6",
    "前置机": "7",
    "B芯通道": "11",
    "虚拟网关": "12",
    "MQTT": "13",
    "交流采样": "14",
    "B芯操作系统": "15",
    "隔离采集1": "CAIJI1",
    "隔离采集2": "CAIJI2",
    "HRF小无线": "16",
}

# 23 前端静态源码核实：chunk-2d22d9d8.f3b401d2.js，f7f7.b。
# 与代理通信方式字典不同；顺序、名称和码值均对应 XLBA 下拉。
COMM_PORT_CODE_MAP: dict[str, str] = {
    "RS485-1": "1",
    "RS485-2": "2",
    "RS485-3": "3",
    "RS485-4": "4",
    "AC485-1": "11",
    "AC485-2": "12",
    "ETH-1": "40",
    "ETH-2": "41",
    "LoRa-1": "31",
    "LoRa-2": "32",
    "LoRa-3": "33",
    "LoRa-4": "34",
    "LoRa-5": "35",
    "LoRa-6": "36",
    "4438-1": "28",
    "4438-2": "29",
    "MQTT": "50",
    "控制模块": "43",
    "脉冲/告警模块": "44",
    "监听RS485-1": "51",
    "监听RS485-2": "52",
}

# IP 型端口（ETH-1/ETH-2/MQTT）：proxyCommPort 属于此集合时，「IP地址/IP端口号」
# 列经端口驱动组装写入 extInfos.authParam（5 段逗号串）；其余端口下 authParam
# 承载电表密码且禁止填写 IP 列。40 已经 10.0.17.23 实测，41/50 按同语义纳入待现场复核。
IP_PORTS: frozenset[str] = frozenset({"40", "41", "50"})

# 监测点类型不再由「挂载关系」的列承载：每种监测点类型各自一张 sheet，
# 类型即由名字所在的 监测点·X 表决定。表↔类型的映射以 SHEET_SPECS 中
# 非网关 spec 的 (sheet_name, device_type, device_type_id) 为单一事实源，
# generator/reader 通过 monitor_sheet_specs()/get_sheet_spec_by_name() 取用。

# ── 下发 itemBody 固定字段（20200002 抄表参数；Path B 175 实测）──
_DEPLOY_ITEM_FIELDS = {
    "roadNo": "分路号（int）",
    "commAddr": "通讯地址（12 位字符串）",
    "protocolCode": "协议代号（int，如 200）",
    "measurNo": "测量点号（int）",
    "comPort": "通信端口号（int，如 1=RS485-1）",
    "baudRate": "波特率（string，实测下发含该字段）",
    "feeNum": "费率数（int）",
    "integerNum": "整数位（int）",
    "decimalNum": "小数位（int）",
    "authParam": "密码参数（下发侧恒 12 位十六进制：有 IP+端口则编码，否则占位全 E）",
    "collCommAddr": "采集通讯地址（12 位字符串）",
    "userBigNo": "用户大分类号（int）",
    "userSmallNo": "用户小分类号/抄表间隔（int）",
    "aCommAddr": "备用地址（字符串）",
}


def _gateway_fields() -> list[FieldSpec]:
    """构建 8163 网关工程列契约（A–C 三列）。

    Returns:
        网关列 FieldSpec 列表。
    """
    return [
        FieldSpec(
            field_key="deviceName",
            header="设备名称",
            input_type=InputType.TEXT,
            source=FieldSource.ENGINEER_INPUT,
            required=True,
            archive_base_key="deviceName",
            readback_path="base.deviceName",
            evidence=EvidenceStatus.VERIFIED,
            note="基本档案，原值",
        ),
        FieldSpec(
            field_key="identifier",
            header="设备条码",
            input_type=InputType.TEXT,
            source=FieldSource.ENGINEER_INPUT,
            required=True,
            archive_base_key="identifier",
            readback_path="base.identifier",
            evidence=EvidenceStatus.VERIFIED,
            note="网关条码经 convert_comm_address 转 deviceAddress（派生）",
        ),
        FieldSpec(
            field_key="proxyCommType",
            header="代理通信方式",
            input_type=InputType.ENUM,
            source=FieldSource.ENGINEER_INPUT,
            dict_scope="comm_mode",
            archive_base_key="proxyCommType",
            readback_path="base.proxyCommType",
            evidence=EvidenceStatus.VERIFIED,
            note="平台 getDictItemList CommunicationMode 字典码",
        ),
    ]


def _gateway_derived() -> list[FieldSpec]:
    """构建 8163 网关派生字段契约。

    Returns:
        网关派生 FieldSpec 列表。
    """
    return [
        FieldSpec(
            field_key="deviceAddress",
            input_type=InputType.TEXT,
            source=FieldSource.DERIVED,
            derived_deps=("identifier",),
            archive_base_key="deviceAddress",
            readback_path="base.deviceAddress",
            evidence=EvidenceStatus.VERIFIED,
            note="12 位=modbus(3)+通道(3)+内机(3)+序号(3)，由条码转换",
        ),
    ]


GATEWAY_8163_SHEET_SPEC = TypeSheetSpec(
    sheet_name="网关·8163",
    device_type="8163网关",
    device_type_id=GATEWAY_8163_TYPE_ID,
    is_gateway=True,
    interface_capabilities={
        "deviceTypeId": GATEWAY_8163_TYPE_ID,
        "clock_request_field": "devId",
    },
    fields=_gateway_fields(),
    derived_fields=_gateway_derived(),
)


def _meter_fields() -> list[FieldSpec]:
    """构建 XLBA 监测点工程列契约（A–T 二十列）。

    Returns:
        监测点列 FieldSpec 列表。
    """
    return [
        FieldSpec(
            field_key="deviceName",
            header="设备名称",
            input_type=InputType.TEXT,
            required=True,
            archive_base_key="deviceName",
            readback_path="base.deviceName",
            evidence=EvidenceStatus.VERIFIED,
        ),
        FieldSpec(
            field_key="identifier",
            header="设备条码",
            input_type=InputType.TEXT,
            required=True,
            archive_base_key="identifier",
            readback_path="base.identifier",
            evidence=EvidenceStatus.VERIFIED,
            note="XLBA identifier 通常直接等于 deviceAddress（原地址）",
        ),
        FieldSpec(
            field_key="measurNo",
            header="测量点号",
            input_type=InputType.INTEGER,
            archive_base_key="measuredPointNum",
            deploy_key="measurNo",
            readback_path="base.measuredPointNum",
            evidence=EvidenceStatus.VERIFIED,
            note="档案 measuredPointNum / 下发 measurNo；网关内唯一，禁止自增",
        ),
        FieldSpec(
            field_key="roadNo",
            header="分路号",
            input_type=InputType.INTEGER,
            required=True,
            archive_base_key="agentNum",
            deploy_key="roadNo",
            readback_path="base.agentNum",
            evidence=EvidenceStatus.VERIFIED,
            note="档案 agentNum / 下发 roadNo；网关内唯一，禁止自增",
        ),
        FieldSpec(
            field_key="protocolNumber",
            header="协议代号",
            input_type=InputType.ENUM,
            dict_scope="protocol_number",
            code_map=dict(_PROTOCOL_NUMBER_CODE_MAP),
            archive_base_key="protocolNumber",
            readback_path="base.protocolNumber",
            evidence=EvidenceStatus.VERIFIED,
            note="用户填写不得被固定 200 覆盖（design §6）",
        ),
        FieldSpec(
            field_key="userBigNo",
            header="用户大分类号",
            input_type=InputType.ENUM,
            dict_scope="user_big_no",
            archive_ext_key="userBigNo",
            readback_path="extInfos.userBigNo",
            evidence=EvidenceStatus.VERIFIED,
            note="云端 get_device_type_list deviceTypeCode；dsTypeId 依赖此值",
        ),
        FieldSpec(
            field_key="brand",
            header="品牌",
            input_type=InputType.ENUM,
            dict_scope="brand",
            archive_ext_key="brand",
            readback_path="extInfos.brand",
            evidence=EvidenceStatus.VERIFIED,
            note="双写 extInfos.brandName（原名称）",
        ),
        FieldSpec(
            field_key="decimalNum",
            header="型号",
            input_type=InputType.ENUM,
            dict_scope="model",
            archive_ext_key="decimalNum",
            readback_path="extInfos.decimalNum",
            evidence=EvidenceStatus.VERIFIED,
            note="品牌级联；双写 extInfos.decimalNumName（原名称）",
        ),
        FieldSpec(
            field_key="userSmallNo",
            header="抄表间隔",
            input_type=InputType.ENUM,
            dict_scope="meter_interval",
            code_map=dict(_INTERVAL_CODE_MAP),
            archive_ext_key="userSmallNo",
            readback_path="extInfos.userSmallNo",
            evidence=EvidenceStatus.PROTOCOL,
            note="userSmallNo 位域（备注6）；1分钟=1 实测，其余端到端属 G2；"
                 "同时双写 extInfos.collCycle（其余项是否同码待现场核验）",
        ),
        FieldSpec(
            field_key="proxyCommType",
            header="代理通信方式",
            input_type=InputType.ENUM,
            dict_scope="comm_mode",
            evidence=EvidenceStatus.UNVERIFIED,
            note="监测点自身代理通信方式落点未核实（网关用 proxyCommType，"
                 "监测点是否需独立落点待 G1）；禁止臆造",
        ),
        FieldSpec(
            field_key="proxyCommPort",
            header="通信端口号",
            input_type=InputType.ENUM,
            dict_scope="comm_port",
            code_map=dict(COMM_PORT_CODE_MAP),
            archive_base_key="proxyCommPort",
            readback_path="base.proxyCommPort",
            evidence=EvidenceStatus.VERIFIED,
            note="23前端21项下拉源码已核实，非全部端到端实测；"
                 "兼容原数字输入，不补默认；43/44专用模式仍阻断",
        ),
        FieldSpec(
            field_key="baudRate",
            header="波特率",
            input_type=InputType.ENUM,
            dict_scope="baud_rate",
            code_map=dict(_BAUD_RATE_CODE_MAP),
            evidence=EvidenceStatus.PROTOCOL,
            note="备注2 枚举；9600→6 实测，其余档端到端属 G2；不写入档案顶层"
                 "（不与平台『通信速率』挂钩），仅参与 feeNum 位域计算",
        ),
        FieldSpec(
            field_key="stopDigit",
            header="停止位",
            input_type=InputType.ENUM,
            dict_scope="stop_digit",
            code_map=dict(_STOP_DIGIT_CODE_MAP),
            archive_base_key="stopDigit",
            readback_path="base.stopDigit",
            evidence=EvidenceStatus.PROTOCOL,
            note="1位→0 实测，2位→1 属 G2",
        ),
        FieldSpec(
            field_key="checkDigit",
            header="校验位",
            input_type=InputType.ENUM,
            dict_scope="check_digit",
            code_map=dict(_CHECK_DIGIT_CODE_MAP),
            archive_base_key="checkDigit",
            readback_path="base.checkDigit",
            evidence=EvidenceStatus.UNVERIFIED,
            note="「无校验」协议同时出现 0 与 1（歧义未决），确切码值须现场 G1 "
                 "只读召测确认；未确认前不下发，读回时 1 作为等价码保留出处",
        ),
        FieldSpec(
            field_key="dataDigit",
            header="数据位",
            input_type=InputType.ENUM,
            dict_scope="data_digit",
            code_map=dict(_DATA_DIGIT_CODE_MAP),
            archive_base_key="dataDigit",
            readback_path="base.dataDigit",
            evidence=EvidenceStatus.PROTOCOL,
            note="8位→3 实测，其余档属 G2",
        ),
        FieldSpec(
            field_key="ip",
            header="IP地址",
            input_type=InputType.TEXT,
            evidence=EvidenceStatus.VERIFIED,
            note="经 authParam 承载（端口驱动）：proxyCommPort ∈ IP_PORTS 时与 IP端口号"
                 "拼为 5 段逗号串写入 extInfos.authParam；串口端口下禁止填写。"
                 "10.0.17.23 手工建档抓包 + 脚本建档实测坐实",
        ),
        FieldSpec(
            field_key="port",
            header="IP端口号",
            input_type=InputType.TEXT,
            evidence=EvidenceStatus.VERIFIED,
            note="同 IP地址：经 authParam 末段承载，仅在 IP 型端口合法",
        ),
        FieldSpec(
            field_key="collectorAddress",
            header="采集器地址",
            input_type=InputType.TEXT,
            archive_base_key="collectorAddress",
            readback_path="base.collectorAddress",
            evidence=EvidenceStatus.VERIFIED,
            note="抄表参数映射实测，原值",
        ),
        FieldSpec(
            field_key="cT",
            header="电流变比",
            input_type=InputType.FLOAT,
            archive_ext_key="cT",
            readback_path="extInfos.cT",
            evidence=EvidenceStatus.VERIFIED,
            note="变比数值直接透传（监测点3 实测=100），非枚举；草案映射表 TA "
                 "行为陈旧 TBD，以本契约为准",
        ),
        FieldSpec(
            field_key="pT",
            header="电压变比",
            input_type=InputType.FLOAT,
            archive_ext_key="pT",
            readback_path="extInfos.pT",
            evidence=EvidenceStatus.VERIFIED,
            note="变比数值直接透传，非枚举",
        ),
    ]


def _meter_derived() -> list[FieldSpec]:
    """构建 XLBA 监测点派生字段契约。

    Returns:
        监测点派生 FieldSpec 列表。
    """
    return [
        FieldSpec(
            field_key="authParam",
            input_type=InputType.TEXT,
            source=FieldSource.DERIVED,
            derived_deps=("ip", "port", "proxyCommPort"),
            archive_ext_key="authParam",
            deploy_key="authParam",
            readback_path="extInfos.authParam",
            evidence=EvidenceStatus.VERIFIED,
            note="多态派生：档案侧 IP 型端口(40/41/50) 写 ip1,ip2,ip3,ip4,port 5 段逗号串，"
                 "串口端口透传电表密码；下发侧恒存且恒为 12 位十六进制——有 IP+端口"
                 "则 hex(IP 4B)+hex(port 2B)，无来源（含串口密码、端口未填）则占位"
                 " EEEEEEEEEEEE。字典名『通信密码（电表）』为历史遗留。"
                 "证据：10.0.17.23 建档抓包 + 2026-10-21 下发抓包",
        ),
        FieldSpec(
            field_key="dsTypeId",
            input_type=InputType.TEXT,
            source=FieldSource.DERIVED,
            derived_deps=("userBigNo",),
            archive_ext_key="dsTypeId",
            readback_path="extInfos.dsTypeId",
            evidence=EvidenceStatus.UNVERIFIED,
            note="userBigNo 为空时 dsTypeId=deviceTypeId 本身（100023/100024 实测）；"
                 "填了才派生 =deviceTypeId+userBigNo(补零至2位)。userBigNo 公式仅对 "
                 "userBigNo=11（电表类）实测确认；其他 userBigNo（如 9=环境传感器）"
                 "后端有独立计算规则，回读值可能与公式不一致，故不纳入回读验证",
        ),
        FieldSpec(
            field_key="deviceAddress",
            input_type=InputType.TEXT,
            source=FieldSource.DERIVED,
            derived_deps=("identifier",),
            archive_base_key="deviceAddress",
            readback_path="base.deviceAddress",
            evidence=EvidenceStatus.VERIFIED,
            note="XLBA 原地址：identifier 通常直接等于 deviceAddress",
        ),
    ]


XLBA_METER_SHEET_SPEC = TypeSheetSpec(
    sheet_name="监测点·XLBA",
    device_type="XLBA电表",
    device_type_id=METER_XLBA_TYPE_ID,
    is_gateway=False,
    interface_capabilities={
        "deviceTypeId": METER_XLBA_TYPE_ID,
        "deploy_item_id": METER_DEPLOY_ITEM_ID,
        "monitor_debug_protocol": _MONITOR_DEBUG_PROTOCOL,
    },
    fields=_meter_fields(),
    derived_fields=_meter_derived(),
)

# 照明 / 配电房监测点：字段契约与 XLBA 完全一致（含 authParam 端口驱动组装），
# 差异仅 deviceTypeId（10.0.17.23 实测建档成功）；下发/召测为通用能力，
# 执行时实时读后端当前参数，不区分类型。
LIGHTING_SHEET_SPEC = TypeSheetSpec(
    sheet_name="监测点·照明",
    device_type="照明",
    device_type_id=METER_LIGHTING_TYPE_ID,
    is_gateway=False,
    interface_capabilities={
        "deviceTypeId": METER_LIGHTING_TYPE_ID,
    },
    fields=_meter_fields(),
    derived_fields=_meter_derived(),
)

PDB_SHEET_SPEC = TypeSheetSpec(
    sheet_name="监测点·配电房",
    device_type="配电房",
    device_type_id=METER_PDB_TYPE_ID,
    is_gateway=False,
    interface_capabilities={
        "deviceTypeId": METER_PDB_TYPE_ID,
    },
    fields=_meter_fields(),
    derived_fields=_meter_derived(),
)

#: 全部已声明类型的 sheet 契约
SHEET_SPECS: list[TypeSheetSpec] = [
    GATEWAY_8163_SHEET_SPEC,
    XLBA_METER_SHEET_SPEC,
    LIGHTING_SHEET_SPEC,
    PDB_SHEET_SPEC,
]


def get_sheet_spec(
    device_type: str = "", device_type_id: str = ""
) -> TypeSheetSpec | None:
    """按设备类型名或 deviceTypeId 查 sheet 契约。

    Args:
        device_type: 中文设备类型名。
        device_type_id: 后端 deviceTypeId。

    Returns:
        命中的 TypeSheetSpec；未命中返回 None。名称优先于 ID。
    """
    for spec in SHEET_SPECS:
        if device_type and spec.device_type == device_type:
            return spec
    for spec in SHEET_SPECS:
        if device_type_id and spec.device_type_id == str(device_type_id):
            return spec
    return None


def get_sheet_spec_by_name(sheet_name: str) -> TypeSheetSpec | None:
    """按工作表名查 sheet 契约（表名唯一，用于 reader 由表定类型）。

    Args:
        sheet_name: 工作表名（如 ``监测点·照明``）。

    Returns:
        命中的 TypeSheetSpec；未命中返回 None。
    """
    for spec in SHEET_SPECS:
        if spec.sheet_name == sheet_name:
            return spec
    return None


def monitor_sheet_specs() -> list[TypeSheetSpec]:
    """返回全部监测点（非网关）类型 sheet 契约，顺序即建表顺序。

    Returns:
        非网关 TypeSheetSpec 列表（XLBA/照明/配电房，后续可扩展新增）。
    """
    return [spec for spec in SHEET_SPECS if not spec.is_gateway]
