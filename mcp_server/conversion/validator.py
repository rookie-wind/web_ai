"""三契约结构校验：MQTT / HTTP / Modbus（纯遍历，不执行配置内容）。

校验只做结构断言，产出结构化错误（每条含路径与原因）。规则来源锁定：
- MQTT/HTTP 映射规则 → `protocol-conversion/SKILL.md` §2/§4/§5；
- Modbus 契约 → `modbus-conversion/SKILL.md`「C 引擎实际读取的配置格式」。
"""

from __future__ import annotations

__all__ = ["validate_config", "VALID_SOURCE_TYPES", "VALID_VALUE_TYPES"]

import json
from typing import Any

VALID_SOURCE_TYPES = {
    "path", "constant", "generated", "array_foreach", "context",
}
VALID_VALUE_TYPES = {
    "string", "double", "int", "long", "bool", "object", "substitute",
}
VALID_ITEM_TYPES = {"object", "key_value"}
VALID_DATA_ORDERS = {"AB", "BA", "ABCD", "DCBA", "BADC", "CDAB"}
VALID_READ_FUNC_CODES = {3, 4}
VALID_WRITE_FUNC_CODES = {6, 16}

MAX_MAPPINGS = 2000  # 防御性上限：防止超大配置拖垮校验


def _errs() -> list[dict]:
    return []


def _add(errors: list[dict], path: str, reason: str, rule_index: int | None = None) -> None:
    entry: dict = {"path": path, "reason": reason}
    if rule_index is not None:
        entry["rule_index"] = rule_index
    errors.append(entry)


def _is_str(value: Any) -> bool:
    return isinstance(value, str)


def _validate_mapping_rule(errors: list[dict], rule: Any, prefix: str, rule_index: int) -> None:
    """校验单条映射规则（protocol-conversion §2 字段契约）。"""
    if not isinstance(rule, dict):
        _add(errors, prefix, "映射规则必须是对象", rule_index)
        return
    for field in ("target", "source_type", "type"):
        if field not in rule or not _is_str(rule.get(field)) or not rule[field].strip():
            _add(errors, f"{prefix}.{field}", "必填字符串字段缺失或为空", rule_index)
    source_type = rule.get("source_type", "")
    value_type = rule.get("type", "")
    if source_type and source_type not in VALID_SOURCE_TYPES:
        _add(errors, f"{prefix}.source_type", f"非法 source_type: {source_type}", rule_index)
    if value_type and value_type not in VALID_VALUE_TYPES:
        _add(errors, f"{prefix}.type", f"非法 type: {value_type}", rule_index)
    if source_type in ("path", "array_foreach"):
        if "source" not in rule:
            _add(errors, f"{prefix}.source", f"source_type={source_type} 时 source 必填", rule_index)
    if source_type == "constant" and "constant" not in rule:
        _add(errors, f"{prefix}.constant", "source_type=constant 时 constant 必填", rule_index)
    if source_type == "generated" and not _is_str(rule.get("generator")):
        _add(errors, f"{prefix}.generator", "source_type=generated 时 generator 必填", rule_index)
    if source_type == "array_foreach":
        item_type = rule.get("item_type")
        if item_type not in VALID_ITEM_TYPES:
            _add(errors, f"{prefix}.item_type", "array_foreach 时 item_type 必填且为 object/key_value", rule_index)
    if "scale" in rule and not isinstance(rule["scale"], (int, float)):
        _add(errors, f"{prefix}.scale", "scale 必须为数值", rule_index)
    if "sub_mappings" in rule:
        subs = rule["sub_mappings"]
        if not isinstance(subs, list):
            _add(errors, f"{prefix}.sub_mappings", "sub_mappings 必须为数组", rule_index)
        else:
            for i, sub in enumerate(subs):
                _validate_mapping_rule(errors, sub, f"{prefix}.sub_mappings[{i}]", rule_index)


def _validate_mqtt(errors: list[dict], config: Any) -> None:
    if not isinstance(config, dict):
        _add(errors, "$", "MQTT 配置必须是对象")
        return
    if not _is_str(config.get("platform_name")) or not config["platform_name"].strip():
        _add(errors, "platform_name", "必填字符串字段缺失或为空")
    mappings = config.get("mappings")
    if not isinstance(mappings, list):
        _add(errors, "mappings", "mappings 必须为数组")
        return
    if len(mappings) > MAX_MAPPINGS:
        _add(errors, "mappings", f"mappings 数量超过上限 {MAX_MAPPINGS}")
        return
    for i, rule in enumerate(mappings):
        _validate_mapping_rule(errors, rule, f"mappings[{i}]", i)


