"""测试输入生成：从映射结构推导 normal/boundary/abnormal 三组输入。

仅支持 MQTT / HTTP（镜像引擎覆盖方向）；Modbus 返回明确不支持。
输出可直接作为 ``execute_conversion_test`` 的 test_cases 输入。
"""

from __future__ import annotations

__all__ = ["generate_test_data"]

from typing import Any

_SAMPLE_BY_TYPE = {
    "string": "样例文本",
    "double": 12.5,
    "int": 42,
    "long": 1700000000,
    "bool": True,
}


def _collect_sources(config: dict, conversion_type: str) -> list[str]:
    """从映射结构收集源路径列表（去重保序）。"""
    sources: list[str] = []

    def _scan_rules(rules: list) -> None:
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            src = rule.get("source")
            if isinstance(src, str) and src and src != ".":
                sources.append(src)
            subs = rule.get("sub_mappings")
            if isinstance(subs, list):
                _scan_rules(subs)

    if conversion_type in ("mqtt_to_mqtt", "mqtt"):
        mappings = config.get("mappings", [])
        _scan_rules(mappings if isinstance(mappings, list) else [])
    elif conversion_type in ("http_to_mqtt", "http"):
        for api in (config.get("apis", []) if isinstance(config.get("apis"), list) else []):
            dm = api.get("data_mappings") if isinstance(api, dict) else None
            _scan_rules(dm if isinstance(dm, list) else [])
    seen: list[str] = []
    for s in sources:
        if s not in seen:
            seen.append(s)
    return seen


def _set_path(root: dict, path: str, value: Any) -> None:
    """按点路径（忽略 [index]/[*]）在 root 上设置值。"""
    parts = [p for p in path.replace("[*]", "").split(".") if p and not p.startswith("[")]
    current = root
    for part in parts[:-1]:
        # 去掉可能残留的 [n] 后缀
        key = part.split("[")[0]
        if not isinstance(current.get(key), dict):
            current[key] = {}
        current = current[key]
    if parts:
        current[parts[-1].split("[")[0]] = value


def _build_input(sources: list[str], kind: str) -> dict:
    """按 kind 生成输入对象。"""
    root: dict = {}
    for idx, src in enumerate(sources):
        leaf = src.split(".")[-1].split("[")[0]
        if kind == "normal":
            value = _SAMPLE_BY_TYPE.get(leaf, _SAMPLE_BY_TYPE[("string", "double", "int")[idx % 3]])
        elif kind == "boundary":
            value = ["", 0, -1, 1 << 32][idx % 4]
        else:  # abnormal：类型错位
            value = {True: "not-a-number", False: None}[idx % 2 == 0]
        _set_path(root, src, value)
    return root


def generate_test_data(conversion_type: str, config_json: Any) -> dict:
    """生成三组测试输入。

    Returns:
        ``{ok, conversion_type, test_cases}`` 或 ``{ok: False, error}``。
    """
    if conversion_type not in ("mqtt_to_mqtt", "mqtt", "http_to_mqtt", "http"):
        return {
            "ok": False, "conversion_type": conversion_type,
            "error": "不支持该方向（generate_test_data 仅支持 MQTT→MQTT 与 HTTP→MQTT）",
        }
    if not isinstance(config_json, dict):
        return {"ok": False, "conversion_type": conversion_type, "error": "配置必须是对象"}

    sources = _collect_sources(config_json, conversion_type)
    if not sources:
        return {
            "ok": False, "conversion_type": conversion_type,
            "error": "配置未发现可推导的 source 路径，无法生成测试数据",
        }
    test_cases = []
    for kind, label in (("normal", "正常数据"), ("boundary", "边界数据"), ("abnormal", "异常数据")):
        test_cases.append({
            "name": label,
            "input": _build_input(sources, kind),
        })
    return {"ok": True, "conversion_type": conversion_type, "test_cases": test_cases}
