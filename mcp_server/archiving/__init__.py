"""XLPA 自动建档模块。

采用「引擎 + profile 插件」架构，将边缘建档拆分为可组合的核心对象：

- ``models``：任务配置、拓扑节点、profile 字段、dry-run 计划、
  执行结果、补偿清单，以及版本化字段契约（FieldSpec／CellInput／
  ResolvedField／TemplateSnapshot／TypeSheetSpec）等结构化数据模型。
- ``field_contract``：每类型 sheet 与接口能力的单一事实源，供
  generator／reader／profile／payload／回读共用。
- ``reference_config``：固定参考环境来源配置，不预置任何现场地址。
- ``reference_provider``：参考字典读取提供者，系统 Token 专用云端链
  （绝不回退用户会话）+ 真实边缘签名登录生命周期。
- ``reference_dict``：五类字典标准化、完整分页、品牌型号作用域关联
  与同名异码检测，全有或全无取数。
- ``snapshot_store``：非敏感快照与空白模板的私有存储、归属与
  30 天有效期、规范化内容权威核对。
- ``converter``：条码到通讯地址的转换与校验规则。
- ``excel_reader``：任务级 Excel 模板解析（后续任务实现）。
- ``engine``：dry-run 计划与执行编排（后续任务实现）。
- ``compensation``：补偿清单确认式清理（后续任务实现）。
- ``profiles``：设备类型 profile 插件（后续任务实现）。

边缘后端签名客户端位于同级 ``edge_client`` 模块，与云端规约平台客户端
相互独立。
"""

from __future__ import annotations

__all__ = [
    "models",
    "field_contract",
    "reference_config",
    "reference_provider",
    "reference_dict",
    "snapshot_store",
    "converter",
]
