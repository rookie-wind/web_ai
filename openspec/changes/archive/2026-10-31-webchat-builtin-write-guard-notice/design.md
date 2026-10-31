## Decisions

### D1 事件保留，只调整展示层级

门禁拒绝仍 MUST 写入 `gate_blocked` 事件与审计台账（既有安全契约）；本变更只给
payload 增加可选 `guard` 标识，并要求前端据此区分展示。不得删除或合并事件。

### D2 guard 只在路径护栏拒绝时出现

`_deny` 新增可选 `guard` 参数；仅 `_decide_builtin_write` 的拒绝传入
`guard="builtin_write_path"`。平台写入、`login` 绝对禁止、`edge_get_token`
需确认拒绝均不带该字段，渲染与确认语义保持原样。

### D3 前端聚合，避免连续刷屏

同一会话内多次路径越界只保留一行提示并累加计数；计数状态随会话切换重置。
提示文案明确"助手会自动改写"，不出现"无法确认解除"，避免误导。

### D4 权限回调保持无副作用

`can_use_tool` 的路径校验复用 `check_builtin_write`，不写事件；因此不会产生第二份
`gate_blocked`，前端一行提示对应一次真实拒绝。
