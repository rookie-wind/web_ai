## MODIFIED Requirements

### Requirement: 运行时工具面必须收敛为 MCP 工具且登录类工具禁用

Web 会话实例的内置文件/命令工具面 MUST 保持关闭（C3 `tools=[]`，模型仅见
MCP 工具与已启用 Skill）；本变更 MUST NOT 依赖任何 agent 可写的路径/命令
白名单配置文件。PreToolUse Hook MUST 对云平台业务登录工具 `login` 显式且
**绝对禁止**（deny 不进入票据校验，webchat 会话已持族凭据、禁对话内业务登录
改变会话角色）。对边缘会话开辟工具 `edge_get_token` MUST 实施**需确认放行**：
无有效 grant 时 deny 并要求用户确认，经 confirm 端点铸票后在 TTL 窗口内放行，
其 grant 目标为 `edge_get_token`（与写入类同构的计划域窗口语义）。对任何不在
已知 MCP 工具集内的工具名（内置工具因配置漂移意外出现）MUST 防御性 deny。
路径/命令白名单属 C6 路线 A 范畴，本变更不实现。

#### Scenario: 登录类工具被禁

- **WHEN** 模型在 webchat 会话中调用云平台业务登录 `login`
- **THEN** 调用被 deny（不校验任何 grant），会话事件流出现标记为
  "绝对禁止、不可经确认解除"的 gate_blocked 事件

#### Scenario: 边缘会话开辟无票据时被拒

- **WHEN** 模型在未持有效 grant 的情况下调用 `edge_get_token`
- **THEN** 调用被 deny，事件流出现标记为"需用户确认"的 gate_blocked 事件，
  前端可对该目标发起确认

#### Scenario: 边缘会话开辟经确认后放行

- **WHEN** 用户确认 `edge_get_token` 后模型再次调用该工具
- **THEN** 在 grant 有效期内放行，工具执行并返回 `task_id` 供后续读取类
  `edge_*` 工具使用；窗口过期后同目标再次调用需重新确认

#### Scenario: 未知工具防御性拒绝

- **WHEN** PreToolUse 收到不属于已知 MCP 工具集的工具名
- **THEN** 调用被 deny（Fail-Closed），不放行未知工具面

### Requirement: 授权票据必须由服务端铸造且与用户页面确认绑定

grant MUST 只能由 webchat 后端在用户页面确认动作后铸造（confirm 端点，
需会话票据鉴权且请求者持有写租约）；grant 的覆盖目标（plan_id/task_id、
tool_name 或需确认类工具名）由后端依据当前会话上下文确定，MUST NOT 由模型
请求参数指定；grant 存储 MUST 为服务端内存态（含 TTL 与目标键，不落盘）。
对**绝对禁止类目标**（如 `login`），confirm 端点 MUST NOT 铸造 grant，
MUST 拒绝该确认请求，避免产生永不参与校验的孤儿票据。

#### Scenario: 模型无法自铸票据

- **WHEN** 模型在会话消息中请求为某工具铸造 grant
- **THEN** 不产生任何 grant（铸造仅经 confirm 端点）

#### Scenario: 非租约持有者无法确认

- **WHEN** 不持有写租约的连接调用 confirm 端点
- **THEN** 返回 409，不铸造 grant

#### Scenario: 绝对禁止类目标拒绝铸票

- **WHEN** 对绝对禁止类目标（如 `login`）发起 confirm
- **THEN** 后端拒绝铸造 grant，不产生孤儿票据

### Requirement: 门禁拒绝必须入会话事件流

每次门禁 deny MUST 以 `gate_blocked` 事件写入该会话的事件流（持久化，
payload 含 tool_name、目标提示与**"是否可经确认解除"标记**），供前端渲染
提示与断线后回看。前端 MUST 据该标记区分渲染：可经确认解除的拒绝呈现
"等待用户确认"入口；绝对禁止的拒绝 MUST NOT 提供确认入口，改为明示该操作
被策略禁止、无法通过确认解除，杜绝确认空操作。

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
