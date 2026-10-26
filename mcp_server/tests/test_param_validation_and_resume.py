"""参数校验降级 + 断点续跑 + 按类型在线判定 的单元验收。

对应 change refactor-param-validation-and-resume 的组5测试项。
"""
from __future__ import annotations

from unittest.mock import MagicMock

from archiving.engine import build_plan
from archiving.excel_reader import ArchiveTemplate
from archiving.models import TaskConfig, TopologyNode
from archiving.profiles.registry import default_registry

from edge_tools import (
    _parse_smart_event_online,
    _stage_succeeded,
    register_edge_tools,
)


def _mk_template(nodes, gateway_details=None, meter_details=None, errors=None):
    """构造最小 ArchiveTemplate 用于引擎级测试。"""
    tpl = ArchiveTemplate()
    tpl.task_config = TaskConfig()
    tpl.nodes = nodes
    tpl.gateway_details = gateway_details or {}
    tpl.meter_details = meter_details or {}
    tpl.errors = errors or []
    return tpl


def _gateway(node_key="gw1", name="网关1", proxy=""):
    node = TopologyNode(
        node_key=node_key, device_name=name, device_type="8163网关",
        identifier="224356000099", comm_address="224356000099",
    )
    detail = {"proxyCommType": proxy}
    return node, detail


def _meter(node_key="m1", name="电表1", parent="gw1", road_no="1"):
    return TopologyNode(
        node_key=node_key, device_name=name, device_type="XLBA电表",
        parent_key=parent, identifier="435600000001",
        comm_address="435600000001", road_no=road_no,
    )


class TestExecutableStructuralOnly:
    """可执行性只由结构性冲突决定（5.2 / 5.3 / 5.4）。"""

    def test_unfilled_proxy_comm_type_does_not_block(self):
        """网关未填 proxyCommType：仅告警，executable 仍 True（5.2）。"""
        gw, gw_detail = _gateway(proxy="")
        tpl = _mk_template([gw], gateway_details={"gw1": gw_detail})
        plan = build_plan(tpl, None, default_registry)
        assert plan.executable is True
        assert any("proxyCommType" in w for w in plan.warnings)

    def test_unsupported_type_blocks(self):
        """不支持设备类型：结构性冲突，executable=False（5.3）。"""
        bad = TopologyNode(
            node_key="x1", device_name="怪设备", device_type="未知类型",
        )
        tpl = _mk_template([bad])
        plan = build_plan(tpl, None, default_registry)
        assert plan.executable is False
        assert any(c.structural for c in plan.conflicts)

    def test_field_error_does_not_block_batch(self):
        """个别目标填非法值：字段级冲突（structural=False），
        executable 仍 True，不连坐整批（5.4）。"""
        gw, gw_detail = _gateway(proxy="13")
        # 分路号填了非法值 abc → 字段级错误
        bad_meter = _meter(node_key="m_bad", name="坏表", road_no="abc")
        ok_meter = _meter(node_key="m_ok", name="好表", road_no="2")
        tpl = _mk_template(
            [gw, bad_meter, ok_meter],
            gateway_details={"gw1": gw_detail},
            meter_details={
                "m_bad": {"roadNo": "abc"},
                "m_ok": {"roadNo": "2"},
            },
        )
        plan = build_plan(tpl, None, default_registry)
        # 字段级错误不拉低可执行性
        assert plan.executable is True
        field_conflicts = [c for c in plan.conflicts if not c.structural]
        assert any(c.node_key == "m_bad" for c in field_conflicts)

    def test_template_errors_block(self):
        """模板级结构性错误（如重名）：executable=False（5.3）。"""
        gw, gw_detail = _gateway(proxy="13")
        tpl = _mk_template(
            [gw], gateway_details={"gw1": gw_detail},
            errors=["挂载关系监测点名重复: m1"],
        )
        plan = build_plan(tpl, None, default_registry)
        assert plan.executable is False


class TestStageSucceededSkip:
    """续跑跳过已完成阶段（5.5 / 5.6 的原语）。"""

    def test_succeeded_stage_returns_true(self):
        from edge_tools import EdgeSession
        from archiving.stage_orchestrator import StageState

        tpl = _mk_template([_gateway(proxy="13")[0]])
        session = EdgeSession(tpl)
        orch = session.stages.get("dev-1")
        # 通过 _stage_for 建表并记一个 SUCCEEDED 阶段
        from edge_tools import _stage_for
        _stage_for(session, "dev-1").record_stage(
            "gateway_clock", StageState.SUCCEEDED, "已校时",
        )
        assert _stage_succeeded(session, "dev-1", "gateway_clock") is True
        assert _stage_succeeded(session, "dev-1", "param_deploy") is False
        assert _stage_succeeded(session, "absent", "gateway_clock") is False


class TestOnlineCheckByType:
    """在线判定按类型分派（5.7 / 5.8）。"""

    def test_online_check_method_per_type(self):
        from archiving.profiles.meter_xlba import MeterXlbaProfile
        from archiving.profiles.meter_lighting import MeterLightingProfile
        from archiving.profiles.meter_pdb import MeterPdbProfile
        from archiving.profiles.gateway_8163 import Gateway8163Profile

        assert MeterLightingProfile.online_check_method == "smart_event"
        assert MeterPdbProfile.online_check_method == "smart_event"
        assert MeterXlbaProfile.online_check_method == "monitor_debug"
        assert Gateway8163Profile.online_check_method == "monitor_debug"

    def test_parse_smart_event_has_record_online(self):
        resp = {
            "data": {
                "responseData": [
                    {
                        "deviceId": "6000000310953389",
                        "dataLabel": "onOff",
                        "dataArray": [{"dataTime": "x", "dataVal": "1"}],
                    }
                ]
            }
        }
        assert _parse_smart_event_online(resp, "6000000310953389") is True

    def test_parse_smart_event_empty_offline(self):
        assert _parse_smart_event_online(
            {"data": {"responseData": []}}, "6000000310953389",
        ) is False
        assert _parse_smart_event_online(
            {"data": {"responseData": [{"deviceId": "other",
                                        "dataArray": [{"v": 1}]}]}},
            "6000000310953389",
        ) is False

    def test_smart_event_online_via_tool(self):
        """照明节点走感知事件：mock client.call 返回记录 → online True。"""
        mcp = MagicMock()
        mcp.tool.return_value = lambda f: f
        register_edge_tools(mcp)
        from edge_tools import edge_check_monitor_online, edge_sessions

        gw, _ = _gateway()
        lighting = TopologyNode(
            node_key="lit1", device_name="路灯1", device_type="照明",
            parent_key="gw1", identifier="435600000009",
            comm_address="435600000009", road_no="1",
        )
        tpl = _mk_template([gw, lighting])
        tid = edge_sessions.create(tpl, owner_id="tester")
        sess = edge_sessions.get(tid, owner_id="tester")
        sess.key_to_device_id = {"gw1": "GW", "lit1": "LIT_DEV"}

        client = MagicMock()
        client.call.return_value = {
            "ok": True,
            "data": {
                "responseData": [
                    {"deviceId": "LIT_DEV", "dataLabel": "onOff",
                     "dataArray": [{"dataTime": "t", "dataVal": "1"}]},
                ]
            },
        }
        import edge_tools as tools
        tools._client_for = lambda s: client
        tools._derive_snapshot_owner = lambda tok: "tester"
        import session as sess_mod
        tok = sess_mod.mcp_token_var.get("x")
        res = edge_check_monitor_online(
            task_id=tid, node_key="lit1",
        )
        assert res["ok"] is True
        assert res["method"] == "smart_event"
        assert res["online"] is True
