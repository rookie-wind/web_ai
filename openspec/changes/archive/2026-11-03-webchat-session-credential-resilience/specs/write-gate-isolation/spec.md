# write-gate-isolation Delta

## MODIFIED Requirements

### Requirement: 写入类操作必须持有计划域授权票据才可执行

系统 MUST 对写入类工具调用（`server.py` 注册表 `type ∈ {write, edge_write}`
全集：云端写工具与边缘写工具）实施服务端验票：仅当存在该会话针对**同一
目标**（plan_id/task_id 或 tool_name）的**有效** grant 时才允许执行。grant
为**计划域窗口语义**：在 TTL 窗口内可被同一目标的多次调用复用（覆盖分批
续跑与逐台写序列），一次确认覆盖整个已确认计划。grant 采用**滑动消费**：
Hook 每次命中放行即把窗口起点顺延一个 TTL，使持续写入的长轮次不因窗口到
期中途被拦（避免确认风暴）；工具执行失败 MUST NOT 退票；一旦停止放行满一个
TTL，窗口过期后同目标写入 MUST 被拒绝并要求重新确认。登录类工具 MUST 被禁用（见"运行时工具面收敛"），只读/探测/
规划类工具与 Skill MUST NOT 要求 grant。

#### Scenario: 无票据时写入被拒

- **WHEN** 模型在未获得用户确认的情况下调用写入类工具
- **THEN** 调用被 deny（Fail-Closed），拒绝原因回传模型，
  会话事件流出现 gate_blocked 事件

#### Scenario: 有效票据窗口内多次放行

- **WHEN** 用户确认后模型以有效 grant 多次调用同一目标的写入工具
  （如 batch/cursor 分批续跑，或共享 active_plan_id 的逐台 edge 写序列）
- **THEN** 窗口内每次调用均放行并滑动续期，无需逐次重新确认
- **THEN** 一旦停止放行超过 TTL（无新命中），同目标写入被 deny，需用户再次确认

#### Scenario: 执行失败不退票

- **WHEN** 一次写入调用被放行但工具执行失败
- **THEN** grant 不因失败而重铸或额外延长（窗口仅在命中放行时滑动续期），防重放窗口

#### Scenario: 只读与规划工具不受门禁影响

- **WHEN** 模型调用只读/探测/规划类工具或 Skill
- **THEN** 不需要 grant，调用行为与门禁无关
