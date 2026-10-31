#!/usr/bin/env python3
"""沙箱执行入口：stdin 收 ``{mode, config, input}``，stdout 回 ``{ok, output|error}``。

固定代码 + 不可信数据模型：
- 加载的引擎是分发源只读母本 ``protocol_converter.py``（引擎目录经环境变量
  ``CONVERSION_ENGINE_DIR`` 注入，避免命令行拼接）；
- 输入仅作为 JSON 数据进入（config / input），不执行任何用户代码；
- 不写文件、不解释 shell、不访问网络。
"""

from __future__ import annotations

import json
import os
import sys

ENGINE_DIR = os.getenv("CONVERSION_ENGINE_DIR", "")


def _emit(ok: bool, error: str | None = None, output=None) -> None:
    """向 stdout 写单行 JSON 结果。"""
    payload: dict = {"ok": ok}
    if error is not None:
        payload["error"] = error
    if output is not None:
        payload["output"] = output
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))


def _load_engine():
    """加载分发源镜像引擎，返回 MapperCore。"""
    if not ENGINE_DIR:
        raise RuntimeError("CONVERSION_ENGINE_DIR 未设置")
    sys.path.insert(0, ENGINE_DIR)
    try:
        import protocol_converter
    except Exception as exc:  # noqa: BLE001 - 引擎缺失/导入失败
        raise RuntimeError(f"引擎不可用: {type(exc).__name__}: {exc}") from exc
    return protocol_converter.MapperCore


def main() -> int:
    """入口：解析请求、执行、返回结构化结果。"""
    try:
        raw = sys.stdin.read()
        request = json.loads(raw)
    except Exception as exc:  # noqa: BLE001 - 输入非 JSON
        _emit(False, f"输入解析失败: {exc}")
        return 1

    mode = request.get("mode", "")
    config = request.get("config")
    source = request.get("input")

    try:
        core = _load_engine()
        if mode == "mqtt":
            output = core.transform_mqtt(source, config)
        elif mode == "http":
            output = core.transform_http(source, config)
        else:
            _emit(False, f"未知执行模式: {mode}")
            return 2
        _emit(True, None, output)
        return 0
    except Exception as exc:  # noqa: BLE001 - 执行失败结构化返回
        _emit(False, f"{type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
