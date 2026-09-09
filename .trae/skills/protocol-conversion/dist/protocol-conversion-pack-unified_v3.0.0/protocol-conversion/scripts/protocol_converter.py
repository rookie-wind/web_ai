#!/usr/bin/env python3
"""
统一协议映射引擎 — Python 实现

镜像 C 引擎 mapper_core.c 的逻辑，作为 Skill 本地测试和验证工具。
MQTT 引擎 (json_mapper.c) 和 HTTP 引擎 (http_json_mapper.c) 共用此核心。

架构：
  protocol-conversion (共享映射核心) → mapper_core
    ├── mqtt-conversion (MQTT 特有: platform_name + mappings[])
    └── http-conversion (HTTP 特有: base_url + token + apis[])

C 引擎归属：
  MQTT → config_loader.c 加载 → mapper_core 映射
  HTTP → vpp_http_config.load.c 加载 → mapper_core 映射
"""

from __future__ import annotations

import json
import re
import uuid
import time
import hashlib
from typing import Any, Optional


# ============================================================
# 共享映射核心 (镜像 mapper_core.c)
# ============================================================

class MapperCore:
    """
    统一映射核心引擎

    所有函数与 mapper_core.c 一一对应：
      get_value_by_path  → C: get_value_by_path
      ensure_path        → C: ensure_path
      add_value_to_parent→ C: add_value_to_parent
      generate_value     → C: generate_value
      process_rule       → C: process_rule
      process_array_foreach → C: process_array_foreach
      process_normal_field  → C: process_normal_field
      template_substitute   → C: template_substitute
    """

    # --- 路径工具 ---

    @staticmethod
    def get_value_by_path(root: Any, path: str) -> Any:
        """
        按 JSON 路径取值 (合并 MQTT get_value_by_path + HTTP http_get_json_by_path)

        支持: a.b.c / a[0] / a[*] / "." (HTTP: 返回根对象)
        """
        if root is None or not path:
            return None

        # HTTP 特有: "." 返回根对象
        if path == ".":
            return root

        current = root
        parts = path.split(".")

        for part in parts:
            if current is None:
                return None

            # 解析 [index] 或 [*]
            bracket_match = re.match(r'^([a-zA-Z_][a-zA-Z0-9_]*)\[([^\]]*)\]$', part)
            if bracket_match:
                key = bracket_match.group(1)
                index_str = bracket_match.group(2)

                if isinstance(current, dict):
                    current = current.get(key)
                else:
                    return None

                if current is None:
                    return None

                if isinstance(current, list):
                    if index_str == "*":
                        # [*] 返回整个数组
                        return current
                    try:
                        idx = int(index_str)
                        if 0 <= idx < len(current):
                            current = current[idx]
                        else:
                            return None
                    except ValueError:
                        return None
                else:
                    return None
            else:
                if isinstance(current, dict):
                    current = current.get(part)
                else:
                    return None

        return current

    @staticmethod
    def get_string_by_path(root: Any, path: str) -> str | None:
        """按 JSON 路径取字符串值"""
        val = MapperCore.get_value_by_path(root, path)
        if val is None:
            return None
        if isinstance(val, str):
            return val
        if isinstance(val, (int, float)):
            return str(val)
        if isinstance(val, bool):
            return "true" if val else "false"
        return None

    @staticmethod
    def ensure_path(root: dict, path: str) -> dict | list:
        """
        确保路径存在 (两引擎逻辑完全相同)

        与 C: ensure_path / http_ensure_path 一致
        """
        if not path:
            return root

        current = root
        parts = path.split(".")

        for part in parts:
            if not part:
                continue

            bracket_match = re.match(r'^([a-zA-Z_][a-zA-Z0-9_]*)\[([^\]]*)\]$', part)
            if bracket_match:
                key = bracket_match.group(1)
                index_str = bracket_match.group(2)

                if key not in current:
                    current[key] = []
                arr = current[key]

                if not isinstance(arr, list):
                    arr = []
                    current[key] = arr

                idx = int(index_str)
                while len(arr) <= idx:
                    arr.append({})
                current = arr[idx]
            else:
                if part not in current:
                    current[part] = {}
                current = current[part]

        return current

    @staticmethod
    def get_flat_array_from_path(root: Any, path: str) -> list | None:
        """
        获取带 [*] 语法的扁平化数组 (来自 MQTT json_mapper.c)

        支持嵌套: "dataObj.itemBody[*].item[*]"
        """
        if not path or "[*]" not in path:
            val = MapperCore.get_value_by_path(root, path)
            if isinstance(val, list):
                return val
            return None

        # 找到第一个 [*]
        star_pos = path.find("[*]")
        base_path = path[:star_pos]

        # 去掉 base_path 末尾可能的点
        # base_path 已经是不含 [*] 的路径

        base_array = MapperCore.get_value_by_path(root, base_path)
        if not isinstance(base_array, list):
            return None

        # 获取剩余路径
        remaining = path[star_pos + 3:]  # 跳过 "[*]"
        if remaining.startswith("."):
            remaining = remaining[1:]

        if not remaining:
            return base_array

        # 递归展平
        result = []
        for item in base_array:
            sub_array = MapperCore.get_flat_array_from_path(item, remaining)
            if isinstance(sub_array, list):
                result.extend(sub_array)
            elif sub_array is not None:
                result.append(sub_array)

        return result

    # --- 生成器 ---

    @staticmethod
    def generate_value(generator: str, param: Any = None,
                       ctx: dict | None = None, idx: int = -1) -> str:
        """
        生成值 (合并 MQTT generate_value + HTTP http_generate_value)

        支持所有生成器类型
        """
        if generator == "uuid":
            return str(uuid.uuid4())
        elif generator in ("current_timestamp", "timestamp_sec"):
            return str(int(time.time()))
        elif generator in ("current_timestamp_ms", "timestamp_ms"):
            return str(int(time.time() * 1000))
        elif generator == "datetime_compact":
            return time.strftime("%Y%m%d%H%M%S")
        elif generator == "datetime_str":
            return time.strftime("%Y-%m-%d %H:%M:%S")
        elif generator == "random_string":
            return uuid.uuid4().hex[:16]
        elif generator == "md5_sign":
            return hashlib.md5(str(time.time()).encode()).hexdigest()
        elif generator == "batch_id":
            return str(uuid.uuid4())[:8]
        elif generator == "sequence":
            if idx >= 0:
                return str(idx + 1)
            elif ctx is not None:
                ctx["_seq_counter"] = ctx.get("_seq_counter", 0) + 1
                return str(ctx["_seq_counter"])
        return ""

    # --- 模板替换 ---

    @staticmethod
    def template_substitute(template_str: str, ctx: dict | None = None) -> str:
        """
        模板变量替换 $var$ 语法 (来自 MQTT json_mapper.c)

        从 ctx 中查找变量值，支持嵌套路径如 ssl_mqtt_server.gatewayID
        """
        if not template_str:
            return template_str

        def replace_var(match):
            var_name = match.group(1)
            if ctx is None:
                return match.group(0)

            # 支持嵌套路径
            parts = var_name.split(".")
            current = ctx
            for part in parts:
                if isinstance(current, dict):
                    current = current.get(part)
                else:
                    return match.group(0)
            return str(current) if current is not None else match.group(0)

        return re.sub(r'\$([^$]+)\$', replace_var, template_str)

    # --- 类型转换 ---

    @staticmethod
    def add_value_to_parent(parent: dict, field_name: str,
                            source_val: Any, value_type: str,
                            constant: Any = None, scale: float = 1.0,
                            ctx: dict | None = None) -> None:
        """
        将源值按目标类型转换并添加到父对象

        合并 MQTT add_value_to_parent (enum) + HTTP http_add_value_to_parent (string)
        统一用 string 比较，支持全部 7 种类型
        """
        if value_type == "int":
            val = 0
            if constant is not None and str(constant):
                try:
                    val = int(constant)
                except (ValueError, TypeError):
                    val = 0
            elif source_val is not None:
                if isinstance(source_val, (int, float)):
                    val = int(source_val * scale)
                elif isinstance(source_val, str):
                    try:
                        val = int(source_val)
                    except ValueError:
                        val = 0
            parent[field_name] = val

        elif value_type == "double":
            val = 0.0
            if constant is not None and str(constant):
                try:
                    val = float(constant)
                except (ValueError, TypeError):
                    val = 0.0
            elif source_val is not None:
                if isinstance(source_val, (int, float)):
                    val = source_val * scale
                elif isinstance(source_val, str):
                    try:
                        val = float(source_val)
                    except ValueError:
                        val = 0.0
            parent[field_name] = val

        elif value_type == "long":
            val = 0
            if constant is not None and str(constant):
                try:
                    val = int(constant)
                except (ValueError, TypeError):
                    val = 0
            elif source_val is not None:
                if isinstance(source_val, (int, float)):
                    val = int(source_val * scale)
                elif isinstance(source_val, str):
                    try:
                        val = int(source_val)
                    except ValueError:
                        val = 0
            parent[field_name] = val

        elif value_type == "bool":
            val = False
            if constant is not None and str(constant):
                val = str(constant).lower() in ("true", "1")
            elif source_val is not None:
                if isinstance(source_val, bool):
                    val = source_val
                elif isinstance(source_val, (int, float)):
                    val = source_val != 0
                elif isinstance(source_val, str):
                    val = source_val.lower() in ("true", "1")
            parent[field_name] = val

        elif value_type == "object":
            # MQTT 特有: 对象类型
            if source_val is not None and isinstance(source_val, dict):
                parent[field_name] = json.loads(json.dumps(source_val))
            elif constant is not None and str(constant):
                try:
                    parent[field_name] = json.loads(constant) if isinstance(constant, str) else constant
                except (json.JSONDecodeError, TypeError):
                    parent[field_name] = {}
            else:
                parent[field_name] = {}

        elif value_type == "substitute":
            # MQTT 特有: 模板替换
            if constant is not None and ctx is not None:
                substituted = MapperCore.template_substitute(str(constant), ctx)
                parent[field_name] = substituted

        else:  # string (默认)
            str_val = None
            if constant is not None:
                str_val = str(constant)
            elif source_val is not None:
                if isinstance(source_val, str):
                    str_val = source_val
                elif isinstance(source_val, bool):
                    str_val = "true" if source_val else "false"
                elif isinstance(source_val, (int, float)):
                    str_val = str(source_val)

            if str_val and len(str_val) > 0:
                parent[field_name] = str_val

    # --- 映射处理核心 ---

    @classmethod
    def process_rule(cls, target: dict, source: Any, rule: dict,
                     ctx: dict | None = None,
                     current_array_item: Any = None) -> None:
        """
        处理单条映射规则 (统一入口, 对应 C: process_rule)

        合并 MQTT process_rule + HTTP http_process_rule
        """
        source_type = rule.get("source_type", "path")

        if source_type == "array_foreach" or rule.get("is_array_foreach"):
            cls.process_array_foreach(target, source, rule, ctx)
        else:
            cls.process_normal_field(target, source, rule, ctx, current_array_item)

    @classmethod
    def process_array_foreach(cls, target: dict, source: Any,
                              rule: dict, ctx: dict | None = None) -> None:
        """
        处理数组遍历规则 (对应 C: process_array_foreach)

        合并 MQTT + HTTP 逻辑:
          - $idx 变量替换 (MQTT)
          - item_type: object / key_value (HTTP)
          - "." 源路径 (HTTP)
          - 嵌套 [*] 展平 (MQTT)
        """
        src_path = rule.get("source", "")
        sub_mappings = rule.get("sub_mappings", [])
        item_type = rule.get("item_type", "object")

        # 1. 获取源数组
        need_free = False
        if src_path == ".":
            # HTTP 特有: "." 表示当前 source 作为单元素数组
            source_array = [source] if not isinstance(source, list) else source
        elif "[*]" in src_path and src_path.count("[*]") > 1:
            # MQTT 特有: 嵌套 [*] 展平
            source_array = cls.get_flat_array_from_path(source, src_path)
        else:
            source_array = cls.get_value_by_path(source, src_path)

        if not isinstance(source_array, list):
            return

        if len(source_array) == 0:
            return

        # 2. 解析 target 中的 @ 锚点
        target_path = rule["target"]
        at_pos = target_path.find("@")

        if at_pos == -1:
            return

        parent_path = target_path[:at_pos].rstrip(".")

        # 3. 确定数组字段名和父对象
        if "." in parent_path:
            last_dot = parent_path.rfind(".")
            array_field = parent_path[last_dot + 1:]
            grand_parent_path = parent_path[:last_dot]
            grand_parent = cls.ensure_path(target, grand_parent_path) if grand_parent_path else target
        elif parent_path:
            array_field = parent_path
            grand_parent = target
        else:
            array_field = ""
            grand_parent = target

        if not array_field:
            return

        # 4. 遍历源数组
        target_array = []

        for i, src_item in enumerate(source_array):
            if item_type == "object":
                target_item = {}

            for sub_rule in sub_mappings:
                # MQTT 特有: $idx 变量替换
                sub_rule_copy = dict(sub_rule)
                if sub_rule_copy.get("source", "") == "$idx":
                    sub_rule_copy["source"] = str(i)

                if item_type == "key_value":
                    target_item = {}

                cls.process_rule(target_item, src_item, sub_rule_copy, ctx, src_item)

                if item_type == "key_value":
                    target_array.append(target_item)

            if item_type == "object":
                target_array.append(target_item)

        # 5. 添加到父对象
        grand_parent[array_field] = target_array

    @classmethod
    def process_normal_field(cls, target: dict, source: Any, rule: dict,
                             ctx: dict | None = None,
                             current_array_item: Any = None) -> None:
        """
        处理普通字段规则 (对应 C: process_normal_field)

        合并 MQTT + HTTP 逻辑:
          - $item 替换 (MQTT)
          - context source_type (HTTP)
          - post_process (MQTT)
          - object + sub_mappings 递归 (MQTT)
        """
        target_path = rule["target"]

        # 解析目标路径
        last_dot = target_path.rfind(".")
        if last_dot != -1:
            parent_path = target_path[:last_dot]
            field_name = target_path[last_dot + 1:]
            parent = cls.ensure_path(target, parent_path)
        else:
            field_name = target_path
            parent = target

        if not isinstance(parent, dict):
            return

        value_type = rule.get("type", "string")
        source_type = rule.get("source_type", "path")

        # MQTT 特有: object + sub_mappings 时先获取 source_val 再递归
        if value_type == "object" and rule.get("sub_mappings"):
            obj = {}

            source_val = None
            if source_type == "path":
                src_path = rule.get("source", "")
                if current_array_item is not None and "$item" in src_path:
                    after_item = src_path.split("$item", 1)[1]
                    if after_item.startswith("."):
                        after_item = after_item[1:]
                    source_val = cls.get_value_by_path(current_array_item, after_item)
                else:
                    source_val = cls.get_value_by_path(source, src_path)

            for sub_rule in rule["sub_mappings"]:
                cls.process_rule(obj, source_val if source_val else source, sub_rule, ctx, current_array_item)

            parent[field_name] = obj
            return

        # 根据 source_type 获取值
        source_val = None
        constant_val = None

        if source_type == "constant":
            constant_val = rule.get("constant")
        elif source_type == "generated":
            gen = rule.get("generator")
            if gen:
                constant_val = cls.generate_value(gen, rule.get("generator_param"), ctx, -1)
        elif source_type == "path":
            src_path = rule.get("source", "")

            # MQTT 特有: $item 替换
            if current_array_item is not None and "$item" in src_path:
                after_item = src_path.split("$item", 1)[1]
                if after_item.startswith("."):
                    after_item = after_item[1:]
                source_val = cls.get_value_by_path(current_array_item, after_item)
            else:
                source_val = cls.get_value_by_path(source, src_path)

        elif source_type == "context":
            # HTTP 特有: context source_type
            src_path = rule.get("source", "")
            source_val = cls.get_value_by_path(ctx, src_path) if ctx else None

        elif source_type == "substitute":
            # MQTT 特有: substitute
            constant_val = rule.get("constant")

        scale = rule.get("scale", 1.0)
        cls.add_value_to_parent(parent, field_name, source_val, value_type,
                                constant_val, scale, ctx)

    # --- 引擎入口 ---

    @classmethod
    def transform_mqtt(cls, source_json: dict, config: dict,
                        ctx: dict | None = None) -> dict:
        """
        MQTT 引擎入口 (对应 C: transform_json)

        config 格式: { platform_name, mappings[] }
        """
        target = {}
        context = ctx or {}

        for rule in config.get("mappings", []):
            cls.process_rule(target, source_json, rule, context)

        return target

    @classmethod
    def transform_http(cls, source_json: dict, config: dict,
                        ctx: dict | None = None) -> dict:
        """
        HTTP 引擎入口 (对应 C: http_json_mapper 执行)

        config 格式: { base_url, token{}, apis[] }
        只执行 data_mappings，body_params/headers 等由 HTTP 业务层处理
        """
        target = {}
        context = ctx or {}

        for api in config.get("apis", []):
            for rule in api.get("data_mappings", []):
                cls.process_rule(target, source_json, rule, context)

        return target
