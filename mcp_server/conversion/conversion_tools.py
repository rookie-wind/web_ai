"""6 个 exec 类 MCP 工具：配置校验、测试数据、沙箱执行、报告查询、保存、打包。

鉴权口径：工具不要求业务登录（不调 ``_require_session``），接入鉴权由
AuthMiddleware 的 Bearer 校验承担；产物归属取 ``derive_owner_id(mcp_token)``。
exec 类工具不属云端写、不属边缘写，webchat 写入门禁按 type 归为放行。

产物（配置/ZIP）复用 snapshot_store 语义（owner 隔离 + 30 天 TTL + file_id
即票据下载端点）；测试报告经 report_store（owner 隔离 + 7 天 TTL）。
"""

from __future__ import annotations

__all__ = ["register_conversion_tools", "conversion_engine_available"]

import hashlib
import io
import json
import os
import re
import zipfile
from typing import Any

from archiving.models import TemplateSnapshot
from archiving.snapshot_store import SnapshotStore, derive_owner_id
from session import mcp_token_var

from .executor import Executor, SandboxError
from .report_store import ReportStore
from .testdata import generate_test_data as _generate_test_data
from .validator import validate_config

# 引擎目录（分发源只读母本）；由 server 注入，缺省按仓库布局推导。
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_ENGINE_DIR = os.path.join(
    _PROJECT_ROOT, "agent_assets", "skills", "protocol-conversion", "scripts"
)

_executor: Executor | None = None
_report_store: ReportStore | None = None
_artifact_store: SnapshotStore | None = None
_engine_dir: str = os.getenv("CONVERSION_ENGINE_DIR", DEFAULT_ENGINE_DIR)

_MODE_BY_TYPE = {"mqtt_to_mqtt": "mqtt", "mqtt": "mqtt", "http_to_mqtt": "http", "http": "http"}

MAX_CASES = 50
_MAX_STDOUT_SUMMARY = 500


def _init_executor() -> Executor:
    global _executor
    if _executor is None:
        _executor = Executor(_engine_dir)
    return _executor


def _init_report_store() -> ReportStore:
    global _report_store
    if _report_store is None:
        _report_store = ReportStore()
    return _report_store


def _init_artifact_store() -> SnapshotStore:
    global _artifact_store
    if _artifact_store is None:
        _artifact_store = SnapshotStore()
    return _artifact_store


def conversion_engine_available() -> bool:
    """启动校验：分发源引擎文件是否可用。"""
    return _init_executor().engine_available()


def _current_owner_id() -> str:
    """从当前 MCP 接入 Token 派生归属摘要；无 token 返回空串。"""
    return derive_owner_id(mcp_token_var.get(""))


def _err(message: str, **extra) -> dict:
    payload: dict = {"ok": False, "error": True, "message": message}
    payload.update(extra)
    return payload


