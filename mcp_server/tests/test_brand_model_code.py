"""品牌/型号映射解析 + 转码测试（建档字段落点修复）。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_MCP_DIR = Path(__file__).parent.parent
if str(_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_MCP_DIR))

from mcp_server.archiving.models import TaskConfig
from mcp_server.archiving.profiles.gateway_8163 import Gateway8163Profile
from mcp_server.archiving.profiles.meter_xlba import MeterXlbaProfile
from mcp_server.archiving.models import TopologyNode


def _node(**kw) -> TopologyNode:
    defaults = dict(node_key="n", device_name="n", device_type="XLBA电表")
    defaults.update(kw)
    return TopologyNode(**defaults)


class TestBrandModelCode:
    """品牌/型号友好名 → code；gateway 补 identifier。"""

    def test_gateway_identifier_written(self):
        node = _node(node_key="gw", device_name="gw", device_type="8163网关",
                     identifier="224356000200")
        prof = Gateway8163Profile()
        r = prof.resolve(node, TaskConfig(), {"proxyCommType": "MQTT"})
        assert r.base_payload.get("identifier") == "224356000200"

    def test_gateway_no_identifier_omitted(self):
        node = _node(node_key="gw", device_name="gw", device_type="8163网关",
                     identifier="")
        prof = Gateway8163Profile()
        r = prof.resolve(node, TaskConfig(), {"proxyCommType": "MQTT"})
        assert "identifier" not in r.base_payload

    def test_meter_brand_model_to_code(self):
        cfg = TaskConfig(
            brand_name_to_code={"安科瑞": "1"},
            model_code_by_brand={"安科瑞": {"ADW300": "11"}},
        )
        node = _node()
        detail = {"brand": "安科瑞", "model": "ADW300", "roadNo": "1"}
        prof = MeterXlbaProfile()
        r = prof.resolve(node, cfg, detail)
        assert r.ext_infos["brand"] == "1"
        assert r.ext_infos["decimalNum"] == "11"

    def test_meter_empty_mapping_rejected(self):
        """未知品牌型号不得透传为设备码值。"""
        cfg = TaskConfig()
        node = _node()
        detail = {"brand": "安科瑞", "model": "ADW300", "roadNo": "1"}
        prof = MeterXlbaProfile()
        r = prof.resolve(node, cfg, detail)
        assert any("品牌/型号" in error for error in r.errors)
        assert "decimalNum" not in r.ext_infos
        assert "brand" not in r.ext_infos

    def test_meter_model_key_fixed(self):
        """detail 以 model 为键（reader 产出），应落到 extInfos.decimalNum 而非空。"""
        cfg = TaskConfig()
        node = _node()
        detail = {"brand": "安科瑞", "model": "ADW300", "roadNo": "1"}
        prof = MeterXlbaProfile()
        r = prof.resolve(node, cfg, detail)
        # 无 "未声明列" 警告关于 model
        assert not any("model" in w and "未声明" in w for w in r.warnings)

    def test_meter_user_big_no_dynamic_mapping(self):
        """动态映射应能将「环境传感器」翻译为码值 9，并正确派生 dsTypeId。"""
        cfg = TaskConfig(
            user_big_no_name_to_code={"环境传感器": "9", "电表类": "11"},
        )
        node = _node(identifier="001002003200")
        detail = {"roadNo": "1", "userBigNo": "环境传感器"}
        prof = MeterXlbaProfile()
        r = prof.resolve(node, cfg, detail)
        assert not r.errors, r.errors
        assert r.ext_infos["userBigNo"] == "9"
        # dsTypeId 使用两位数字格式（09 而非 9）
        assert r.ext_infos["dsTypeId"] == "10001909"

    def test_meter_user_big_no_fallback_to_hardcoded(self):
        """动态映射为空时，硬编码兜底应仍能翻译「电表类」为 11。"""
        cfg = TaskConfig()
        node = _node(identifier="001002003200")
        detail = {"roadNo": "1", "userBigNo": "电表类"}
        prof = MeterXlbaProfile()
        r = prof.resolve(node, cfg, detail)
        assert not r.errors, r.errors
        assert r.ext_infos["userBigNo"] == "11"
        assert r.ext_infos["dsTypeId"] == "10001911"

    def test_meter_user_big_no_unknown_name_rejected(self):
        """动态映射中不存在的名称必须被拒绝，不得透传。"""
        cfg = TaskConfig(
            user_big_no_name_to_code={"环境传感器": "9", "电表类": "11"},
        )
        node = _node(identifier="001002003200")
        detail = {"roadNo": "1", "userBigNo": "未知类型"}
        prof = MeterXlbaProfile()
        r = prof.resolve(node, cfg, detail)
        assert any("userBigNo" in error for error in r.errors)
        assert "userBigNo" not in r.ext_infos


@pytest.mark.parametrize(
    "name,barcode,road,brand,model,brand_code,model_code,interval,interval_code",
    [
        ("200", "001002003200", 200, "安科瑞", "ADW300", "1", "11", "1分钟", "1"),
        ("201", "001002003201", 201, "如皋八院空气能", "如皋八院空气能",
         "80", "310", "5分钟", "2"),
        ("203", "001002003203", 202, "安徽拓强", "安徽拖强电表值取反",
         "116", "406", "1分钟", "1"),
        ("204", "001002003204", 203, "德力西", "PD606K", "113", "448", "不抄表", "0"),
        ("205", "001002003205", 204, "德力西", "PD606K", "113", "448", "不抄表", "0"),
    ],
)
def test_batch_fields_match_all_three_targets(
    name, barcode, road, brand, model, brand_code, model_code, interval, interval_code,
) -> None:
    """按用户提供的五行输入验证编码，不读取原工作簿或伪装现场回执。"""
    cfg = TaskConfig(
        brand_name_to_code={brand: brand_code},
        model_code_by_brand={brand: {model: model_code}},
    )
    node = _node(device_name="监测点" + name, identifier=barcode, road_no=str(road))
    detail = {
        "brand": brand, "model": model, "roadNo": road, "measurNo": road,
        "interval": interval, "userBigNo": "电表类", "protocolNumber": "新联MQTT协议",
        "proxyCommPort": "1", "baudRate": "9600", "stopDigit": "1位停止位",
        "checkDigit": "无校验", "dataDigit": "8位", "cT": "100", "pT": "10",
    }
    resolved = MeterXlbaProfile().resolve(node, cfg, detail)
    assert not resolved.errors, resolved.errors
    assert resolved.base_payload["deviceAddress"] == barcode
    assert not resolved.base_payload.get("baudRate")  # 波特率不写档案顶层（空值清除残留）
    assert resolved.ext_infos["feeNum"] == "195"
    assert resolved.ext_infos["userSmallNo"] == interval_code
    assert resolved.ext_infos["decimalNum"] == model_code
    assert resolved.ext_infos["cT"] == "100" and resolved.ext_infos["pT"] == "10"
    assert "collCycle" not in resolved.ext_infos
    body = resolved.deploy_item_body
    assert body["feeNum"] == 195
    assert body["userSmallNo"] == int(interval_code)
    assert body["decimalNum"] == int(model_code)
    assert "baudRate" in body and body["baudRate"] == ""  # 实测契约含 baudRate，空占位清残留
    # RS485 未填电表密码：按页面占位默认补 12 个 E（2026-10-21 现场抓包实证）
    assert body["authParam"] == "EEEEEEEEEEEE"
    # 采集器地址按页面行为补默认 000000000000（避免 RTU DENY，预置前端默认字段）
    assert body["collCommAddr"] == "000000000000"


@pytest.mark.parametrize("field,value", [("baudRate", "未知"), ("interval", "2分钟")])
def test_unknown_enum_blocks(field: str, value: str) -> None:
    """未知枚举不得透传。"""
    result = MeterXlbaProfile().resolve(
        _node(identifier="001002003200", road_no="0"), TaskConfig(), {field: value},
    )
    assert result.errors


def test_zero_serial_values_preserved() -> None:
    """合法的数字0保留为位域0和不抄表，不回退默认。"""
    result = MeterXlbaProfile().resolve(
        _node(identifier="001002003200", road_no="0"), TaskConfig(),
        {"baudRate": 0, "stopDigit": 0, "checkDigit": 0, "dataDigit": 0, "interval": 0},
    )
    assert not result.errors, result.errors
    assert result.ext_infos["feeNum"] == "0"
    assert result.ext_infos["userSmallNo"] == "0"
    assert result.deploy_item_body["roadNo"] == 0


@pytest.mark.parametrize("barcode,address", [
    ("224356000200", "435600000200"), ("224356000210", "435600000210"),
    ("224356000220", "435600000220"), ("224356000300", "435600000300"),
])
def test_gateway_conversion_matches_175_handler(barcode: str, address: str) -> None:
    """对照175已核实的固定位置转换表达式。"""
    from mcp_server.archiving.converter import convert_comm_address

    assert convert_comm_address(barcode) == address
    assert address == barcode[2:6] + "000" + barcode[7:]


@pytest.mark.parametrize("field,value", [
    ("feeNum", -1), ("feeNum", 256), ("feeNum", "not-int"),
    ("proxyCommPort", 43), ("proxyCommPort", 44),
    ("ipAddress", "192.0.2.1"), ("ipPort", 1883),
])
def test_invalid_parameter_contract_blocks(field: str, value: object) -> None:
    """未知落点、特殊端口及超范围位域不能写入。

    IP 地址/端口号未选 ETH/MQTT 通信端口时阻断（无 IP 型端口承载）；
    proxyCommType 落点未核验但已降为不写入的声明列，不再硬阻断。
    """
    result = MeterXlbaProfile().resolve(
        _node(identifier="001002003200", road_no="0"), TaskConfig(), {field: value},
    )
    assert result.errors


@pytest.mark.parametrize("aliases", [
    {"interval": "5分钟", "userSmallNo": "1"},
    {"protocolCode": "200", "protocolNumber": "202"},
    {"agentNum": "2", "roadNo": "1"},
    {"measuredPointNum": "2", "measurNo": "1"},
    {"collectorAddress": "0", "collCommAddr": "1"},
    {"proxyCommPort": "1", "comPort": "2"},
])
def test_conflicting_aliases_block(aliases: dict) -> None:
    """同义字段冲突必须报错，不静默选择某个值。"""
    result = MeterXlbaProfile().resolve(
        _node(identifier="001002003200", road_no="0"), TaskConfig(), aliases,
    )
    assert any("输入不一致" in error for error in result.errors)


def test_equivalent_aliases_share_normalized_output() -> None:
    """友好名与同义码值统一解析，合法零值在三处保持一致。"""
    result = MeterXlbaProfile().resolve(
        _node(identifier="001002003200", road_no=0), TaskConfig(),
        {"protocolCode": "新联MQTT协议", "protocolNumber": "200",
         "interval": "不抄表", "userSmallNo": 0, "agentNum": 0,
         "measuredPointNum": 0, "comPort": 0, "collCommAddr": 0, "feeNum": 0},
    )
    assert not result.errors, result.errors
    for key in ("agentNum", "measuredPointNum", "proxyCommPort", "collectorAddress"):
        assert result.base_payload[key] == "0"
    for key in ("roadNo", "measurNo", "comPort", "feeNum", "userSmallNo"):
        assert result.deploy_item_body[key] == 0
    assert result.deploy_item_body["protocolCode"] == 200
    assert result.ext_infos["userSmallNo"] == result.ext_infos["feeNum"] == "0"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])