def _validate_http(errors: list[dict], config: Any) -> None:
    if not isinstance(config, dict):
        _add(errors, "$", "HTTP 配置必须是对象")
        return
    if "base_url" not in config or not _is_str(config.get("base_url")):
        _add(errors, "base_url", "必填字符串字段缺失或为空")
    token = config.get("token")
    if token is not None and not isinstance(token, dict):
        _add(errors, "token", "token 必须为对象")
    apis = config.get("apis")
    if not isinstance(apis, list):
        _add(errors, "apis", "apis 必须为数组")
        return
    for ai, api in enumerate(apis):
        if not isinstance(api, dict):
            _add(errors, f"apis[{ai}]", "api 必须是对象")
            continue
        dm = api.get("data_mappings")
        if dm is None:
            continue
        if not isinstance(dm, list):
            _add(errors, f"apis[{ai}].data_mappings", "data_mappings 必须为数组")
            continue
        for i, rule in enumerate(dm):
            _validate_mapping_rule(errors, rule, f"apis[{ai}].data_mappings[{i}]", i)


def _validate_modbus(errors: list[dict], config: Any) -> None:
    if not isinstance(config, dict):
        _add(errors, "$", "Modbus 配置必须是对象")
        return
    for field, typ in (("prtlType", str), ("modelNum", int), ("classNum", int)):
        value = config.get(field)
        if value is None or not isinstance(value, typ):
            _add(errors, field, f"必填 {typ.__name__} 字段缺失或类型错误")
    for field in ("taskList", "labelList"):
        if not isinstance(config.get(field), list):
            _add(errors, field, f"{field} 必须为数组")

    def _check_io(io: Any, path: str, *, is_write: bool) -> None:
        if not isinstance(io, dict):
            _add(errors, path, "read/write 必须是对象")
            return
        if "addr_base" not in io or not isinstance(io.get("addr_base"), int):
            _add(errors, f"{path}.addr_base", "必填 int 字段缺失或类型错误")
        if not _is_str(io.get("data_type")):
            _add(errors, f"{path}.data_type", "必填字符串字段缺失或为空")
        if io.get("data_order") not in VALID_DATA_ORDERS:
            _add(errors, f"{path}.data_order", f"非法字节序: {io.get('data_order')}")
        for f in ("addr_exprs", "data_exprs"):
            if not _is_str(io.get(f)):
                _add(errors, f"{path}.{f}", "必填字符串字段缺失（可为空串）")
        func_code = io.get("func_code")
        valid_codes = VALID_WRITE_FUNC_CODES if is_write else VALID_READ_FUNC_CODES
        if not isinstance(func_code, int) or func_code not in valid_codes:
            _add(errors, f"{path}.func_code", f"非法功能码: {func_code}")

    label_list = config.get("labelList", [])
    for li, label in enumerate(label_list if isinstance(label_list, list) else []):
        if not isinstance(label, dict):
            _add(errors, f"labelList[{li}]", "label 必须是对象")
            continue
        if not _is_str(label.get("name")):
            _add(errors, f"labelList[{li}].name", "必填字符串字段缺失或为空")
        if "read" not in label:
            _add(errors, f"labelList[{li}].read", "read 必填")
        else:
            _check_io(label["read"], f"labelList[{li}].read", is_write=False)
        if "write" in label:
            _check_io(label["write"], f"labelList[{li}].write", is_write=True)


def validate_config(conversion_type: str, config: Any) -> dict:
    """校验配置结构，返回 ``{ok, conversion_type, checked, errors}``。

    不执行配置内容；未知 conversion_type 返回 ok=False 与原因。
    """
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except json.JSONDecodeError as exc:
            return {
                "ok": False, "conversion_type": conversion_type,
                "checked": 0,
                "errors": [{"path": "$", "reason": f"配置不是合法 JSON: {exc}"}],
            }
    errors: list[dict] = []
    if conversion_type in ("mqtt_to_mqtt", "mqtt"):
        _validate_mqtt(errors, config)
    elif conversion_type in ("http_to_mqtt", "http"):
        _validate_http(errors, config)
    elif conversion_type in ("modbus_to_internal", "modbus"):
        _validate_modbus(errors, config)
    else:
        return {
            "ok": False, "conversion_type": conversion_type, "checked": 0,
            "errors": [{"path": "$", "reason": f"未知转换方向: {conversion_type}"}],
        }
    return {
        "ok": not errors,
        "conversion_type": conversion_type,
        "checked": 1,
        "errors": errors,
    }
