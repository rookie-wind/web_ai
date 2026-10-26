"""设备类型 profile 插件包。

- ``base``：profile 基类、ProfileResult 与 deviceTypeId / itemId 常量。
- ``registry``：按设备类型名或 deviceTypeId 查表，含虚拟网关二期占位。
- ``gateway_8163``：8163 网关 profile（deviceTypeId=100009）。
- ``meter_xlba``：XLBA 电表 profile（deviceTypeId=100019，itemId=20200002）。
- ``meter_lighting``：照明监测点 profile（deviceTypeId=100023，仅建档+参数保存）。
- ``meter_pdb``：配电房监测点 profile（deviceTypeId=100024，仅建档+参数保存）。

新增设备类型时在此包内扩展 profile 并注册到 registry，不改引擎。
"""

from __future__ import annotations

__all__ = [
    "base",
    "registry",
    "gateway_8163",
    "meter_xlba",
    "meter_lighting",
    "meter_pdb",
    "default_registry",
    "ProfileRegistry",
]

from .registry import ProfileRegistry, default_registry