def _deep_equal(a: Any, b: Any) -> bool:
    """深度对比（含类型）：数字 1 与字符串 "1" 不相等。"""
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_deep_equal(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(_deep_equal(x, y) for x, y in zip(a, b))
    return a == b


def _diff_reason(actual: Any, expected: Any) -> str:
    """生成差异说明（失败 case 用）。"""
    if type(actual) is not type(expected):
        return f"类型不一致：实际 {type(actual).__name__}，期望 {type(expected).__name__}"
    if isinstance(expected, dict):
        keys_missing = [k for k in expected if k not in (actual or {})]
        if keys_missing:
            return f"缺少字段: {keys_missing[:10]}"
        return f"字段值不一致: {list(expected.keys())[:10]}"
    if isinstance(expected, list):
        return f"数组长度不一致：实际 {len(actual) if isinstance(actual, list) else '?'}，期望 {len(expected)}"
    return f"值不一致：实际 {actual!r}，期望 {expected!r}"


def register_conversion_tools(mcp) -> None:
    """将 6 个 exec 类工具注册到 FastMCP 实例。"""

    @mcp.tool()
    def validate_config_format(conversion_type: str, config: dict) -> dict:
        """校验转换配置 JSON 结构（不执行配置）。

        支持 MQTT（platform_name+mappings[]）、HTTP（base_url+token{}+apis[]）、
        Modbus（prtlType/modelNum/classNum/taskList/labelList）三种契约。

        Args:
            conversion_type: 转换方向 mqtt_to_mqtt / http_to_mqtt / modbus_to_internal
            config: 待校验的配置对象
        """
        return validate_config(conversion_type, config)

    @mcp.tool()
    def generate_test_data(conversion_type: str, config: dict) -> dict:
        """根据映射结构生成 normal/boundary/abnormal 三组测试输入。

        仅支持 MQTT→MQTT 与 HTTP→MQTT；Modbus 不支持。

        Args:
            conversion_type: 转换方向
            config: 转换配置对象
        """
        return _generate_test_data(conversion_type, config)

    @mcp.tool()
    def execute_conversion_test(
        conversion_type: str, config: dict, test_cases: list | None = None
    ) -> dict:
        """在沙箱中执行转换测试并返回结构化报告。

        先校验配置（不合法不进沙箱）；逐 case 执行镜像引擎；有 expected 则
        深度对比（含类型）。仅支持 MQTT→MQTT / HTTP→MQTT。

        Args:
            conversion_type: 转换方向
            config: 转换配置对象
            test_cases: 测试用例列表（每项 name/input/expected?）；缺省自动生成
        """
        validation = validate_config(conversion_type, config)
        if not validation.get("ok"):
            return _err("配置校验未通过，未执行测试", validation=validation)

        mode = _MODE_BY_TYPE.get(conversion_type)
        if mode is None:
            return _err(f"沙箱执行不支持该方向: {conversion_type}")

        if test_cases is None:
            generated = _generate_test_data(conversion_type, config)
            if not generated.get("ok"):
                return generated
            test_cases = generated["test_cases"]
        if not isinstance(test_cases, list):
            return _err("test_cases 必须为数组")
        if len(test_cases) > MAX_CASES:
            return _err(f"测试用例数超过上限 {MAX_CASES}")

        executor = _init_executor()
        results: list[dict] = []
        passed = failed = skipped = 0
        for i, case in enumerate(test_cases):
            if not isinstance(case, dict) or not isinstance(case.get("input"), dict):
                results.append({"name": case.get("name", f"case-{i}"),
                                "status": "failed", "reason": "case.input 必须为对象"})
                failed += 1
                continue
            try:
                raw = executor.run_case(mode, config, case["input"])
            except SandboxError as exc:
                results.append({"name": case.get("name", f"case-{i}"),
                                "status": "failed", "reason": str(exc)})
                failed += 1
                continue
            if raw.get("ok"):
                actual = raw.get("output")
                expected = case.get("expected")
                if expected is not None:
                    if _deep_equal(actual, expected):
                        results.append({"name": case.get("name", f"case-{i}"),
                                        "status": "passed", "output": actual})
                        passed += 1
                    else:
                        results.append({"name": case.get("name", f"case-{i}"),
                                        "status": "failed",
                                        "reason": _diff_reason(actual, expected),
                                        "output": actual, "expected": expected})
                        failed += 1
                else:
                    results.append({"name": case.get("name", f"case-{i}"),
                                    "status": "passed", "output": actual})
                    passed += 1
            else:
                results.append({"name": case.get("name", f"case-{i}"),
                                "status": "failed",
                                "reason": raw.get("error", "执行失败")})
                failed += 1

        report = {
            "conversion_type": conversion_type,
            "total": len(results),
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "results": results,
        }
        owner_id = _current_owner_id()
        if not owner_id:
            return _err("无法确定归属身份")
        test_run_id = _init_report_store().save(owner_id, report)
        return {"ok": True, "test_run_id": test_run_id, **report}

    @mcp.tool()
    def get_test_report(test_run_id: str) -> dict:
        """按 test_run_id 查询测试报告（校验归属）。

        Args:
            test_run_id: execute_conversion_test 返回的报告标识
        """
        owner_id = _current_owner_id()
        if not owner_id:
            return _err("无法确定归属身份")
        report = _init_report_store().get(test_run_id, owner_id)
        if report is None:
            return _err("报告不存在或已过期")
        return {"ok": True, "test_run_id": test_run_id, **report}

    @mcp.tool()
    def save_conversion_config(
        conversion_type: str, config: dict, name: str = ""
    ) -> dict:
        """校验并保存转换配置 JSON 到产物存储（30 天 TTL，file_id 即票据）。

        Args:
            conversion_type: 转换方向
            config: 转换配置对象
            name: 产物展示名（缺省自动生成）
        """
        validation = validate_config(conversion_type, config)
        if not validation.get("ok"):
            return _err("配置校验未通过，未保存", validation=validation)
        owner_id = _current_owner_id()
        if not owner_id:
            return _err("无法确定归属身份")
        file_name = (name.strip() or f"conversion_config") + ".json"
        payload = json.dumps(config, ensure_ascii=False).encode("utf-8")
        store = _init_artifact_store()
        try:
            record = store.save(
                TemplateSnapshot(), owner_id=owner_id,
                template_bytes=payload, template_name=file_name,
            )
        except Exception as exc:  # noqa: BLE001
            return _err(f"保存失败: {exc}")
        return {
            "ok": True,
            "file_id": record.snapshot_id,
            "file_name": record.template_name,
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "expires_at": record.expires_at,
            "download_url": f"/api/archive/templates/{record.snapshot_id}?owner={owner_id}",
        }

    @mcp.tool()
    def pack_bundle(
        pack_name: str,
        config: dict,
        test_report_json: dict,
        mapping_report_md: str = "",
        source_spec_json: dict | None = None,
        target_spec_json: dict | None = None,
    ) -> dict:
        """将配置+文档+测试报告打包为 ZIP（测试门控：报告须为 passed）。

        Args:
            pack_name: 包名
            config: 转换配置对象
            test_report_json: 测试报告（status 必须为 passed）
            mapping_report_md: 映射报告 Markdown
            source_spec_json: 源协议规格（可选）
            target_spec_json: 目标协议规格（可选）
        """
        if not isinstance(test_report_json, dict) or test_report_json.get("status") != "passed":
            return _err("测试未通过，禁止打包（需 test_report.status == passed）")
        if not pack_name or not pack_name.strip():
            return _err("pack_name 不能为空")
        owner_id = _current_owner_id()
        if not owner_id:
            return _err("无法确定归属身份")

        config_text = json.dumps(config, ensure_ascii=False, indent=2)
        report_text = json.dumps(test_report_json, ensure_ascii=False, indent=2)
        readme = _build_readme(pack_name, config_text, test_report_json)

        buf = io.BytesIO()
        entries: dict[str, bytes] = {
            "config.json": config_text.encode("utf-8"),
            "mapping_report.md": (mapping_report_md or "（未提供）\n").encode("utf-8"),
            "test_report.json": report_text.encode("utf-8"),
            "README.md": readme.encode("utf-8"),
        }
        if source_spec_json is not None:
            entries["source_protocol_spec.json"] = json.dumps(
                source_spec_json, ensure_ascii=False, indent=2).encode("utf-8")
        if target_spec_json is not None:
            entries["target_protocol_spec.json"] = json.dumps(
                target_spec_json, ensure_ascii=False, indent=2).encode("utf-8")

        manifest_files = []
        for rel, data in entries.items():
            manifest_files.append({
                "name": rel,
                "size": len(data),
                "checksum": "sha256:" + hashlib.sha256(data).hexdigest(),
            })
        manifest = {
            "packId": pack_name.strip(),
            "version": "1.0.0",
            "conversionType": "auto",
            "createdAt": "",  # 由存储时间戳补充
            "files": manifest_files,
            "testStatus": "passed",
        }
        entries["manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")

        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel, data in entries.items():
                zf.writestr(rel, data)
        zip_bytes = buf.getvalue()

        store = _init_artifact_store()
        try:
            record = store.save(
                TemplateSnapshot(), owner_id=owner_id,
                template_bytes=zip_bytes,
                template_name=f"{pack_name.strip()}.zip",
            )
        except Exception as exc:  # noqa: BLE001
            return _err(f"打包保存失败: {exc}")
        return {
            "ok": True,
            "file_id": record.snapshot_id,
            "file_name": record.template_name,
            "size_bytes": len(zip_bytes),
            "sha256": hashlib.sha256(zip_bytes).hexdigest(),
            "manifest": manifest,
            "download_url": f"/api/archive/templates/{record.snapshot_id}?owner={owner_id}",
        }


def _build_readme(pack_name: str, config_text: str, test_report: dict) -> str:
    """生成 README（占位符清单从 config 文本提取）。"""
    placeholders = sorted(set(re.findall(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", config_text)))
    summary = test_report.get("testSummary", "")
    lines = [f"# {pack_name}", "", "## 安装", "1. 将 config.json 复制到 C 引擎配置目录",
             "2. 替换配置中的占位符为实际值", "3. 启动 C 协议转换引擎", "", "## 配置参数"]
    if placeholders:
        lines.append("")
        lines.append("| 占位符 | 说明 | 示例值 |")
        lines.append("|--------|------|--------|")
        for p in placeholders:
            lines.append(f"| {p} | 待填写 | 待填写 |")
    else:
        lines.append("")
        lines.append("（未检测到占位符）")
    lines += ["", "## 测试结果", f"- 状态：{summary or test_report.get('status', '')}",
              f"- 通过：{test_report.get('passed', 0)}/{test_report.get('total', 0)}", ""]
    return "\n".join(lines)
