"""task 2.1 验收：版本化共享字段契约的单一事实源测试。

证明生成、解析、payload 构造与回读四方消费同一 ``FieldSpec`` 契约，
不各自维护名称码值表；并验证证据状态门槛（UNVERIFIED 字段不得进入可执行模板）。

本测试中的 ``resolve_field`` 是「契约消费」的最小演示（生产版落点在 group 5），
仅用于断言四种表示均由同一 FieldSpec 派生。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_MCP_DIR = Path(__file__).parent.parent
if str(_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_MCP_DIR))

from archiving.field_contract import (  # noqa: E402
    FIELD_CONTRACT_VERSION,
    IP_PORTS,
    METER_LIGHTING_TYPE_ID,
    METER_PDB_TYPE_ID,
    XLBA_METER_SHEET_SPEC,
    get_sheet_spec,
)
from archiving.models import (  # noqa: E402
    CellInput,
    EvidenceStatus,
    FieldSource,
    FieldSpec,
    InputType,
    ResolvedField,
    TemplateSnapshot,
    TypeSheetSpec,
)
from archiving.profiles.registry import default_registry  # noqa: E402

# v14 监测点·XLBA 二十列（表头顺序即列顺序）
_EXPECTED_HEADERS = [
    "设备名称", "设备条码", "测量点号", "分路号",
    "协议代号", "用户大分类号", "品牌", "型号", "抄表间隔",
    "代理通信方式", "通信端口号", "波特率", "停止位", "校验位",
    "数据位", "IP地址", "IP端口号", "采集器地址", "电流变比", "电压变比",
]


def resolve_field(spec: FieldSpec, raw) -> ResolvedField:
    """按单一 FieldSpec 契约派生解析／档案／下发／回读四种表示。

    Args:
        spec: 字段契约。
        raw: 单元格原始值。

    Returns:
        ResolvedField，四种落点表示均由同一 spec 派生。
    """
    filled = raw is not None and str(raw).strip() != ""
    rf = ResolvedField(field_key=spec.field_key, source=spec.source, value=None)
    if not filled:
        return rf
    if spec.input_type is InputType.ENUM:
        # 未知名称不透传（阻断），命中才取码值
        value = spec.code_map.get(str(raw))
    else:
        value = raw
    rf.value = value
    if spec.archive_base_key:
        rf.archive_base[spec.archive_base_key] = value
    if spec.archive_ext_key:
        rf.archive_ext[spec.archive_ext_key] = value
    if spec.deploy_key:
        rf.deploy[spec.deploy_key] = value
    if spec.readback_path:
        rf.readback[spec.readback_path] = value
    return rf


class TestContractLookup:
    """契约可按名称与 deviceTypeId 双通道检索。"""

    def test_contract_versioned(self):
        assert FIELD_CONTRACT_VERSION

    def test_lookup_by_name_and_id_agree(self):
        by_name = get_sheet_spec(device_type="XLBA电表")
        by_id = get_sheet_spec(device_type_id="100019")
        assert by_name is by_id is XLBA_METER_SHEET_SPEC

    def test_registry_exposes_same_contract(self):
        spec = default_registry.sheet_spec(device_type="XLBA电表")
        assert spec is XLBA_METER_SHEET_SPEC

    def test_unknown_type_returns_none(self):
        assert get_sheet_spec(device_type="不存在类型") is None


class TestGenerationConsumer:
    """生成方消费契约：表头、下拉选项来自同一 FieldSpec。"""

    def test_headers_match_v14_columns(self):
        assert XLBA_METER_SHEET_SPEC.headers() == _EXPECTED_HEADERS

    def test_baud_rate_dropdown_full_enum(self):
        spec = XLBA_METER_SHEET_SPEC.field("baudRate")
        assert spec.dropdown_options() == [
            "38400", "115200", "1200", "2400", "4800", "7200", "9600", "19200",
        ]

    def test_interval_dropdown_is_bitfield_names(self):
        spec = XLBA_METER_SHEET_SPEC.field("userSmallNo")
        assert set(spec.dropdown_options()) == {
            "15秒", "1分钟", "5分钟", "15分钟", "60分钟", "24小时", "不抄表",
        }
        # 位域码值（非 0 基顺序）：15秒=9、24小时=10
        assert spec.code_map["15秒"] == "9"
        assert spec.code_map["24小时"] == "10"

    def test_stop_check_data_dropdowns(self):
        assert XLBA_METER_SHEET_SPEC.field("stopDigit").dropdown_options() == [
            "1位停止位", "2位停止位",
        ]
        assert XLBA_METER_SHEET_SPEC.field("dataDigit").dropdown_options() == [
            "5位", "6位", "7位", "8位",
        ]


class TestParsingConsumer:
    """解析方消费契约：字段键、输入类型、必填来自同一 FieldSpec。"""

    def test_field_keys_unique(self):
        keys = [f.field_key for f in XLBA_METER_SHEET_SPEC.fields]
        assert len(keys) == len(set(keys))

    def test_required_fields_flagged(self):
        required = {
            f.field_key for f in XLBA_METER_SHEET_SPEC.fields if f.required
        }
        assert {"deviceName", "identifier", "roadNo"} <= required

    def test_integer_fields_typed(self):
        assert XLBA_METER_SHEET_SPEC.field("roadNo").input_type is InputType.INTEGER
        assert XLBA_METER_SHEET_SPEC.field("measurNo").input_type is InputType.INTEGER


class TestPayloadAndReadbackConsumer:
    """payload 与回读消费同一 FieldSpec：档案／下发／回读表示一致派生。"""

    def test_baud_rate_no_archive_no_deploy(self):
        """波特率不写档案顶层、不进下发，仅参与 feeNum 位域计算。"""
        spec = XLBA_METER_SHEET_SPEC.field("baudRate")
        rf = resolve_field(spec, "9600")
        # 无 archive_base_key / deploy_key / readback_path
        assert rf.archive_base == {}
        assert rf.deploy == {}
        assert rf.readback == {}
        # 码值仍可解析（供 feeNum 计算使用）
        assert rf.value == "6"

    def test_road_no_archive_vs_deploy_keys_differ(self):
        spec = XLBA_METER_SHEET_SPEC.field("roadNo")
        rf = resolve_field(spec, 3)
        # 档案 agentNum / 下发 roadNo（design §6）
        assert rf.archive_base == {"agentNum": 3}
        assert rf.deploy == {"roadNo": 3}
        assert rf.readback == {"base.agentNum": 3}

    def test_measur_no_archive_vs_deploy_keys_differ(self):
        spec = XLBA_METER_SHEET_SPEC.field("measurNo")
        rf = resolve_field(spec, 5)
        assert rf.archive_base == {"measuredPointNum": 5}
        assert rf.deploy == {"measurNo": 5}

    def test_ct_lands_in_ext_infos(self):
        spec = XLBA_METER_SHEET_SPEC.field("cT")
        rf = resolve_field(spec, 100)
        assert rf.archive_ext == {"cT": 100}
        assert rf.readback == {"extInfos.cT": 100}

    def test_unknown_enum_not_passed_through(self):
        spec = XLBA_METER_SHEET_SPEC.field("baudRate")
        rf = resolve_field(spec, "4000")  # 非法档位
        assert rf.value is None
        assert rf.archive_base == {}

    def test_blank_yields_no_value(self):
        spec = XLBA_METER_SHEET_SPEC.field("cT")
        rf = resolve_field(spec, "  ")
        assert rf.value is None
        assert rf.archive_ext == {}

    def test_derived_dsTypeId_declared(self):
        spec = XLBA_METER_SHEET_SPEC.field("dsTypeId")
        assert spec is not None
        assert spec.derived_deps == ("userBigNo",)
        assert spec.archive_ext_key == "dsTypeId"


class TestEvidenceGate:
    """G1 证据门槛：UNVERIFIED 字段阻止可执行模板。"""

    def test_meter_not_fully_verified(self):
        assert XLBA_METER_SHEET_SPEC.is_fully_verified() is False

    def test_unverified_fields_enumerated(self):
        unverified = set(XLBA_METER_SHEET_SPEC.unverified_fields())
        # 校验位 0/1 歧义、监测点代理通信方式落点仍未核验
        assert {"checkDigit", "proxyCommType"} <= unverified
        # ip/port 经 10.0.17.23 实测坐实为 authParam 承载，已升 VERIFIED
        assert "ip" not in unverified
        assert "port" not in unverified

    def test_verified_serial_ports_not_blocked(self):
        unverified = set(XLBA_METER_SHEET_SPEC.unverified_fields())
        assert "baudRate" not in unverified
        assert "stopDigit" not in unverified
        assert "dataDigit" not in unverified

    def test_unverified_field_not_executable(self):
        # ip/port 升 VERIFIED 后可执行（经 authParam 端口驱动承载）
        assert XLBA_METER_SHEET_SPEC.field("ip").is_executable() is True
        assert XLBA_METER_SHEET_SPEC.field("port").is_executable() is True
        # proxyCommType 落点未核验，仍不可执行
        assert XLBA_METER_SHEET_SPEC.field("proxyCommType").is_executable() is False
        assert XLBA_METER_SHEET_SPEC.field("baudRate").is_executable() is True

    def test_auth_param_derived_declared(self):
        """authParam 派生列存在、依赖 ip/port/proxyCommPort、落点 extInfos.authParam。"""
        spec = XLBA_METER_SHEET_SPEC.field("authParam")
        assert spec is not None
        assert spec.source is FieldSource.DERIVED
        assert spec.derived_deps == ("ip", "port", "proxyCommPort")
        assert spec.archive_ext_key == "authParam"
        assert spec.evidence is EvidenceStatus.VERIFIED

    def test_ip_ports_constant_exposed(self):
        """IP 型端口集合供 profile 引用，端口驱动 authParam 组装。"""
        assert IP_PORTS == frozenset({"40", "41", "50"})

    def test_lighting_pdb_specs_registered(self):
        """照明/配电房新类型 spec 命中，类型 ID 一致，能力旗已删除。"""
        lighting = get_sheet_spec(device_type="照明")
        assert lighting.device_type_id == METER_LIGHTING_TYPE_ID
        assert not hasattr(lighting, "supports_deploy")
        assert not hasattr(lighting, "supports_poll")
        pdb = get_sheet_spec(device_type="配电房")
        assert pdb.device_type_id == METER_PDB_TYPE_ID
        assert not hasattr(pdb, "supports_deploy")
        # 复用同一字段列表：ip/port/authParam 均在
        assert lighting.field("ip").is_executable() is True
        assert lighting.field("authParam") is not None
        assert pdb.field("authParam") is not None

    def test_registry_surfaces_unverified(self):
        rows = {r["device_type"]: r for r in default_registry.supported_types()}
        meter = rows["XLBA电表"]
        assert "checkDigit" in meter["unverified_fields"]
        assert meter["interface_capabilities"]["monitor_debug_protocol"] == "31800006"
        assert meter["interface_capabilities"]["deploy_item_id"] == "20200002"


class TestGatewayContract:
    """8163 网关契约：三列、时钟召测接口事实记录保留。"""

    def test_gateway_headers(self):
        spec = get_sheet_spec(device_type="8163网关")
        assert spec.headers() == ["设备名称", "设备条码", "代理通信方式"]

    def test_gateway_capabilities(self):
        spec = get_sheet_spec(device_type="8163网关")
        assert spec.is_gateway is True
        assert not hasattr(spec, "supports_deploy")
        assert not hasattr(spec, "supports_poll")
        assert spec.interface_capabilities["clock_request_field"] == "devId"


class TestSnapshotRoundTrip:
    """快照序列化稳定性。"""

    def test_typesheetspec_roundtrip_drops_capability_flags(self):
        """TypeSheetSpec 序列化往返不含能力旗键；旧快照多余键被容忍。"""
        spec = get_sheet_spec(device_type="XLBA电表")
        payload = spec.to_dict()
        assert "supports_deploy" not in payload
        assert "supports_poll" not in payload
        restored = TypeSheetSpec.from_dict(payload)
        assert restored.to_dict() == payload
        # 旧快照 JSON 携带已删除的能力旗键 → from_dict 忽略，不报错
        legacy = dict(payload)
        legacy["supports_deploy"] = False
        legacy["supports_poll"] = True
        tolerated = TypeSheetSpec.from_dict(legacy)
        assert not hasattr(tolerated, "supports_deploy")
        assert not hasattr(tolerated, "supports_poll")
        assert tolerated.to_dict() == payload

    def test_snapshot_roundtrip(self):
        snap = TemplateSnapshot(
            version="v14-engineer",
            field_contract_version=FIELD_CONTRACT_VERSION,
            snapshot_id="abc123",
            source_time="2026-09-21T00:00:00",
            dictionaries={"baud_rate": [{"name": "9600", "code": "6"}]},
            mappings={"baudRate": {"9600": "6"}},
            content_digest="deadbeef",
        )
        restored = TemplateSnapshot.from_dict(snap.to_dict())
        assert restored == snap

    def test_cellinput_roundtrip(self):
        cell = CellInput(
            field_key="baudRate", raw="9600", filled=True,
            normalized="6", sheet="监测点·XLBA", row=2, column="J",
            mapping_source="field_contract",
        )
        assert CellInput.from_dict(cell.to_dict()) == cell


class TestProfileCodeMapping:
    """任务 5.1 验收：profile 使用 field_contract 码值映射。"""

    def test_xlba_baud_rate_mapping(self):
        """XLBA 波特率不写入档案顶层，仅参与 feeNum 位域计算。"""
        from archiving.profiles.meter_xlba import MeterXlbaProfile
        from archiving.models import TopologyNode

        profile = MeterXlbaProfile()
        node = TopologyNode(
            node_key="001234",
            device_name="测试电表",
            device_type="XLBA电表",
            identifier="001234",
            road_no="1",
        )
        detail = {"baudRate": "9600", "roadNo": "1"}
        result = profile.resolve(node, None, detail)
        # baudRate 不写入档案顶层（显式空值清除残留）
        assert not result.base_payload.get("baudRate")

    def test_xlba_protocol_number_mapping(self):
        """XLBA 协议代号 新联MQTT协议→200。"""
        from archiving.profiles.meter_xlba import MeterXlbaProfile
        from archiving.models import TopologyNode

        profile = MeterXlbaProfile()
        node = TopologyNode(
            node_key="001234",
            device_name="测试电表",
            device_type="XLBA电表",
            identifier="001234",
            road_no="1",
        )
        detail = {"protocolNumber": "新联MQTT协议", "roadNo": "1"}
        result = profile.resolve(node, None, detail)
        assert result.base_payload["protocolNumber"] == "200"

    def test_gateway_no_default_proxy(self):
        """网关未填 proxyCommType：不报错不阻断建档，仅告警并标记 link_blocked。"""
        from archiving.profiles.gateway_8163 import Gateway8163Profile
        from archiving.models import TopologyNode, TaskConfig

        profile = Gateway8163Profile()
        node = TopologyNode(
            node_key="224356000099",
            device_name="测试网关",
            device_type="8163网关",
            identifier="224356000099",
        )
        # 明细无 proxyCommType
        detail = {}
        task_config = TaskConfig()
        result = profile.resolve(node, task_config, detail)
        # 未填写不再报错阻断建档（D3）；仅告警且标记联通前置缺失
        assert not any("proxyCommType" in e for e in result.errors)
        assert any("proxyCommType" in w for w in result.warnings)
        assert result.link_blocked is True

    def test_gateway_address_conversion(self):
        """网关条码转 deviceAddress（12 位）。"""
        from archiving.profiles.gateway_8163 import Gateway8163Profile
        from archiving.models import TopologyNode

        profile = Gateway8163Profile()
        node = TopologyNode(
            node_key="224356000099",
            device_name="测试网关",
            device_type="8163网关",
            identifier="224356000099",
        )
        detail = {"proxyCommType": "1"}
        result = profile.resolve(node, None, detail)
        # 条码转 deviceAddress（去第 1/2/7 位，中间补 3 个 0）
        assert len(result.base_payload["deviceAddress"]) == 12

    def test_xlba_identifier_is_device_address(self):
        """XLBA identifier 通常直接等于 deviceAddress（原地址）。"""
        from archiving.profiles.meter_xlba import MeterXlbaProfile
        from archiving.models import TopologyNode

        profile = MeterXlbaProfile()
        node = TopologyNode(
            node_key="001234000001",
            device_name="测试电表",
            device_type="XLBA电表",
            identifier="001234000001",
            road_no="1",
        )
        detail = {"roadNo": "1"}
        result = profile.resolve(node, None, detail)
        # XLBA 原地址：identifier 直接等于 deviceAddress
        assert result.base_payload["deviceAddress"] == "001234000001"

    def test_leading_zero_preserved(self):
        """前导零保留（条码不截断）。"""
        from archiving.profiles.meter_xlba import MeterXlbaProfile
        from archiving.models import TopologyNode

        profile = MeterXlbaProfile()
        # 使用 12 位条码（符合 validate_device_address 要求）
        node = TopologyNode(
            node_key="001234000001",
            device_name="测试电表",
            device_type="XLBA电表",
            identifier="001234000001",
            road_no="1",
        )
        detail = {"roadNo": "1"}
        result = profile.resolve(node, None, detail)
        # 前导零保留（12 位条码）
        assert result.base_payload["deviceAddress"] == "001234000001"
        assert result.base_payload["deviceAddress"].startswith("0")


class TestFeeNumBitField:
    """任务 5.3 验收：feeNum 串口位域转换。"""

    def test_fee_num_computation(self):
        """feeNum = (baud << 5) | (stop << 4) | (check << 2) | data。"""
        from archiving.profiles.meter_xlba import _compute_fee_num

        # 115200/1位/无校验/8位 = (1<<5)|(0<<4)|(0<<2)|3 = 35
        assert _compute_fee_num("1", "0", "0", "3") == 35
        # 9600/1位/无校验/8位 = (6<<5)|(0<<4)|(0<<2)|3 = 195
        assert _compute_fee_num("6", "0", "0", "3") == 195

    def test_fee_num_from_profile(self):
        """profile 在四项串口参数均填写时计算 feeNum。"""
        from archiving.profiles.meter_xlba import MeterXlbaProfile
        from archiving.models import TopologyNode

        profile = MeterXlbaProfile()
        node = TopologyNode(
            node_key="001234000001",
            device_name="测试电表",
            device_type="XLBA电表",
            identifier="001234000001",
            road_no="1",
        )
        # 填写完整四项串口参数
        detail = {
            "roadNo": "1",
            "baudRate": "9600",
            "stopDigit": "1位停止位",
            "checkDigit": "无校验",
            "dataDigit": "8位",
        }
        result = profile.resolve(node, None, detail)
        # feeNum 应被计算：9600/1位/无校验/8位 = 195
        assert result.deploy_item_body["feeNum"] == 195

    def test_fee_num_not_computed_when_incomplete(self):
        """四项串口参数不完整时不计算 feeNum，不补默认。"""
        from archiving.profiles.meter_xlba import MeterXlbaProfile
        from archiving.models import TopologyNode

        profile = MeterXlbaProfile()
        node = TopologyNode(
            node_key="001234000001",
            device_name="测试电表",
            device_type="XLBA电表",
            identifier="001234000001",
            road_no="1",
        )
        # 只填写部分串口参数
        detail = {
            "roadNo": "1",
            "baudRate": "9600",
            # 缺少 stopDigit/checkDigit/dataDigit
        }
        result = profile.resolve(node, None, detail)
        # feeNum 不应存在（不补默认，不计算）
        assert "feeNum" not in result.deploy_item_body


class TestNoDefaultBackfill:
    """任务 5.4 验收：工程输入不足不补默认。"""

    def test_serial_params_not_backfilled(self):
        """串口参数不填写时留空，不补默认值。"""
        from archiving.profiles.meter_xlba import MeterXlbaProfile
        from archiving.models import TopologyNode

        profile = MeterXlbaProfile()
        node = TopologyNode(
            node_key="001234000001",
            device_name="测试电表",
            device_type="XLBA电表",
            identifier="001234000001",
            road_no="1",
        )
        # 不填写串口参数
        detail = {"roadNo": "1"}
        result = profile.resolve(node, None, detail)
        # 串口参数应留空（baudRate 显式空值清除残留，其他三项留空）
        assert not result.base_payload.get("baudRate")
        assert result.base_payload["stopDigit"] == ""
        assert result.base_payload["checkDigit"] == ""
        assert result.base_payload["dataDigit"] == ""

    def test_protocol_number_not_overridden(self):
        """协议代号不填写时留空，不被固定 200 覆盖。"""
        from archiving.profiles.meter_xlba import MeterXlbaProfile
        from archiving.models import TopologyNode

        profile = MeterXlbaProfile()
        node = TopologyNode(
            node_key="001234000001",
            device_name="测试电表",
            device_type="XLBA电表",
            identifier="001234000001",
            road_no="1",
        )
        # 不填写协议代号
        detail = {"roadNo": "1"}
        result = profile.resolve(node, None, detail)
        # 协议代号应留空
        assert result.base_payload["protocolNumber"] == ""

    def test_partial_serial_params_warns_not_blocks(self) -> None:
        """串口参数部分填写：不阻断建档，仅告警并跳过 feeNum 派生。"""
        from archiving.profiles.meter_xlba import MeterXlbaProfile
        from archiving.models import TopologyNode

        profile = MeterXlbaProfile()
        node = TopologyNode(
            node_key="001234000001",
            device_name="测试电表",
            device_type="XLBA电表",
            identifier="001234000001",
            road_no="1",
        )
        # 只填写部分串口参数
        detail = {
            "roadNo": "1",
            "baudRate": "9600",
            # 缺少 stopDigit/checkDigit/dataDigit
        }
        result = profile.resolve(node, None, detail)
        # 部分填写不再阻断（D3）：降级为 warning，已填项照常写入
        assert not any("串口参数不完整" in e for e in result.errors)
        assert any("串口参数不完整" in w for w in result.warnings)

    def test_measur_no_not_auto_incremented(self):
        """测量点号不填写时留空，禁止自增。"""
        from archiving.profiles.meter_xlba import MeterXlbaProfile
        from archiving.models import TopologyNode

        profile = MeterXlbaProfile()
        node = TopologyNode(
            node_key="001234000001",
            device_name="测试电表",
            device_type="XLBA电表",
            identifier="001234000001",
            road_no="1",
        )
        # 不填写测量点号
        detail = {"roadNo": "1"}
        result = profile.resolve(node, None, detail)
        # 测量点号应留空
        assert result.base_payload["measuredPointNum"] == ""

    def test_optional_serial_fields_not_defaulted(self):
        """每项可选串口参数单独留空不补默认。"""
        from archiving.profiles.meter_xlba import MeterXlbaProfile
        from archiving.models import TopologyNode

        profile = MeterXlbaProfile()
        node = TopologyNode(
            node_key="001234000001",
            device_name="测试电表",
            device_type="XLBA电表",
            identifier="001234000001",
            road_no="1",
        )
        # 只填波特率，其他串口参数留空
        detail = {"roadNo": "1", "baudRate": "9600"}
        result = profile.resolve(node, None, detail)
        # 波特率不写入档案顶层（显式空值清除残留），仅参与 feeNum 计算
        assert not result.base_payload.get("baudRate")
        # 停止位、校验位、数据位不应补默认（留空）
        assert result.base_payload.get("stopDigit") == ""
        assert result.base_payload.get("checkDigit") == ""
        assert result.base_payload.get("dataDigit") == ""

    def test_fee_num_not_computed_without_all_four(self):
        """四项串口参数不全时 feeNum 不计算。"""
        from archiving.profiles.meter_xlba import MeterXlbaProfile
        from archiving.models import TopologyNode

        profile = MeterXlbaProfile()
        node = TopologyNode(
            node_key="001234000001",
            device_name="测试电表",
            device_type="XLBA电表",
            identifier="001234000001",
            road_no="1",
        )
        # 只填三项，缺 dataDigit
        detail = {
            "roadNo": "1",
            "baudRate": "115200",
            "stopDigit": "1",
            "checkDigit": "0",
        }
        result = profile.resolve(node, None, detail)
        # feeNum 不应被计算（缺 dataDigit）
        assert "feeNum" not in result.deploy_item_body

    def test_fee_num_computed_with_all_four(self):
        """四项串口参数全填时 feeNum 正确计算。"""
        from archiving.profiles.meter_xlba import MeterXlbaProfile
        from archiving.models import TopologyNode

        profile = MeterXlbaProfile()
        node = TopologyNode(
            node_key="001234000001",
            device_name="测试电表",
            device_type="XLBA电表",
            identifier="001234000001",
            road_no="1",
        )
        # 115200-8-N-1（使用档案层字段名）
        detail = {
            "roadNo": "1",
            "baudRate": "115200",
            "stopDigit": "1",
            "checkDigit": "0",
            "dataDigit": "3",
        }
        result = profile.resolve(node, None, detail)
        assert "feeNum" in result.deploy_item_body

    def test_filled_not_applicable_param_preserved(self):
        """已填“不适用”参数不被清空或覆盖。"""
        from archiving.profiles.meter_xlba import MeterXlbaProfile
        from archiving.models import TopologyNode

        profile = MeterXlbaProfile()
        node = TopologyNode(
            node_key="001234000001",
            device_name="测试电表",
            device_type="XLBA电表",
            identifier="001234000001",
            road_no="1",
        )
        # 明确填写 cT 为 0（不适用）
        detail = {"roadNo": "1", "cT": "0"}
        result = profile.resolve(node, None, detail)
        # cT=0 应被保留（序列化用户填写值）
        assert "cT" in result.ext_infos
        assert result.ext_infos["cT"] == "0"
