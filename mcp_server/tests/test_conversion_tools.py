"""转换执行能力测试：校验、测试数据、沙箱执行、报告、产物工具。

覆盖 C6 新增能力：三契约校验、测试输入生成、沙箱执行（真实镜像引擎）、
报告归属隔离、配置保存、打包测试门控与 SHA256 清单。
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest

_MCP_DIR = Path(__file__).resolve().parent.parent
if str(_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_MCP_DIR))

_ROOT = _MCP_DIR.parent
ENGINE_DIR = str(_ROOT / "agent_assets" / "skills" / "protocol-conversion" / "scripts")

from archiving.snapshot_store import SnapshotStore  # noqa: E402
from conversion.executor import Executor, SandboxError  # noqa: E402
from conversion.report_store import ReportStore  # noqa: E402
from conversion.testdata import generate_test_data  # noqa: E402
from conversion.validator import validate_config  # noqa: E402
import conversion.conversion_tools as ct  # noqa: E402
from session import mcp_token_var  # noqa: E402

# ── 样例 ──

MQTT_CONFIG = {
    "platform_name": "test",
    "mappings": [
        {"target": "deviceId", "source": "roadNo", "source_type": "path", "type": "string"},
        {"target": "value", "source": "voltageA", "source_type": "path", "type": "double", "scale": 10.0},
    ],
}

HTTP_CONFIG = {
    "base_url": "https://api.test",
    "token": {"path": "data.token"},
    "apis": [
        {"data_mappings": [
            {"target": "devId", "source": "item[0].id", "source_type": "path", "type": "string"},
        ]},
    ],
}

MODBUS_CONFIG = {
    "prtlType": "MODBUS-RTU",
    "modelNum": 10001911,
    "classNum": 11,
    "taskList": [{"labels": ["voltageA"]}],
    "labelList": [{
        "name": "voltageA",
        "read": {"addr_base": 37, "data_type": "[UINT16]", "data_order": "AB",
                 "addr_exprs": "", "data_exprs": "", "func_code": 3},
    }],
}


# ── validator ──

def test_validate_mqtt_ok():
    result = validate_config("mqtt_to_mqtt", MQTT_CONFIG)
    assert result["ok"] is True and result["errors"] == []


def test_validate_http_ok():
    assert validate_config("http_to_mqtt", HTTP_CONFIG)["ok"] is True


def test_validate_modbus_ok():
    assert validate_config("modbus_to_internal", MODBUS_CONFIG)["ok"] is True


def test_validate_mqtt_missing_required_and_bad_enum():
    cfg = {"platform_name": "", "mappings": [
        {"target": "x", "source_type": "bad_type", "type": "bad_value_type"},
        {"source_type": "path", "type": "string"},  # 缺 target
        {"target": "y", "source_type": "constant", "type": "string"},  # 缺 constant
    ]}
    result = validate_config("mqtt_to_mqtt", cfg)
    assert result["ok"] is False
    reasons = " ".join(e["reason"] for e in result["errors"])
    assert "非法 source_type" in reasons
    assert "非法 type" in reasons
    assert "source_type=constant 时 constant 必填" in reasons
    # 每条错误含路径
    assert all(e["path"] for e in result["errors"])


def test_validate_modbus_missing_read():
    cfg = copy.deepcopy(MODBUS_CONFIG)
    cfg["labelList"] = [{"name": "voltageA"}]  # 缺 read
    result = validate_config("modbus_to_internal", cfg)
    assert result["ok"] is False
    assert any("read 必填" in e["reason"] for e in result["errors"])


def test_validate_modbus_bad_order_and_func():
    cfg = copy.deepcopy(MODBUS_CONFIG)
    cfg["labelList"][0]["read"]["data_order"] = "XX"
    cfg["labelList"][0]["read"]["func_code"] = 6  # 读功能码应为 3/4
    result = validate_config("modbus_to_internal", cfg)
    assert result["ok"] is False
    reasons = " ".join(e["reason"] for e in result["errors"])
    assert "非法字节序" in reasons
    assert "非法功能码" in reasons


def test_validate_unknown_type_and_bad_json():
    assert validate_config("weird_type", {})["ok"] is False
    result = validate_config("mqtt_to_mqtt", "{not json")
    assert result["ok"] is False
    assert "合法 JSON" in result["errors"][0]["reason"]


# ── testdata ──

def test_generate_test_data_mqtt():
    result = generate_test_data("mqtt_to_mqtt", MQTT_CONFIG)
    assert result["ok"] is True
    cases = result["test_cases"]
    names = [c["name"] for c in cases]
    assert names == ["正常数据", "边界数据", "异常数据"]
    assert all(isinstance(c["input"], dict) for c in cases)


def test_generate_test_data_modbus_unsupported():
    result = generate_test_data("modbus_to_internal", MODBUS_CONFIG)
    assert result["ok"] is False
    assert "不支持" in result["error"]


# ── report_store ──

def test_report_store_owner_isolation(tmp_path):
    store = ReportStore(base_dir=tmp_path, ttl_seconds=3600)
    rid = store.save("owner-a", {"total": 1, "passed": 1})
    assert store.get(rid, "owner-a") == {"total": 1, "passed": 1}
    assert store.get(rid, "owner-b") is None  # 越权不存在语义
    assert store.get("nope", "owner-a") is None


def test_report_store_expiry(tmp_path):
    now = {"t": 1000.0}
    store = ReportStore(base_dir=tmp_path, ttl_seconds=10, now_fn=lambda: now["t"])
    rid = store.save("o", {"x": 1})
    now["t"] = 1020.0
    assert store.get(rid, "o") is None


# ── executor（真实镜像引擎沙箱）──

def test_executor_runs_mqtt_transform():
    ex = Executor(ENGINE_DIR)
    assert ex.engine_available() is True
    result = ex.run_case("mqtt", MQTT_CONFIG, {"roadNo": "1", "voltageA": 22.0})
    assert result["ok"] is True
    assert result["output"]["deviceId"] == "1"
    assert result["output"]["value"] == 220.0  # 22.0 * 10


def test_executor_temp_dir_cleaned(monkeypatch):
    created: list[str] = []
    real_mkdtemp = tempfile.mkdtemp

    def _recording_mkdtemp(prefix="", **kw):
        d = real_mkdtemp(prefix=prefix, **kw)
        created.append(d)
        return d

    monkeypatch.setattr("conversion.executor.tempfile.mkdtemp", _recording_mkdtemp)
    ex = Executor(ENGINE_DIR)
    ex.run_case("mqtt", MQTT_CONFIG, {"roadNo": "1"})
    assert created, "未创建临时目录"
    assert not Path(created[-1]).exists(), "临时目录未清理"


def test_executor_missing_engine():
    ex = Executor("/nonexistent/engine/dir")
    assert ex.engine_available() is False
    with pytest.raises(SandboxError, match="引擎不可用"):
        ex.run_case("mqtt", MQTT_CONFIG, {"roadNo": "1"})


def test_executor_bad_mode_and_bad_input():
    ex = Executor(ENGINE_DIR)
    with pytest.raises(SandboxError, match="未知执行模式"):
        ex.run_case("weird", MQTT_CONFIG, {})
    # 输入非 JSON 结构仍可执行（引擎处理 None），但超大请求应拒绝
    with pytest.raises(SandboxError, match="上限"):
        ex.run_case("mqtt", MQTT_CONFIG, {"roadNo": "x" * (2 * 1024 * 1024)})


# ── conversion_tools（6 工具经 stub mcp 捕获）──

class _StubMCP:
    def __init__(self):
        self.tools = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


@pytest.fixture
def tools(tmp_path, monkeypatch):
    """构造带 tmp 存储 + 真实引擎的 6 工具。"""
    ct._artifact_store = SnapshotStore(base_dir=tmp_path / "artifacts")
    ct._report_store = ReportStore(base_dir=tmp_path / "reports", ttl_seconds=3600)
    ct._executor = Executor(ENGINE_DIR)
    token = mcp_token_var.set("test-mcp-token")
    stub = _StubMCP()
    ct.register_conversion_tools(stub)
    yield stub.tools
    mcp_token_var.reset(token)


def test_validate_tool(tools):
    result = tools["validate_config_format"]("mqtt_to_mqtt", MQTT_CONFIG)
    assert result["ok"] is True


def test_execute_and_get_report_tools(tools):
    cases = [
        {"name": "正确", "input": {"roadNo": "1", "voltageA": 22.0},
         "expected": {"deviceId": "1", "value": 220.0}},
        {"name": "错误", "input": {"roadNo": "1", "voltageA": 22.0},
         "expected": {"deviceId": "1", "value": 999.0}},
    ]
    result = tools["execute_conversion_test"]("mqtt_to_mqtt", MQTT_CONFIG, cases)
    assert result["ok"] is True
    assert result["passed"] == 1 and result["failed"] == 1
    assert result["test_run_id"]
    # 按 test_run_id 可查
    fetched = tools["get_test_report"](result["test_run_id"])
    assert fetched["ok"] is True
    assert fetched["passed"] == 1 and fetched["failed"] == 1


def test_execute_rejects_invalid_config(tools):
    result = tools["execute_conversion_test"]("mqtt_to_mqtt", {"bad": 1}, None)
    assert result["ok"] is False
    assert "配置校验未通过" in result["message"]


def test_execute_modbus_rejected(tools):
    result = tools["execute_conversion_test"]("modbus_to_internal", MODBUS_CONFIG, [])
    assert result["ok"] is False
    assert "不支持" in result["message"]


def test_save_config_tool(tools):
    result = tools["save_conversion_config"]("mqtt_to_mqtt", MQTT_CONFIG, "my-config")
    assert result["ok"] is True
    assert result["file_id"] and result["download_url"]
    # 取回内容一致
    store = ct._artifact_store
    owner = result["download_url"].split("owner=")[1]
    record = store.load(result["file_id"], owner_id=owner)
    payload = store.read_template_bytes(result["file_id"], owner_id=owner)
    assert json.loads(payload.decode("utf-8")) == MQTT_CONFIG
    assert record.template_name == "my-config.json"


def test_save_config_rejects_invalid(tools):
    result = tools["save_conversion_config"]("mqtt_to_mqtt", {"bad": 1}, "x")
    assert result["ok"] is False
    assert "配置校验未通过" in result["message"]


def test_pack_bundle_gate_and_zip(tools):
    # 未通过 → 拒绝
    failing = tools["pack_bundle"](
        "p1", MQTT_CONFIG, {"status": "failed"}, mapping_report_md="# m")
    assert failing["ok"] is False
    assert "禁止打包" in failing["message"]

    report = {"status": "passed", "total": 3, "passed": 3, "testSummary": "3/3 通过"}
    result = tools["pack_bundle"](
        "p1", MQTT_CONFIG, report, mapping_report_md="# 映射报告",
        source_spec_json={"a": 1}, target_spec_json={"b": 2})
    assert result["ok"] is True
    assert result["manifest"]["testStatus"] == "passed"

    # 下载 ZIP 解包校验结构与 SHA256
    owner = result["download_url"].split("owner=")[1]
    zbytes = ct._artifact_store.read_template_bytes(result["file_id"], owner_id=owner)
    with zipfile.ZipFile(__import__("io").BytesIO(zbytes)) as zf:
        names = set(zf.namelist())
        assert {"config.json", "mapping_report.md", "test_report.json",
                "README.md", "manifest.json", "source_protocol_spec.json",
                "target_protocol_spec.json"} <= names
        # manifest SHA256 与实际一致
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        by_name = {f["name"]: f["checksum"] for f in manifest["files"]}
        import hashlib
        assert by_name["config.json"] == "sha256:" + hashlib.sha256(
            zf.read("config.json")).hexdigest()


def test_pack_readme_placeholder_extraction(tools):
    cfg = copy.deepcopy(MQTT_CONFIG)
    cfg["mappings"].append({"target": "devId", "source_type": "constant",
                            "type": "substitute", "constant": "$ssl_mqtt_server.gatewayID$"})
    report = {"status": "passed", "total": 0, "passed": 0}
    result = tools["pack_bundle"]("p2", cfg, report)
    assert result["ok"] is True
    owner = result["download_url"].split("owner=")[1]
    zbytes = ct._artifact_store.read_template_bytes(result["file_id"], owner_id=owner)
    with zipfile.ZipFile(__import__("io").BytesIO(zbytes)) as zf:
        readme = zf.read("README.md").decode("utf-8")
    assert "ssl_mqtt_server" in readme


def test_no_owner_errors(tools):
    # 无 token 时产物类工具明确报错
    token = mcp_token_var.set("")
    try:
        assert tools["save_conversion_config"]("mqtt_to_mqtt", MQTT_CONFIG, "x")["ok"] is False
        assert tools["get_test_report"]("nope")["ok"] is False
    finally:
        mcp_token_var.reset(token)
