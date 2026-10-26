"""refactor-xlpa-entry-and-permissions 变更的自动化测试。

覆盖：
  - 转换通讯地址（Group 4.4）
  - Profile registry（Group 5.3）
  - Token Registry 迁移（Group 3.1）
  - 权限矩阵：超级账号 + 业务 Token 缓存（Group 3.3-3.5）
  - EdgeDeviceClient 响应归一化与三态（Group 4.2）
  - 补偿清单记录（Group 6.6）
  - Showcase 数据汇总（Group 8）
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import re
import sys
import tempfile
from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 确保 mcp_server 在 sys.path 中
_MCP_DIR = Path(__file__).parent.parent
if str(_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_MCP_DIR))

os.environ.setdefault("MCP_AUTH_TOKEN", "test_token")


# ═══════════════════════════════════════════════════════════
# Group 4.4：转换通讯地址
# ═══════════════════════════════════════════════════════════


class TestConvertCommAddress:
    """转换通讯地址：去掉第 1、2、7 位并在中间补 3 个 0。"""

    def test_standard_conversion(self):
        from archiving.converter import convert_comm_address

        assert convert_comm_address("224356000099") == "435600000099"

    def test_short_input_raises(self):
        from archiving.converter import AddressConversionError, convert_comm_address

        with pytest.raises(AddressConversionError):
            convert_comm_address("12345")

    def test_empty_input_raises(self):
        from archiving.converter import AddressConversionError, convert_comm_address

        with pytest.raises(AddressConversionError):
            convert_comm_address("")

    def test_non_digit_raises(self):
        from archiving.converter import AddressConversionError, convert_comm_address

        with pytest.raises(AddressConversionError):
            convert_comm_address("22435600009X")

    def test_validate_device_address_12_chars(self):
        from archiving.converter import validate_device_address

        result = validate_device_address("435600000099")
        assert result == "435600000099"
        assert len(result) == 12

    def test_validate_device_address_short_raises(self):
        from archiving.converter import validate_device_address

        with pytest.raises(ValueError):
            validate_device_address("12345")


# ═══════════════════════════════════════════════════════════
# Group 5.3：Profile Registry
# ═══════════════════════════════════════════════════════════


class TestProfileRegistry:
    """Profile registry：按 deviceTypeId 查找 profile。"""

    def test_default_registry_has_gateway_8163(self):
        from archiving.profiles.registry import _build_default_registry

        reg = _build_default_registry()
        profile = reg.get(device_type_id="100009")
        assert profile is not None
        assert profile.device_type == "8163网关"

    def test_default_registry_has_meter_xlba(self):
        from archiving.profiles.registry import _build_default_registry

        reg = _build_default_registry()
        profile = reg.get(device_type_id="100019")
        assert profile is not None
        assert profile.device_type == "XLBA电表"

    def test_unknown_device_type_returns_none(self):
        from archiving.profiles.registry import _build_default_registry

        reg = _build_default_registry()
        profile = reg.get(device_type_id="999999")
        assert profile is None

    def test_virtual_gateway_placeholder(self):
        from archiving.profiles.registry import _build_default_registry

        reg = _build_default_registry()
        profile = reg.get(device_type_id="100015")
        assert profile is not None
        # 虚拟网关占位 profile 应提示二期实现
        assert "二期" in profile.device_type or "虚拟网关" in profile.device_type


# ═════════════════════════════════════════════════════════
# XLBA 电表 profile：档案字段补全 + extInfos 17 项
# ═════════════════════════════════════════════════════════


class TestMeterXlbaProfile:
    """XLBA 电表 profile：固化档案顶层字段与 17 项 extInfos。"""

    def _resolve(self, detail: dict):
        from archiving.models import TaskConfig, TopologyNode
        from archiving.profiles.meter_xlba import MeterXlbaProfile

        node = TopologyNode(
            node_key="435600000001",
            parent_key="224356000099",
            device_name="示例电表1",
            device_type="XLBA电表",
            identifier="435600000001",
            comm_address="435600000001",
            road_no="1",
        )
        profile = MeterXlbaProfile()
        return profile.resolve(node, TaskConfig(), detail)

    def test_ext_infos_has_17_keys_with_ct_pt(self):
        """design §5/§6：只序列化已填扩展项，不默认补全 17 项。"""
        result = self._resolve({"roadNo": "1", "measurNo": "1", "cT": "100", "pT": "100"})
        # 只输出已填的扩展项
        assert "cT" in result.ext_infos
        assert "pT" in result.ext_infos
        assert result.ext_infos["cT"] == "100"
        assert result.ext_infos["pT"] == "100"

    def test_ct_pt_from_detail(self):
        result = self._resolve({"roadNo": "1", "cT": "100", "pT": "100"})
        assert result.ext_infos["cT"] == "100"
        assert result.ext_infos["pT"] == "100"

    def test_ds_type_id_derived(self):
        """design §6：dsTypeId 仅在 deviceTypeId 和 userBigNo 均确定时派生。"""
        # 用户填写 "电表类" 翻译为 "11"，非默认值，触发 dsTypeId 派生
        result = self._resolve({"roadNo": "1", "userBigNo": "电表类"})
        assert result.ext_infos["dsTypeId"] == "10001911"

    def test_baud_rate_not_in_base_payload(self):
        """波特率不写入档案顶层（不与通信速率挂钩，显式空值清除残留）。"""
        result = self._resolve({"roadNo": "1", "baudRate": "9600"})
        assert not result.base_payload.get("baudRate")

    def test_agent_num_and_measured_point_from_template(self):
        result = self._resolve({"roadNo": "100", "measurNo": "100"})
        assert result.base_payload["agentNum"] == "100"
        assert result.base_payload["measuredPointNum"] == "100"

    def test_archive_comm_fields_present(self):
        result = self._resolve({"roadNo": "1"})
        for key in ("stopDigit", "checkDigit", "dataDigit",
                    "protocolNumber", "proxyCommPort"):
            assert key in result.base_payload

    # ── 受控回归：开放通信 IP/端口引入的 XLBA 行为差异 ──
    # 端口驱动组装与空 userBigNo 的 dsTypeId 分支对齐 10.0.17.23 实测；
    # authParam 下发默认值由 2026-10-21 两份现场抓包重新坐实（见下）。

    def test_rs485_empty_password_fills_auth_param_placeholder(self):
        """RS485 未填密码：下发 itemBody 补页面占位默认 12 个 E。

        实证：Path B 175 与 20.3.106.62 抓包的 20200002 itemBody
        均含 authParam；档案 extInfos 侧无实证支持默认值，不写入。
        """
        result = self._resolve({"roadNo": "1", "proxyCommPort": "1"})
        assert not result.errors, result.errors
        assert result.deploy_item_body["authParam"] == "EEEEEEEEEEEE"
        assert "authParam" not in result.ext_infos

    def test_rs485_password_falls_back_to_placeholder(self):
        """串口电表密码无法按 IP+端口编码 → 下发退回占位默认全 E。

        2026-10-21 定稿：下发 authParam 恒为 12 位十六进制，来源只有
        IP地址+IP端口号；档案 extInfos 侧仍保留透传的密码值。
        """
        result = self._resolve({
            "roadNo": "1", "proxyCommPort": "1", "authParam": "PWD123",
        })
        assert not result.errors, result.errors
        assert result.deploy_item_body["authParam"] == "EEEEEEEEEEEE"
        assert result.ext_infos["authParam"] == "PWD123"

    def test_unfilled_port_still_gets_placeholder(self):
        """通信端口未填：下发仍恒含 authParam，取占位默认全 E。"""
        result = self._resolve({"roadNo": "1"})
        assert not result.errors, result.errors
        assert result.deploy_item_body["authParam"] == "EEEEEEEEEEEE"

    def test_eth_port_without_ip_gets_placeholder(self):
        """IP 型端口但两列留空：下发补占位默认，档案侧不写。"""
        result = self._resolve({"roadNo": "1", "proxyCommPort": "40"})
        assert not result.errors, result.errors
        assert result.deploy_item_body["authParam"] == "EEEEEEEEEEEE"
        assert "authParam" not in result.ext_infos

    def test_rs485_with_ip_column_is_blocked(self):
        """RS485（非 IP 型端口）误填 IP地址/IP端口号：变严格阻断，不再静默忽略。"""
        result = self._resolve({
            "roadNo": "1", "proxyCommPort": "1",
            "ipAddress": "192.168.1.11", "ipPort": "21883",
        })
        assert result.errors
        assert any("authParam" in err for err in result.errors), result.errors

    def test_empty_user_big_no_ds_type_id_equals_type_id(self):
        """userBigNo 未填：dsTypeId=deviceTypeId 本身（不再补零成 10001900）。"""
        result = self._resolve({"roadNo": "1"})
        assert result.ext_infos["dsTypeId"] == "100019"

    def test_eth_port_opens_ip_into_auth_param(self):
        """ETH 端口填 IP：档案落五段串，下发落 12 位十六进制。"""
        result = self._resolve({
            "roadNo": "1", "proxyCommPort": "40",
            "ipAddress": "192.168.1.11", "ipPort": "21883",
        })
        assert not result.errors, result.errors
        # 档案 extInfos：10.0.17.23 建档实测为五段逗号串
        assert result.ext_infos["authParam"] == "192,168,1,11,21883"
        # 下发 itemBody：2026-10-21 抓包实证为 hex(IP 4B)+hex(port 2B)
        assert result.deploy_item_body["authParam"] == "c0a8010b557b"

    def test_eth_auth_param_hex_matches_field_capture(self):
        """回归现场抓包原值：192.168.23.150:21883 → c0a81796557b。"""
        result = self._resolve({
            "roadNo": "4", "proxyCommPort": "40",
            "ipAddress": "192.168.23.150", "ipPort": "21883",
        })
        assert not result.errors, result.errors
        auth = result.deploy_item_body["authParam"]
        assert auth == "c0a81796557b"
        assert len(auth) == 12

    def test_eth_port_overflow_is_blocked(self):
        """端口超出 16 位可编码范围：报错，不截断成错误报文。"""
        result = self._resolve({
            "roadNo": "1", "proxyCommPort": "40",
            "ipAddress": "192.168.23.150", "ipPort": "70000",
        })
        assert any("authParam" in err for err in result.errors), result.errors

    def test_eth_port_with_password_is_blocked(self):
        """ETH 端口 authParam 承载 IP，不得同时填电表密码（多态互斥）。"""
        result = self._resolve({
            "roadNo": "1", "proxyCommPort": "40",
            "ipAddress": "192.168.1.11", "ipPort": "21883",
            "authParam": "PWD123",
        })
        assert result.errors
        assert any("authParam" in err for err in result.errors), result.errors


class TestAuthParamNormalize:
    """下发侧 authParam 归一规则（12 位十六进制 / 占位全 E）。"""

    @staticmethod
    def _norm(value: str) -> str:
        from archiving.profiles.base import normalize_auth_param_for_deploy
        return normalize_auth_param_for_deploy(value)

    def test_empty_falls_back_to_placeholder(self):
        assert self._norm("") == "EEEEEEEEEEEE"
        assert self._norm("   ") == "EEEEEEEEEEEE"

    def test_five_segment_ip_string_is_hex_encoded(self):
        assert self._norm("192,168,23,150,21883") == "c0a81796557b"

    def test_already_hex_is_kept_lowercased(self):
        assert self._norm("C0A81796557B") == "c0a81796557b"

    def test_non_encodable_input_falls_back(self):
        assert self._norm("PWD123") == "EEEEEEEEEEEE"
        assert self._norm("192,168,1,1") == "EEEEEEEEEEEE"
        assert self._norm("1,2,3,4,99999") == "EEEEEEEEEEEE"


# ═══════════════════════════════════════════════════════════
# Group 3.1：Token Registry 迁移
# ═══════════════════════════════════════════════════════════


class TestTokenRegistryMigration:
    """Token Registry v1 → v2 user-only 迁移。"""

    def test_v1_registry_migrated_to_v2(self):
        from server import REGISTRY_SCHEMA_VERSION, TokenManager

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            tmp = Path(f.name)

        try:
            # 写入旧 v1 格式 registry
            v1_data = {
                "schema_version": 1,
                "entries": {
                    "192.168.1.100": {
                        "token": "old_token_1",
                        "accessLevel": "system",
                        "createdAt": 1000,
                    }
                },
            }
            tmp.write_text(json.dumps(v1_data), encoding="utf-8")

            mgr = TokenManager(admin_token="admin_tok", registry_path=tmp)

            # 迁移后 entry 的 accessLevel 应为 user
            info = mgr.get_token_info("192.168.1.100")
            assert info["accessLevel"] == "user"

            # 磁盘上应为 v2 schema
            disk = json.loads(tmp.read_text(encoding="utf-8"))
            assert disk["schema_version"] == REGISTRY_SCHEMA_VERSION
            assert disk["entries"]["192.168.1.100"]["accessLevel"] == "user"
            assert disk["entries"]["192.168.1.100"]["legacyMigrated"] is True
        finally:
            tmp.unlink(missing_ok=True)
            # 清理可能的备份文件
            for backup in tmp.parent.glob(f"{tmp.name}.*.backup"):
                backup.unlink(missing_ok=True)

    def test_v2_registry_no_migration(self):
        from server import REGISTRY_SCHEMA_VERSION, TokenManager

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            tmp = Path(f.name)

        try:
            v2_data = {
                "schema_version": REGISTRY_SCHEMA_VERSION,
                "entries": {
                    "10.0.0.5": {
                        "token": "user_tok",
                        "accessLevel": "user",
                        "createdAt": 2000,
                        "lastSeenAt": 2000,
                        "revoked": False,
                        "legacyMigrated": False,
                    }
                },
            }
            tmp.write_text(json.dumps(v2_data), encoding="utf-8")

            mgr = TokenManager(admin_token="admin_tok", registry_path=tmp)
            info = mgr.get_token_info("10.0.0.5")
            assert info["accessLevel"] == "user"
            assert info["token"] == "user_tok"
        finally:
            tmp.unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════
# Group 3.3-3.5：权限矩阵
# ═══════════════════════════════════════════════════════════


class TestPermissionMatrix:
    """超级账号配置 + 业务 Token 缓存 + 写权限判定。"""

    def test_super_account_hit(self):
        from permissions import SuperAccountConfig

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            json.dump({"superAccounts": {"userIds": ["u001"]}}, f)
            tmp = Path(f.name)

        try:
            cfg = SuperAccountConfig(tmp)
            assert cfg.is_super({"userId": "u001"}) is True
            assert cfg.is_super({"userId": "u999"}) is False
        finally:
            tmp.unlink(missing_ok=True)

    def test_super_account_empty_config(self):
        from permissions import SuperAccountConfig

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            tmp = Path(f.name)

        try:
            cfg = SuperAccountConfig(tmp)
            assert cfg.is_super({"userId": "anyone"}) is False
        finally:
            tmp.unlink(missing_ok=True)

    def test_business_token_cache_save_and_get(self):
        from permissions import BusinessTokenCache

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            tmp = Path(f.name)

        try:
            cache = BusinessTokenCache(tmp)
            cache.save("biz_tok_1", {"userId": "u1", "phone": "13800000001"})
            account = cache.get_account("biz_tok_1")
            assert account is not None
            assert account["userId"] == "u1"
        finally:
            tmp.unlink(missing_ok=True)

    def test_business_token_cache_invalidate(self):
        from permissions import BusinessTokenCache

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            tmp = Path(f.name)

        try:
            cache = BusinessTokenCache(tmp)
            cache.save("tok_x", {"userId": "ux"})
            assert cache.invalidate("tok_x") is True
            assert cache.get_account("tok_x") is None
            assert cache.invalidate("tok_x") is False
        finally:
            tmp.unlink(missing_ok=True)

    def test_most_recent_token(self):
        from permissions import BusinessTokenCache

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            tmp = Path(f.name)

        try:
            cache = BusinessTokenCache(tmp)
            assert cache.most_recent_token() is None
            cache.save("t1", {"userId": "a"})
            cache._entries["t1"]["lastSeenAt"] = 100
            cache.save("t2", {"userId": "b"})
            cache._entries["t2"]["lastSeenAt"] = 200
            assert cache.most_recent_token() == "t2"
        finally:
            tmp.unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════
# Group 4.2：EdgeDeviceClient 响应归一化与三态
# ═══════════════════════════════════════════════════════════


class TestEdgeClientNormalization:
    """EdgeDeviceClient 响应归一化。"""

    def test_normalize_success(self):
        from edge_client import EdgeDeviceClient

        resp = {"rtnCode": 0, "rtnMsg": "success", "rtnData": {"id": 1}}
        result = EdgeDeviceClient._normalize(resp)
        assert result["ok"] is True
        assert result["rtnCode"] == 0
        assert result["data"] == {"id": 1}

    def test_normalize_failure(self):
        from edge_client import EdgeDeviceClient

        resp = {"rtnCode": 1001, "rtnMsg": "设备不存在", "rtnData": None}
        result = EdgeDeviceClient._normalize(resp)
        assert result["ok"] is False
        assert result["rtnCode"] == 1001

    def test_normalize_invalid_input(self):
        from edge_client import EdgeDeviceClient

        result = EdgeDeviceClient._normalize("not a dict")
        assert result["ok"] is False
        assert result["rtnCode"] is None

    def test_link_state_enum_values(self):
        from edge_client import EdgeLinkState

        assert EdgeLinkState.OK.value == "OK"
        assert EdgeLinkState.NOT_CONFIGURED.value == "NOT_CONFIGURED"
        assert EdgeLinkState.OFFLINE_TIMEOUT.value == "OFFLINE_TIMEOUT"


# ═══════════════════════════════════════════════════════════
# Group 6.6：补偿清单记录
# ═══════════════════════════════════════════════════════════


class TestCompensationRecorder:
    """补偿清单记录与计划生成。"""

    def test_recorder_tracks_new_devices(self):
        from archiving.compensation import CompensationRecorder

        rec = CompensationRecorder()
        rec.record_created(
            node_key="meter_001",
            device_id="D001",
            device_name="电表1",
        )
        rec.record_created(
            node_key="meter_002",
            device_id="D002",
            device_name="电表2",
        )
        entries = rec.entries
        assert len(entries) == 2
        assert entries[0].node_key == "meter_001"
        assert entries[1].device_id == "D002"

    def test_recorder_empty_plan(self):
        from archiving.compensation import CompensationRecorder

        rec = CompensationRecorder()
        assert len(rec.entries) == 0
        result = rec.to_dict()
        assert "entries" in result


# ═══════════════════════════════════════════════════════════
# Group 8：Showcase 数据汇总
# ═══════════════════════════════════════════════════════════


class TestShowcaseData:
    """Showcase 数据汇总函数。"""

    def test_count_rows_with_total(self):
        from server import _count_rows

        result = {"data": {"rows": [1, 2], "total": 10}}
        assert _count_rows(result) == 10

    def test_count_rows_without_total(self):
        from server import _count_rows

        result = {"data": {"rows": [1, 2, 3]}}
        assert _count_rows(result) == 3

    def test_count_rows_empty(self):
        from server import _count_rows

        assert _count_rows({"data": {}}) == 0
        assert _count_rows({"data": None}) == 0

    def test_count_skills(self):
        from server import _count_skills

        count = _count_skills()
        assert count >= 5

    @pytest.mark.asyncio
    async def test_build_showcase_data_structure(self) -> None:
        """仅验证展示契约，不查询真实平台。"""
        from server import _build_showcase_data

        with patch("server._get_showcase_platform", new=AsyncMock(return_value={})):
            data = await _build_showcase_data()
        assert "toolCount" in data
        assert "skillCount" in data
        assert "serverVersion" in data
        assert "dataSource" in data
        assert "degraded" in data
        assert data["toolCount"] > 0
        assert data["skillCount"] > 0
        assert data["dataSource"] in ("live", "cache", "static")


@pytest.fixture
def showcase_server(monkeypatch, tmp_path) -> ModuleType:
    """隔离展示缓存、凭证和平台调用，禁止测试访问真实后端。"""
    import server

    monkeypatch.setattr(server, "SHOWCASE_CACHE_PATH", tmp_path / "showcase.json")
    monkeypatch.setattr(server, "SERVER_TEST_REPORT_PATH", tmp_path / "server-tests.json")
    monkeypatch.setattr(server, "_test_report_fallback", None)
    monkeypatch.setattr(server, "_showcase_platform_result", None)
    monkeypatch.setattr(server, "_showcase_platform_expires", 0.0)
    monkeypatch.setattr(server, "_showcase_platform_task", None)
    monkeypatch.setattr(server.system_token_mgr, "get_token", lambda: "test-only")
    monkeypatch.setattr(server, "_query_platform_stats", AsyncMock(return_value={
        "brandCount": 12, "deviceTypeCount": 7, "classifyCount": 2, "protocolCount": 20,
    }))
    return server


def _test_result_xml() -> str:
    """生成包含四类结果的结构化测试样本。"""
    return (
        '<testsuites><testsuite tests="4" failures="1" errors="1" skipped="1">'
        '<testcase classname="mcp_server.tests.test_example" name="pass" />'
        '<testcase classname="mcp_server.tests.test_example" name="fail"><failure /></testcase>'
        '<testcase classname="mcp_server.tests.test_example" name="error"><error /></testcase>'
        '<testcase classname="mcp_server.tests.test_example" name="skip"><skipped /></testcase>'
        '</testsuite></testsuites>'
    )


def test_server_test_report_counts_and_scope(showcase_server, tmp_path) -> None:
    """报告保留四类数量和真实时间，同一用例的清理错误不重复计数。"""
    server = showcase_server
    path = tmp_path / "results.xml"
    path.write_text(_test_result_xml(), encoding="utf-8")
    report = server._parse_server_test_xml(path, 1)
    assert report["testScope"] == "mcp_server/tests" and report["testAvailable"]
    assert report["testTotal"] == 4
    assert [report[key] for key in server._TEST_COUNT_KEYS] == [1, 1, 1, 1]
    assert datetime.fromisoformat(report["testRunAt"]).tzinfo is not None
    assert report["testSuites"] == [{"name": "test_example", "total": 4}]
    server._save_server_test_report(report)
    assert server._load_server_test_report() == report
    duplicate = (
        '<testcase classname="mcp_server.tests.test_example" name="fail"><error /></testcase>'
    )
    path.write_text(_test_result_xml().replace("</testsuite>", duplicate + "</testsuite>"))
    report = server._parse_server_test_xml(path, 1)
    assert report["testTotal"] == 4
    assert [report[key] for key in server._TEST_COUNT_KEYS] == [1, 0, 2, 1]


@pytest.mark.parametrize("content", ["{", "[]", "null", '{"testTotal":91}',
    '{"testScope":"protocol-conversion","testAvailable":true}'])
def test_server_test_report_rejects_legacy_and_broken(showcase_server, content: str) -> None:
    """损坏和其他范围报告不进入服务端指标，未知数量不伪装成零。"""
    server = showcase_server
    server.SERVER_TEST_REPORT_PATH.write_text(content, encoding="utf-8")
    result = server._load_server_test_report()
    assert not result["testAvailable"] and result["testTotal"] is None
    assert all(result[key] is None for key in server._TEST_COUNT_KEYS)


@pytest.mark.parametrize("field,value", [
    ("testTotal", 5), ("testPassed", True), ("testFailed", -1),
    ("testRunAt", "invalid"), ("testRunAt", "2026-09-24T00:00:00"),
    ("testSuites", []), ("testSuites", [{"name": "test_example", "total": True}]),
])
def test_server_test_report_rejects_invalid_counts(
    showcase_server, tmp_path, field: str, value,
) -> None:
    """数量、明细和时间必须一致且有效。"""
    server = showcase_server
    path = tmp_path / "results.xml"
    path.write_text(_test_result_xml(), encoding="utf-8")
    result = server._parse_server_test_xml(path, 1)
    result[field] = value
    server._save_server_test_report(result)
    assert server._load_server_test_report()["testTotal"] is None


@pytest.mark.parametrize("returncode", [2, 3, 4, 5])
def test_server_test_report_incomplete_exit(showcase_server, tmp_path, returncode: int) -> None:
    """中断、收集失败和未收集到用例不能冒充完整回归。"""
    server = showcase_server
    path = tmp_path / "partial.xml"
    path.write_text(_test_result_xml(), encoding="utf-8")
    report = server._parse_server_test_xml(path, returncode)
    assert report["testStatus"] == "INTERRUPTED" and report["testTotal"] is None


def test_server_test_runner_uses_full_scope(showcase_server, monkeypatch) -> None:
    """固定完整服务端范围，忽略环境筛选，结果不依赖 pytest 摘要文本。"""
    server = showcase_server
    monkeypatch.setenv("PYTEST_ADDOPTS", "-k selected -x")

    def run(command: list[str], **kwargs) -> MagicMock:
        """模拟只生成 XML 且标准输出为空的 pytest。"""
        assert command[3] == str(server.SCRIPT_DIR / "tests")
        assert "--maxfail=0" in command and "addopts=" in command
        assert "PYTEST_ADDOPTS" not in kwargs["env"]
        assert kwargs["timeout"] == 180 and kwargs["cwd"] == str(server.PROJECT_ROOT)
        report = Path(command[command.index("--junitxml") + 1])
        report.write_text(_test_result_xml(), encoding="utf-8")
        return MagicMock(returncode=1, stdout=b"", stderr=b"")

    mock = MagicMock(side_effect=run)
    monkeypatch.setattr(server.subprocess, "run", mock)
    result = server._run_startup_tests()
    assert result["testTotal"] == 4 and result["testStatus"] == "FAILED"
    mock.assert_called_once()


@pytest.mark.parametrize("failure", ["timeout", "missing", "broken", "empty"])
def test_server_test_runner_failure(showcase_server, monkeypatch, failure: str) -> None:
    """超时、缺报告、破损报告或零用例一律不可用。"""
    server = showcase_server

    def run(command: list[str], **kwargs) -> MagicMock:
        """模拟执行中断与结构化报告损坏。"""
        if failure == "timeout":
            raise server.subprocess.TimeoutExpired(command, 180)
        report = Path(command[command.index("--junitxml") + 1])
        if failure in ("broken", "empty"):
            report.write_text("<" if failure == "broken" else "<testsuites />")
        return MagicMock(returncode=0)

    monkeypatch.setattr(server.subprocess, "run", run)
    result = server._run_startup_tests()
    assert not result["testAvailable"] and result["testTotal"] is None


def test_server_test_background_isolation(showcase_server, monkeypatch, tmp_path) -> None:
    """后台运行时可读取状态，拒绝重复运行且不覆写业务事件计数。"""
    server = showcase_server
    monkeypatch.setattr(server, "STATS_PATH", tmp_path / "stats.json")
    server._save_stats({"scriptsGenerated": 57, "testTotal": 91})
    before = server.STATS_PATH.read_bytes()
    started, release = server.threading.Event(), server.threading.Event()

    def run() -> dict:
        """保持后台运行，模拟用户请求期间的自检。"""
        started.set()
        assert release.wait(5)
        return server._unavailable_test_report("INTERRUPTED")

    runner = MagicMock(side_effect=run)
    monkeypatch.setattr(server, "_run_startup_tests", runner)
    worker = server.threading.Thread(target=server._refresh_startup_test_report, daemon=True)
    worker.start()
    try:
        assert started.wait(5)
        assert server._load_server_test_report()["testStatus"] == "RUNNING"
        server._refresh_startup_test_report()
        runner.assert_called_once()
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert server._load_server_test_report()["testStatus"] == "INTERRUPTED"
    assert server.STATS_PATH.read_bytes() == before


def test_server_test_report_write_failure(showcase_server, monkeypatch, tmp_path) -> None:
    """只读部署目录保留当前进程真实状态，不继续使用旧成功值。"""
    server = showcase_server
    monkeypatch.setattr(server, "SERVER_TEST_REPORT_PATH", tmp_path / "missing/report.json")
    server._save_server_test_report(server._unavailable_test_report("INTERRUPTED"))
    assert server._load_server_test_report()["testStatus"] == "INTERRUPTED"
    runner = MagicMock(side_effect=RuntimeError("private-details"))
    monkeypatch.setattr(server, "_run_startup_tests", runner)
    server._refresh_startup_test_report()
    assert server._load_server_test_report()["testTotal"] is None


@pytest.mark.asyncio
async def test_showcase_reads_test_report_without_running_tests(
    showcase_server, monkeypatch, tmp_path,
) -> None:
    """平台缓存和页面轮询只读取回归报告，旧映射统计不再展示。"""
    server = showcase_server
    monkeypatch.setattr(server, "STATS_PATH", tmp_path / "stats.json")
    server._save_stats({"scriptsGenerated": 42, "testTotal": 91, "testPassed": 89})
    runner = MagicMock(side_effect=AssertionError("页面不得执行测试"))
    monkeypatch.setattr(server, "_run_startup_tests", runner)
    first = await server._build_showcase_data()
    assert first["scriptsGenerated"] == 42 and first["testTotal"] is None
    path = tmp_path / "results.xml"
    path.write_text(_test_result_xml(), encoding="utf-8")
    server._save_server_test_report(server._parse_server_test_xml(path, 1))
    second = await server._build_showcase_data()
    assert second["testTotal"] == 4 and second["testSkipped"] == 1
    assert second["dataSource"] == "cache" and second["scriptsGenerated"] == 42
    runner.assert_not_called()


def _write_test_skill(root: Path, name: str, entries: list[dict]) -> None:
    """在临时目录创建能力声明，不改动真实发布资源。"""
    folder = root / name
    folder.mkdir(exist_ok=True)
    (folder / "SKILL.md").write_text("测试技能", encoding="utf-8")
    (folder / "manifest.json").write_text(
        json.dumps({"protocolDirections": entries}), encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_showcase_catalog_matches_all_registered_tools(showcase_server) -> None:
    """所有注册工具完整展示，并保留边缘写工具的操作性质。"""
    server = showcase_server
    data = await server._build_showcase_data()
    registered = {tool.name for tool in await server.mcp.list_tools()}
    tools = {tool["name"]: tool for tool in data["tools"]}
    assert set(tools) == registered
    assert len(tools) == len(data["tools"]) == data["toolCount"]
    assert data["domainCount"] == len({tool["domain"] for tool in tools.values()})
    assert data["skillCount"] == len(data["skills"]) == server._count_skills()
    assert data["clientCount"] == len(data["clients"]) == 9
    assert {d["name"] for d in data["protocolDirections"]} == {"MODBUS", "MQTT", "HTTP", "建档"}
    assert data["protocolDirectionCount"] == 4
    assert tools["edge_delete_device"]["operation"] == "write"
    assert tools["edge_get_device_tree"]["operation"] == "read"
    assert "阻断" in tools["edge_call_device_data"]["description"]
    for tool in tools.values():
        assert set(tool) == {"name", "description", "type", "operation", "domain"}
    assert not {"token", "Authorization", "session", "task"}.intersection(data)
    assert "test-only" not in json.dumps(data)


@pytest.mark.asyncio
async def test_showcase_local_catalog_updates_during_platform_cache(
    showcase_server, monkeypatch,
) -> None:
    """平台缓存命中仍重新统计本地工具，新增未知业务域不遗漏。"""
    server = showcase_server
    before = await server._build_showcase_data()
    monkeypatch.setattr(server, "TOOL_DEFINITIONS", server.TOOL_DEFINITIONS + [
        {"name": "future_tool", "type": "edge_write", "description": "待确认"},
    ])
    after = await server._build_showcase_data()
    assert after["toolCount"] == before["toolCount"] + 1
    assert after["tools"][-1]["domain"] == "其他"
    assert after["tools"][-1]["operation"] == "write"
    assert after["protocolDirections"] == before["protocolDirections"]
    assert after["dataSource"] == "cache"
    assert after["updatedAt"] == before["updatedAt"]
    server._query_platform_stats.assert_awaited_once()
    monkeypatch.setattr(server, "TOOL_DEFINITIONS", server.TOOL_DEFINITIONS[:-2])
    assert (await server._build_showcase_data())["toolCount"] == before["toolCount"] - 1


def test_showcase_skills_and_top_directions_are_independent(
    showcase_server, monkeypatch, tmp_path,
) -> None:
    """新增子技能仅改变 Skill 数，增删顶层声明才改变方向数。"""
    monkeypatch.setattr(showcase_server, "SKILLS_DIR", tmp_path)
    top = {"id": "example", "name": "示例方向", "level": "top"}
    _write_test_skill(tmp_path, "main", [top, top])
    package = {"skills": ["main"]}
    result = showcase_server._skill_capabilities(package)
    assert result["skillCount"] == result["protocolDirectionCount"] == 1
    _write_test_skill(tmp_path, "child", [{"id": "child", "level": "sub"}])
    package["skills"].append("child")
    result = showcase_server._skill_capabilities(package)
    assert result["skillCount"] == 2 and result["protocolDirectionCount"] == 1
    _write_test_skill(tmp_path, "child", [dict(top, id="new", name="新增方向")])
    assert showcase_server._skill_capabilities(package)["protocolDirectionCount"] == 2
    _write_test_skill(tmp_path, "child", [])
    assert showcase_server._skill_capabilities(package)["protocolDirectionCount"] == 1
    _write_test_skill(tmp_path, "unlisted", [])
    assert showcase_server._skill_capabilities(package)["skillCount"] == 3


@pytest.mark.parametrize("manifest", ["{", "[]", '{"protocolDirections":{}}',
    '{"protocolDirections":[{"id":"x","name":"X"}]}'])
def test_showcase_invalid_direction_is_not_zero(
    showcase_server, monkeypatch, tmp_path, manifest: str,
) -> None:
    """损坏声明保留不可用语义，实际 Skill 数仍可统计。"""
    monkeypatch.setattr(showcase_server, "SKILLS_DIR", tmp_path)
    _write_test_skill(tmp_path, "main", [])
    (tmp_path / "main/manifest.json").write_text(manifest, encoding="utf-8")
    data = showcase_server._skill_capabilities({"skills": ["main"]})
    assert data["skillCount"] == 1
    assert data["protocolDirectionCount"] is None
    assert not data["protocolDirectionsAvailable"] and data["catalogErrors"]


def test_showcase_conflicting_and_missing_direction(
    showcase_server, monkeypatch, tmp_path,
) -> None:
    """重复标识名称冲突和发布资源缺失均不得产生部分总数。"""
    monkeypatch.setattr(showcase_server, "SKILLS_DIR", tmp_path)
    _write_test_skill(tmp_path, "main", [
        {"id": "same", "name": "A", "level": "top"},
        {"id": "same", "name": "B", "level": "top"},
    ])
    for names in (["main"], ["missing"]):
        data = showcase_server._skill_capabilities({"skills": names})
        assert data["protocolDirectionCount"] is None
    monkeypatch.setattr(showcase_server, "SKILLS_DIR", tmp_path / "absent")
    data = showcase_server._skill_capabilities({"skills": []})
    assert data["skillCount"] is None and not data["skillsAvailable"]


@pytest.mark.parametrize("content", ["{", "[]", "null"])
def test_showcase_invalid_package_manifest(
    showcase_server, monkeypatch, tmp_path, content: str,
) -> None:
    """错误的资源包声明不会破坏工具目录接口。"""
    path = tmp_path / "package.json"
    path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(showcase_server, "PACKAGE_MANIFEST_PATH", path)
    package = showcase_server._load_package_manifest()
    assert package["manifestError"]
    assert showcase_server._skill_capabilities(package)["protocolDirectionCount"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("cached", [False, True])
async def test_showcase_platform_degradation(showcase_server, cached: bool) -> None:
    """平台失败时仅使用真实缓存，并且不把异常凭证回显到公共接口。"""
    server = showcase_server
    if cached:
        server._write_showcase_cache({
            "platform": {"available": True, "brandCount": 5}, "updatedAt": "2026-01-01T00:00:00",
        })
    server._query_platform_stats.side_effect = RuntimeError("private-credential")
    data = await server._build_showcase_data()
    assert data["degraded"]
    assert data["dataSource"] == ("cache" if cached else "static")
    assert data["platform"]["available"] is cached
    assert data["toolCount"] == len(data["tools"]) and data["protocolDirectionCount"] == 4
    assert "private-credential" not in json.dumps(data)
    if cached:
        assert data["updatedAt"] == "2026-01-01T00:00:00"
    else:
        assert data["updatedAt"] is None
    await server._get_showcase_platform()
    server._query_platform_stats.assert_awaited_once()


@pytest.mark.asyncio
async def test_showcase_concurrent_refresh_and_cancellation(showcase_server, monkeypatch) -> None:
    """合并并发查询，单个调用取消不会取消其他浏览器共享的查询。"""
    started, release = asyncio.Event(), asyncio.Event()

    async def query(token: str) -> dict:
        """通过事件控制平台响应时序。"""
        started.set()
        await release.wait()
        return {"brandCount": 7}

    mock = AsyncMock(side_effect=query)
    monkeypatch.setattr(showcase_server, "_query_platform_stats", mock)
    first = asyncio.create_task(showcase_server._get_showcase_platform())
    await started.wait()
    second = asyncio.create_task(showcase_server._get_showcase_platform())
    await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    release.set()
    data = await second
    assert data["platform"]["brandCount"] == 7
    mock.assert_awaited_once()
    data["platform"]["brandCount"] = 999
    assert (await showcase_server._get_showcase_platform())["platform"]["brandCount"] == 7
    monkeypatch.setattr(showcase_server, "_showcase_platform_expires", 0)
    await showcase_server._get_showcase_platform()
    assert mock.await_count == 2


@pytest.fixture
def showcase_page() -> Iterator:
    """启动离线浏览器，不使用用户浏览器或真实服务凭证。"""
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(
            headless=True, channel="chromium", executable_path=os.getenv("PCA_TEST_BROWSER"),
        )
        context = browser.new_context(
            viewport={"width": 1366, "height": 900}, reduced_motion="reduce",
        )
        page = context.new_page()
        page.clock.install(time=1000000)
        page.clock.pause_at(1000000)
        page.add_init_script("""
            Object.defineProperty(document, 'hidden', {get: () => window.__hidden === true});
        """)
        yield page
        context.close()
        browser.close()


def _showcase_payload() -> dict:
    """使用真实公开能力目录搭配测试统计，不查询平台。"""
    import server

    tools = server._public_tool_catalog()
    return {
        "tools": tools, "toolCount": len(tools),
        "clients": copy.deepcopy(server.CLIENT_DEFINITIONS),
        "clientCount": len(server.CLIENT_DEFINITIONS),
        **server._skill_capabilities(server._load_package_manifest()),
        "scriptsGenerated": 23, "testTotal": 123, "testPassed": 120, "testFailed": 0,
        "testErrors": 0, "testSkipped": 3, "testAvailable": True, "testStatus": "PASSED",
        "testScope": "mcp_server/tests", "testRunAt": "2026-09-24T10:00:00+00:00",
        "testSuites": [{"name": "test_example", "total": 123}],
        "serverVersion": "1.2.3", "packageVersion": "2.3.4", "packageName": "test-assets",
        "platform": {"available": True, "brandCount": 8, "deviceTypeCount": 10},
        "dataSource": "live", "updatedAt": "2026-09-24T10:00:00", "degraded": False,
    }


def _serve_showcase(page, state: dict, path: str = "/showcase") -> list[str]:
    """拦截页面与 API 请求，模拟动态快照与接口失败。"""
    requests = []
    html = (_MCP_DIR / "static/showcase.html").read_text(encoding="utf-8")

    def route_request(route) -> None:
        """仅提供测试页面，意外外部请求直接阻断。"""
        url = route.request.url
        requests.append(url)
        if url.endswith("/api/showcase/data"):
            if state.get("fail"):
                route.fulfill(status=503, body="暂不可用")
            else:
                route.fulfill(json=state["data"])
        elif url == "http://showcase.test" + path:
            route.fulfill(content_type="text/html", body=html)
        else:
            route.abort()

    page.route("**/*", route_request)
    page.goto("http://showcase.test" + path)
    return requests


def _wait_showcase(page, text: str = "ONLINE") -> None:
    """等待请求完成后的状态渲染。"""
    page.wait_for_function(
        "text => document.querySelector('#status-txt').textContent === text", arg=text,
    )


def test_showcase_browser_dynamic_snapshot_and_scroll(showcase_page) -> None:
    """验证目录增减、搜索、焦点、窗口滚动和节点复用。"""
    page = showcase_page
    state = {"data": _showcase_payload()}
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    requests = _serve_showcase(page, state)
    _wait_showcase(page)
    count = state["data"]["toolCount"]
    assert page.locator("#domains .chip").count() == count
    assert page.locator("#metrics b").all_text_contents() == [str(count), "9", "9", "4"]
    assert sum(
        int(page.locator("#lg-" + key).inner_text()) for key in ("read", "write", "other")
    ) == count
    assert "建档" in page.locator("#direction-list").inner_text()
    page.clock.run_for(1000)
    page.locator("#capability").scroll_into_view_if_needed()
    page.locator("#matrix-search").fill("不存在的工具")
    assert page.locator("#domains .chip").count() == 0
    assert page.locator("#matrix-empty").is_visible()
    page.locator("#matrix-search").fill("edge_")
    assert page.locator("#domains .chip").count() > 0
    page.locator("#matrix-domain").select_option(label="档案与参数")
    assert page.locator("#domains .domain").count() == 1
    page.locator("#matrix-search").fill("")
    page.locator("#matrix-domain").select_option("")
    page.locator(".chip[data-n='edge_set_device_param']").focus()
    # tooltip 应反映被聚焦工具的当前描述（rtnCode 口径）
    assert "rtnCode=0" in page.locator("#tip").inner_text()
    page.evaluate("""() => {
        window.__metric = document.querySelector('#metrics b');
        window.__term = document.querySelector('#term-out').innerHTML;
        window.__top = document.querySelector('#matrix-scroll').scrollTop;
        window.__pageTop = scrollY;
    }""")
    state["data"]["tools"].append({
        "name": "future_tool", "domain": "新增业务域", "operation": "write", "description": "测试",
    })
    state["data"]["toolCount"] += 1
    state["data"]["skills"].append("future-child")
    state["data"]["skillCount"] += 1
    state["data"]["protocolDirections"].append({"id": "future", "name": "新增方向"})
    state["data"]["protocolDirectionCount"] += 1
    page.clock.run_for(59000)
    page.wait_for_function(
        "count => document.querySelector('#metrics b').textContent === String(count)",
        arg=count + 1,
    )
    assert page.locator("#metrics b").all_text_contents() == [str(count + 1), "10", "9", "5"]
    assert page.locator("#domains .chip").count() == count + 1
    assert str(count + 1) in page.locator("#pl-tool-count").text_content()
    assert "5 个协议方向" in page.locator("#closing-sub").inner_text()
    assert page.evaluate("document.activeElement.dataset.n") == "edge_set_device_param"
    assert page.evaluate("document.querySelector('#metrics b') === window.__metric")
    assert page.evaluate("document.querySelector('#matrix-scroll').scrollTop === window.__top")
    assert page.evaluate("scrollY === window.__pageTop")
    assert page.evaluate("document.querySelector('#term-out').innerHTML === window.__term")
    page.evaluate("window.__chip = document.querySelector('.chip')")
    page.clock.run_for(60000)
    page.wait_for_function("document.querySelector('#status-txt').textContent === 'ONLINE'")
    assert page.evaluate("document.querySelector('.chip') === window.__chip")
    state["data"]["tools"].pop()
    state["data"]["toolCount"] -= 1
    page.clock.run_for(60000)
    page.wait_for_function(
        "count => document.querySelector('#metrics b').textContent === String(count)", arg=count,
    )
    assert not errors
    assert sum(url.endswith("/showcase") for url in requests) == 1
    assert not any("access-info" in url for url in requests)


def test_showcase_browser_visibility_failure_and_recovery(showcase_page) -> None:
    """验证首次失败、隐藏暂停、恢复补查和最近数据保留。"""
    page = showcase_page
    state = {"data": _showcase_payload(), "fail": True}
    requests = _serve_showcase(page, state, "/")
    _wait_showcase(page, "UPDATE FAILED")
    assert page.locator("#metrics b").all_text_contents() == ["—"] * 4
    state["fail"] = False
    page.clock.run_for(60000)
    _wait_showcase(page)
    page.evaluate("window.__hidden = true; document.dispatchEvent(new Event('visibilitychange'))")
    previous = len(requests)
    page.clock.run_for(180000)
    assert len(requests) == previous
    state["fail"] = True
    page.evaluate("window.__hidden = false; document.dispatchEvent(new Event('visibilitychange'))")
    page.clock.run_for(1)
    _wait_showcase(page, "UPDATE FAILED")
    assert page.locator("#data-source-badge").count() == 0
    assert page.locator("#test-total").inner_text() == "123"
    assert page.locator("#metrics b").first.inner_text() == str(state["data"]["toolCount"])
    state["fail"] = False
    state["data"].update(protocolDirectionsAvailable=False, protocolDirectionCount=None)
    page.clock.run_for(60000)
    _wait_showcase(page)
    assert page.locator("#metrics b").last.inner_text() == "—"
    assert page.locator("#domains .chip").count() == state["data"]["toolCount"]
    previous = len(requests)
    page.clock.run_for(10000)
    page.evaluate("window.__hidden = true; document.dispatchEvent(new Event('visibilitychange'))")
    page.clock.run_for(10000)
    page.evaluate("window.__hidden = false; document.dispatchEvent(new Event('visibilitychange'))")
    page.clock.run_for(39000)
    assert len(requests) == previous
    page.clock.run_for(1000)
    page.wait_for_timeout(10)
    assert len(requests) == previous + 1


def test_showcase_browser_report_integrity(showcase_page) -> None:
    """上下两处仅展示总数，状态明细不渲染，异常报告不影响目录与轮询。"""
    page = showcase_page
    state = {"data": _showcase_payload()}
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    _serve_showcase(page, state)
    _wait_showcase(page)
    assert page.locator("#data-source-badge").count() == 0
    assert "降级模式" not in page.locator("body").inner_text()
    assert page.locator("#test-total").inner_text() == "123"
    removed = "#test-passed, #test-skipped, #test-status, #test-run-at, #test-errors, #test-failed"
    assert page.locator(removed).count() == 0
    assert page.locator(".test-card").inner_text().split() == ["123", "项", "回归测试用例"]
    assert "123" in page.locator("#delivery-stats .stat").last.inner_text()
    assert not page.locator("#delivery-stats .stat i").last.is_visible()
    page.evaluate("window.__stat = document.querySelector('#delivery-stats .stat:last-child')")
    state["data"].update(
        testTotal=124, testPassed=117, testFailed=2, testErrors=2,
        testStatus="FAILED", degraded=True,
        testSuites=[{"name": "test_example", "total": 124}],
    )
    page.clock.run_for(60000)
    page.wait_for_function("document.querySelector('#test-total').textContent === '124'")
    assert page.locator(".test-card").inner_text().split() == ["124", "项", "回归测试用例"]
    assert "124" in page.locator("#delivery-stats .stat").last.inner_text()
    text = page.locator(".test-grid").inner_text()
    text += page.locator("#delivery-stats .stat").last.inner_text()
    assert not re.search(r"\b(passed|failed|errors|skipped)\b", text, re.IGNORECASE)
    assert page.evaluate("SHOWCASE_DATA.delivery.test.testErrors") == 2
    state["data"]["testTotal"] = 999
    page.clock.run_for(60000)
    page.wait_for_function("document.querySelector('#test-total').textContent === '—'")
    assert page.locator("#test-suites .suite").count() == 0
    assert page.locator("#domains .chip").count() == state["data"]["toolCount"]
    state["data"].update(testAvailable=False, testStatus="INTERRUPTED")
    page.clock.run_for(60000)
    page.wait_for_function("SHOWCASE_DATA.delivery.test.testStatus === 'INTERRUPTED'")
    assert page.locator(".test-card").inner_text().split() == ["—", "项", "回归测试用例"]
    assert page.locator(removed).count() == 0
    assert page.evaluate("document.querySelector('#delivery-stats .stat:last-child') === __stat")
    assert not errors


def test_showcase_browser_timeout_and_late_response(showcase_page) -> None:
    """模拟忽略取消的慢请求，超时后重试且旧响应不能覆盖新快照。"""
    page = showcase_page
    state = {"data": _showcase_payload()}
    page.add_init_script("""
        window.__calls = 0;
        const originalFetch = window.fetch;
        window.fetch = (...args) => {
            window.__calls++;
            if (window.__calls === 1) {
                return new Promise(resolve => { window.__late = resolve; });
            }
            return originalFetch(...args);
        };
    """)
    _serve_showcase(page, state)
    page.clock.run_for(29000)
    assert page.evaluate("window.__calls") == 1
    page.clock.run_for(1000)
    _wait_showcase(page, "UPDATE FAILED")
    page.clock.run_for(30000)
    _wait_showcase(page)
    assert page.evaluate("window.__calls") == 2
    before = page.locator("#metrics b").all_text_contents()
    old = copy.deepcopy(state["data"])
    old["tools"], old["toolCount"] = [], 0
    page.evaluate("data => window.__late({ok: true, json: () => Promise.resolve(data)})", old)
    assert page.locator("#metrics b").all_text_contents() == before


def test_showcase_browser_narrow_matrix(showcase_page, tmp_path) -> None:
    """窄屏下长工具名可换行，扩展目录仅增长窗口内部高度。"""
    page = showcase_page
    page.set_viewport_size({"width": 390, "height": 844})
    data = _showcase_payload()
    data["tools"] += [
        {"name": "long_tool_" + "x" * 100 + str(i), "domain": "扩展", "operation": "other"}
        for i in range(120)
    ]
    data["toolCount"] = len(data["tools"])
    _serve_showcase(page, {"data": data})
    _wait_showcase(page)
    page.clock.run_for(1000)
    page.locator("#capability").scroll_into_view_if_needed()
    dimensions = page.evaluate("""() => {
        const el = document.querySelector('#matrix-scroll');
        return [el.clientHeight, el.scrollHeight, el.clientWidth, el.scrollWidth,
                document.documentElement.clientWidth, document.documentElement.scrollWidth];
    }""")
    assert 320 <= dimensions[0] <= 560 and dimensions[1] > dimensions[0]
    assert dimensions[2] == dimensions[3]
    assert dimensions[4] == dimensions[5]
    # 原生键盘滚动由浏览器合成线程驱动，不使用虚拟时钟判定完成。
    page.clock.resume()
    page.locator("#matrix-scroll").focus()
    page.keyboard.press("PageDown")
    page.wait_for_function("document.querySelector('#matrix-scroll').scrollTop > 0")
    page.screenshot(path=str(tmp_path / "showcase-narrow.png"))


def test_access_browser_all_client_configs(showcase_page, tmp_path) -> None:
    """验证九个配置格式、WorkBuddy 指引与复制下载一致性。"""
    page = showcase_page
    data = _showcase_payload()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    access = {
        "clients": data["clients"], "token": "test-only", "baseUrl": "http://127.0.0.1:8765",
        "accessLevel": "user", "source": "test", "serverIPs": [],
    }
    html = (_MCP_DIR / "static/access.html").read_text(encoding="utf-8")

    def route_request(route) -> None:
        """仅返回假接入凭证，不访问真实分配接口。"""
        if route.request.url.endswith("/api/access-info"):
            route.fulfill(json=access)
        else:
            route.fulfill(content_type="text/html", body=html)

    page.route("**/*", route_request)
    page.goto("http://access.test/access")
    page.wait_for_selector("#platform-cards button")
    assert page.locator("#platform-cards button").count() == 9
    expected = {
        "trae": ("mcpServers", "url", {}), "cursor": ("servers", "url", {"type": "http"}),
        "vscode": ("servers", "url", {"type": "http"}),
        "claude": ("mcpServers", "url", {"type": "streamableHttp"}),
        "windsurf": ("mcpServers", "serverUrl", {}),
        "cline": ("mcpServers", "url", {"type": "streamableHttp"}),
        "kimi": ("mcpServers", "url", {"transport": "http"}),
        "qoder": ("mcpServers", "url", {}),
        "workbuddy": ("mcpServers", "url", {"type": "streamableHttp"}),
    }
    for name, (root_key, url_key, transport) in expected.items():
        page.locator(f"button[data-platform='{name}']").click()
        text = page.evaluate("generatedText")
        config = json.loads(re.search(r"```json\s*([\s\S]*?)```", text).group(1))
        assert config == {root_key: {"xl-protocol-agent": {
            **transport, url_key: access["baseUrl"] + "/mcp",
            "headers": {"Authorization": "Bearer test-only"},
        }}}
        assert "幂等" in text and "损坏保护" in text and "list_mcp_tools" in text
        assert page.locator("#output").text_content().rstrip() == text.rstrip()
    text = page.evaluate("generatedText")
    assert "~/.workbuddy/mcp.json" in text and ".codebuddy/skills/" in text
    assert "MCP 配置为用户级" in text
    page.evaluate("""() => {
        Object.defineProperty(navigator, 'clipboard', {value: {
            writeText: text => { window.__copied = text; return Promise.resolve(); }
        }});
        URL.createObjectURL = blob => { window.__blob = blob; return 'blob:test'; };
        HTMLAnchorElement.prototype.click = function () {};
        copyText(); download();
    }""")
    assert page.evaluate("window.__copied") == text
    assert page.evaluate("window.__blob.text()") == text
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.screenshot(path=str(tmp_path / "access-workbuddy-narrow.png"))
    assert not errors


@pytest.mark.asyncio
async def test_showcase_public_routes_share_client_catalog(showcase_server, monkeypatch) -> None:
    """公开路由返回同一客户端目录，展示接口不暴露接入凭证。"""
    import httpx

    server = showcase_server
    manager = MagicMock()
    manager.get_token_info.return_value = {
        "token": "test-private-value", "accessLevel": "user", "source": "test",
    }
    monkeypatch.setattr(server, "_get_server_ips", lambda: [])
    app = server.CompositeApp(None, server.ACCESS_HTML, manager, server.SHOWCASE_HTML)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test",
    ) as client:
        root = await client.get("/")
        showcase = await client.get("/showcase")
        access = await client.get("/access")
        assert root.status_code == showcase.status_code == access.status_code == 200
        assert root.text == showcase.text and root.text != access.text
        data = (await client.get("/api/showcase/data")).json()
        assert manager.get_token_info.call_count == 0
        info = (await client.get("/api/access-info")).json()
        assert data["clients"] == info["clients"] == server.CLIENT_DEFINITIONS
        assert "test-private-value" not in json.dumps(data)
        assert info["token"] == "test-private-value"


def test_archive_tool_catalog_matches_registration() -> None:
    """目录与真实注册工具一致，不导入server启动应用。"""
    import ast
    import asyncio

    from mcp.server.fastmcp import FastMCP

    from edge_tools import EDGE_TOOL_NAMES, register_edge_tools

    syntax = ast.parse((_MCP_DIR / "server.py").read_text(encoding="utf-8-sig"))
    definition = next(
        node.value for node in syntax.body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "TOOL_DEFINITIONS"
                for target in node.targets)
    )
    catalog = ast.literal_eval(definition)
    names = [item["name"] for item in catalog]
    mcp = FastMCP("catalog-test")
    register_edge_tools(mcp)
    registered = {tool.name for tool in asyncio.run(mcp.list_tools())}
    assert registered == set(EDGE_TOOL_NAMES)
    assert len(names) == len(set(names))
    assert registered.issubset(names)


def test_archive_distribution_contract() -> None:
    """验证资源必需文件及主子Skill版本，避免分发缺失新契约。"""
    import re

    assets = _MCP_DIR.parent / "agent_assets"
    package = json.loads((assets / "skills/package-manifest.json").read_text(encoding="utf-8"))
    for relative in package["requiredFiles"]:
        assert (assets / relative).is_file(), relative
    for name in ("xlpa", "xlpa-device-archiving", "modbus-conversion", "test-validation"):
        folder = assets / "skills" / name
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        text = (folder / "SKILL.md").read_text(encoding="utf-8")
        version = re.search(r"^\s*version:\s*[\"']?([0-9.]+)", text, flags=re.MULTILINE)
        assert version and version.group(1) == manifest["version"]
        for relative in manifest["required"]:
            assert (folder / relative).is_file(), relative
        if name == "xlpa-device-archiving":
            assert "references/gateway-button-endpoints.md" in manifest["required"]
            for tool in ("edge_save_device_parameters", "get_device_archive_task_report"):
                assert tool in text
    version = json.loads((_MCP_DIR / "version.json").read_text(encoding="utf-8"))
    assert re.fullmatch(r"\d+\.\d+\.\d+", version["serverVersion"])


@pytest.fixture(scope="module")
def modbus_docs() -> dict[str, str]:
    """读取发布源文档，不使用客户端副本或调用平台。"""
    root = _MCP_DIR.parent
    paths = {
        "skill": "agent_assets/skills/modbus-conversion/SKILL.md",
        "validation": "agent_assets/skills/test-validation/SKILL.md",
        "spec": "openspec/specs/modbus-mcp-workflow/spec.md",
    }
    return {name: (root / path).read_text(encoding="utf-8") for name, path in paths.items()}


def _document_section(text: str, start: str, end: str) -> str:
    """截取已知章节，缺失标题时直接失败。"""
    assert start in text and end in text
    return text.split(start, 1)[1].split(end, 1)[0]


def _first_markdown_table(text: str) -> list[dict[str, str]]:
    """读取章节首个简单表格，仅供文档契约测试。"""
    rows = []
    for line in text.splitlines():
        if line.startswith("|"):
            rows.append([cell.strip().strip("`") for cell in line.strip("|").split("|")])
        elif rows:
            break
    assert len(rows) >= 3
    header = rows[0]
    assert all(re.fullmatch(r":?-+:?", cell) for cell in rows[1])
    return [dict(zip(header, row, strict=True)) for row in rows[2:]]


def test_modbus_resource_versions() -> None:
    """两个技能与资源包同步升版，不要求改变服务器版本。"""
    skills = _MCP_DIR.parent / "agent_assets/skills"
    expected = {"modbus-conversion": "0.4.1", "test-validation": "0.1.1"}
    for name, version in expected.items():
        manifest = json.loads((skills / name / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["version"] == version
    package = json.loads((skills / "package-manifest.json").read_text(encoding="utf-8"))
    assert tuple(map(int, package["version"].split("."))) >= (0, 8, 1)
    assert set(expected).issubset(package["skills"])


def test_modbus_query_entry_contract(modbus_docs: dict[str, str]) -> None:
    """查询示例匹配实际签名，流程及来源不再依赖规约数据项。"""
    import ast

    skill = modbus_docs["skill"]
    section = _document_section(skill, "#### 4.3 查询原子标签", "**文档选择规则**")
    match = re.search(r"`(get_function_type_list\([^`\n]+\))`", section)
    assert match
    call = ast.parse(match.group(1), mode="eval").body
    assert isinstance(call, ast.Call) and not call.args
    arguments = {item.arg: ast.literal_eval(item.value) for item in call.keywords}
    syntax = ast.parse((_MCP_DIR / "server.py").read_text(encoding="utf-8-sig"))
    definition = next(
        node for node in syntax.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_function_type_list"
    )
    defaults = dict(zip(
        [arg.arg for arg in definition.args.args],
        [ast.literal_eval(value) for value in definition.args.defaults],
        strict=True,
    ))
    assert arguments == defaults == {
        "functionTypeName": "", "functionCode": "", "pageIndex": 1, "pageSize": 9999,
    }
    assert "不依赖 `protocolId`" in section
    assert "单页未命中" in section and "分页" in section and "复用" in section
    assert "查询失败" in section and "不得" in section and "新增流程" in section
    assert "get_data_item_list" not in section
    flow = _document_section(skill, "## 处理流程", "### 步骤 1")
    assert "get_function_type_list" in flow and "get_data_item_list" not in flow
    tools = _first_markdown_table(
        _document_section(skill, "### 原子工具映射表", "### 查询通用规则")
    )
    entries = {row["阶段"]: row for row in tools}
    assert entries["查原子标签"]["工具"] == "get_function_type_list"
    assert entries["查规约数据项"]["工具"] == "get_data_item_list"
    assert "MCP:get_data_item_list.rows" not in skill
    for text in (skill, modbus_docs["spec"]):
        assert "MCP:get_function_type_list.rows[i].unit" in text
        assert "functionId" in text and "规约数据项 ID" in text
        assert "functionCode" in text and "func_code" in text and "dataType" in text
        assert "不新增平台功能项写入路径" in text


@pytest.mark.parametrize("document", ["skill", "validation", "spec"])
def test_modbus_type_and_unit_document_contract(
    modbus_docs: dict[str, str], document: str,
) -> None:
    """各文档覆盖类型和单位确认信息，仅验证资源契约。"""
    text = modbus_docs[document]
    for data_type in (
        "[UINT16]", "[SINT16]", "[UINT32]", "[SINT32]", "[FLOAT]",
        "[SBCD16]", "[UBCD16]", "[BITS]", "[0:3]", "[0:7]", "[8:15]",
    ):
        assert data_type in text
    assert "FLOAT32" not in text
    for column in (
        "源单位", "目标单位", "协议精度/原公式", "单位换算关系", "最终 data_exprs",
        "来源", "验证样例",
    ):
        assert column in text
    for boundary in ("符号位置", "符号码", "异常编码", "二进制补码", "未验证"):
        assert boundary in text
    for stage in ("静态契约检查", "离线算例", "真实引擎测试", "现场测试"):
        assert stage in text
    assert "不新增引擎 JSON 字段" in text
    assert "不自动迁移" in text


def test_modbus_type_spans_document_contract(modbus_docs: dict[str, str]) -> None:
    """类型核心表保留位范围，明确 BCD 和浮点的寄存器跨度。"""
    section = _document_section(
        modbus_docs["skill"], "### 1. data_type", "### 2. data_order",
    )
    rows = {row["格式"]: row["长度"] for row in _first_markdown_table(section)}
    expected = {
        "[UINT16]": 1, "[SINT16]": 1, "[UBCD16]": 1, "[SBCD16]": 1,
        "[UINT32]": 2, "[SINT32]": 2, "[FLOAT]": 2,
        "[0:3]": 1, "[0:7]": 1, "[8:15]": 1,
    }
    assert rows == {name: f"{span}寄存器" for name, span in expected.items()}
    assert "不能使用未指定范围的 `[BITS]`" in section
    assert "不把高字节位号擅自移到低字节" in section


@pytest.mark.parametrize("order", ["AB", "BA", "ABCD", "DCBA", "BADC", "CDAB"])
def test_modbus_byte_order_examples_offline(
    modbus_docs: dict[str, str], order: str,
) -> None:
    """核对文档中的不同字节排列，不模拟真实引擎解码。"""
    section = _document_section(
        modbus_docs["skill"], "### 2. data_order", "### 3. data_exprs",
    )
    rows = {row["值"]: row for row in _first_markdown_table(section)}
    assert set(rows) == {"AB", "BA", "ABCD", "DCBA", "BADC", "CDAB"}
    values = dict(zip("ABCD", bytes.fromhex("12 34 56 78"), strict=True))
    expected = bytes(values[letter] for letter in order)
    assert bytes.fromhex(rows[order]["字节排列示例"]) == expected
    assert rows[order]["长度"] == f"{len(order)} 字节"
    for document in modbus_docs.values():
        assert order in document
    for heading, end in (
        ("### 最小冒烟测试清单", "### 未验证项清单"),
        ("## 约束规则", "| 查询失败不新增"),
    ):
        assert order in _document_section(modbus_docs["skill"], heading, end)


@pytest.mark.parametrize(
    ("raw", "bit_range", "expected"),
    [(0xAB, "[0:3]", 11), (0x1234, "[8:15]", 18), (0x1234, "[0:7]", 52)],
)
def test_modbus_bit_examples_offline(
    modbus_docs: dict[str, str], raw: int, bit_range: str, expected: int,
) -> None:
    """按既有位号核对算例，不扩大引擎的位范围支持边界。"""
    start, end = (int(part) for part in bit_range.strip("[]").split(":"))
    assert (raw >> start) & ((1 << (end - start + 1)) - 1) == expected
    smoke = _document_section(
        modbus_docs["skill"], "### 最小冒烟测试清单", "### 未验证项清单",
    )
    assert f"{bit_range}={expected}" in smoke


@pytest.mark.parametrize(
    ("case", "source", "target", "expression", "raw", "expected"),
    [
        ("W→kW", "W", "kW", "$D/1000", "1500", "1.5"),
        ("kW→W", "kW", "W", "$D*1000", "1.5", "1500"),
        ("0.1 W→kW", "W", "kW", "$D/10/1000", "15000", "1.5"),
        ("负值", "W", "kW", "$D/1000", "-1500", "-1.5"),
        ("零值", "W", "kW", "$D/1000", "0", "0"),
        ("同单位", "kW", "kW", "\"\"", "1.5", "1.5"),
        ("已有换算", "W", "kW", "$D/1000", "1500", "1.5"),
        ("同单位精度", "kW", "kW", "$D/10", "15", "1.5"),
    ],
)
def test_modbus_unit_examples_offline(
    modbus_docs: dict[str, str], case: str, source: str, target: str,
    expression: str, raw: str, expected: str,
) -> None:
    """读取文档算例验证乘除数学关系，不验证 C 引擎表达式执行。"""
    section = _document_section(
        modbus_docs["skill"], "**单位离线算例**", "**单位待确认门控**",
    )
    rows = {row["场景"]: row for row in _first_markdown_table(section)}
    row = rows[case]
    assert (row["源单位"], row["目标单位"]) == (source, target)
    assert row["最终 data_exprs"] == expression
    assert (row["输入值"], row["期望值"]) == (raw, expected)
    value = Decimal(row["输入值"])
    formula = row["最终 data_exprs"]
    if formula != "\"\"":
        # 仅核对表内简单乘除，不使用 eval 或实现通用转换引擎。
        assert re.fullmatch(r"\$D(?:[*/]\d+(?:\.\d+)?)*", formula)
        for operator, operand in re.findall(r"([*/])(\d+(?:\.\d+)?)", formula):
            factor = Decimal(operand)
            value = value * factor if operator == "*" else value / factor
    assert value == Decimal(expected)


@pytest.mark.parametrize(
    "case", ["单位未知", "单位冲突", "随设备配置变化", "不同物理量", "复杂关系无公式"],
)
def test_modbus_unit_blocking_document_contract(
    modbus_docs: dict[str, str], case: str,
) -> None:
    """门控规则必须明确阻断；不声称测试了实际生成器行为。"""
    section = _document_section(
        modbus_docs["skill"], "**单位待确认门控**", "### 4. addr_exprs",
    )
    rows = {row["情形"]: row["处理"] for row in _first_markdown_table(section)}
    assert "阻断" in rows[case]
    assert "不因无物理单位阻断" in rows["明确无量纲或枚举"]
    assert "W 与 kWh" in rows["不同物理量"]


def test_modbus_validation_uses_real_fields(modbus_docs: dict[str, str]) -> None:
    """专项测试采用真实字段，不添加虚构配置或扩大功能码。"""
    section = _document_section(
        modbus_docs["validation"], "### Modbus 专项测试", "## 操作流程",
    )
    rows = _first_markdown_table(section)
    methods = " ".join(row["方法"] for row in rows)
    for field in ("addr_base", "addr_exprs", "data_type", "data_order", "data_exprs", "func_code"):
        assert field in methods
    for unsupported in ("readPlan", "polling", "scale", "address", "byteOrder", "functionCode"):
        assert unsupported not in methods
    assert "read=3/4，write=6/16" in section
    for document in (modbus_docs["skill"], section, modbus_docs["spec"]):
        for rule in ("不可逆", "舍入", "阻断", "write", "convert", "位提取与按位运算互斥"):
            assert rule in document


def test_modbus_legacy_example_contract(modbus_docs: dict[str, str]) -> None:
    """保护历史样例字段及关键公式，不校验其省略的点位定义。"""
    text = _document_section(
        modbus_docs["skill"], "## 实际 JSON 配置样例", "## 交互记录输出规范",
    )
    examples = [json.loads(block) for block in re.findall(r"```json\s*([\s\S]*?)```", text)]
    assert len(examples) == 3
    operation_fields = {
        "addr_base", "data_type", "data_order", "addr_exprs", "data_exprs", "func_code",
    }
    for config in examples:
        assert set(config) == {"prtlType", "modelNum", "classNum", "taskList", "labelList"}
        order = config["taskList"][0]["labels"]
        for label in config["labelList"]:
            assert "read" in label
            for operation in ("read", "write"):
                if operation not in label:
                    continue
                fields = label[operation]
                assert set(fields) == operation_fields
                assert fields["func_code"] in ((3, 4) if operation == "read" else (6, 16))
                for dependency in re.findall(r"\$'([^']+)'", fields["data_exprs"]):
                    assert order.index(dependency) < order.index(label["name"])
            for mapping in label.get("convert", []):
                assert set(mapping) == {"name", "org", "reg"}
    meter = {label["name"]: label for label in examples[0]["labelList"]}
    assert examples[0]["taskList"][0]["labels"][:6] == ["PT", "CT", "DPT", "DCT", "DPQ", "PQ"]
    assert meter["DPT"]["read"]["data_type"] == "[8:15]"
    assert meter["DCT"]["read"]["data_type"] == "[0:7]"
    assert meter["PQ"]["read"]["data_type"] == "[UINT16]"
    assert meter["PT"]["read"]["data_exprs"] == ""
    assert meter["voltageA"]["read"]["data_exprs"] == "$D*pow(10,($'DPT'-4))"
    assert meter["indicatedFApT"]["read"]["data_exprs"] == "$D/1000*$'PT'*$'CT'"
    multi = {label["name"]: label for label in examples[1]["labelList"]}
    assert multi["remoteStatus"]["write"]["addr_exprs"] == "$A+160*16*($M-1)+16*($I-1)"
    assert multi["airConPattern"]["convert"][0] == {"name": "自动", "org": 3, "reg": 0}

