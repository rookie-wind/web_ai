"""配电房监测点 profile（deviceTypeId=100024）。

复用 XLBA 建档结构（同一 20 列契约与派生规则，各自占用独立 `监测点·配电房` sheet），
差异仅两点：

- 类型标识：device_type=「配电房」、deviceTypeId=100024（10.0.17.23 实测建档成功）。
- 下发/召测为通用能力：执行时实时读后端当前参数，不区分类型；
  authParam 端口驱动组装由基类共享逻辑承载。
"""

from __future__ import annotations

__all__ = ["MeterPdbProfile"]

from .base import METER_PDB_TYPE_ID
from .meter_xlba import MeterXlbaProfile


class MeterPdbProfile(MeterXlbaProfile):
    """配电房监测点（deviceTypeId=100024）建档 profile。

    建档/校验逻辑完全继承 XLBA；下发/召测与其它监测点类型同路径
    执行（实时读后端当前参数），无类型级能力开关。
    """

    device_type = "配电房"
    device_type_id = METER_PDB_TYPE_ID
    profile_name = "meter_pdb"
    # 在线判定走感知事件（getSmartEventData），非运维召测。
    online_check_method = "smart_event"
