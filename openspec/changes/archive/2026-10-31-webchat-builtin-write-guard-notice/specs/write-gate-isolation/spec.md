# write-gate-isolation Delta

## MODIFIED Requirements

### Requirement: 门禁拒绝必须入会话事件流

每次门禁 deny MUST 以 `gate_blocked` 事件写入该会话的事件流（持久化，
payload 含 tool_name、目标提示与**"是否可经确认解除"标记**），供前端渲染
提示与断线后回看。对"自纠错型"的内置写入路径/扩展名护栏拒绝，payload MUST
额外携带可选字段 `guard`（值为 `builtin_write_path`）；其他拒绝（平台写入、
`login` 绝对禁止、`edge_get_token` 需确认）MUST NOT 携带该字段。前端 MUST 据
该字段区分展示层级：携带 `guard=builtin_write_path` 的拒绝 MUST 渲染为弱提示
（说明已拦截一次路径越界、助手会自动改写到产物目录），MUST NOT 渲染为
"策略禁止、无法确认解除"卡片；其余拒绝仍按 `confirmable` 标记渲染：
可经确认解除的呈现"等待用户确认"入口，绝对禁止的 MUST NOT 提供确认入口，
改为明示该操作被策略禁止、无法通过确认解除，杜绝确认空操作。

#### Scenario: 断线后仍可见门禁记录

- **WHEN** 用户在 gate_blocked 事件产生后重连会话
- **THEN** 历史回放中包含该 gate_blocked 事件

#### Scenario: 绝对禁止的拒绝不提供确认入口

- **WHEN** 一次针对 `login` 的绝对禁止拒绝产生 gate_blocked 事件
- **THEN** 前端渲染为不可确认的禁止提示，不出现"确认写入"按钮

#### Scenario: 需确认的拒绝提供确认入口

- **WHEN** 一次针对 `edge_get_token` 或写入类工具的拒绝产生 gate_blocked
  事件
- **THEN** 前端渲染"等待用户确认"入口，用户确认经 confirm 端点铸票

#### Scenario: 内置写入路径护栏弱化展示

- **WHEN** 模型把文档写到 `xlpa-output/` 之外，门禁产生带
  `guard=builtin_write_path` 的 gate_blocked 事件
- **THEN** 前端只渲染一行弱提示（可聚合计数），不出现"操作被禁止、无法确认解除"卡片
- **THEN** 事件与审计仍完整落盘，可回放查看
