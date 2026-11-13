# write-gate-isolation Specification

## Purpose

定义 Web 会话写入门禁与运行时隔离的行为契约：计划域授权票据（grant）的
铸造/消费/窗口过期语义、PreToolUse 验票与 Fail-Closed 拒绝、登录类工具
禁用、建档一键编排入口、门禁事件入流与独立审计台账，以及门禁与工作区的
结构性隔离。运行时工具面收敛为 MCP 工具（C3 已以 `tools=[]` 关闭内置
文件/命令工具，本变更不重建路径白名单——见 design D3）。

**变更四要素**

| 要素 | 内容 |
|---|---|
| 前置条件（含需先验证事项） | 1) C1~C3 已归档（会话运行时与 webchat 族凭据就绪，实例 `tools=[]` 内置工具面为空）；2) V3 已 PASS（PreToolUse 拿到 tool_name+结构化 tool_input、deny 真实阻断）；3) **需补验**：V7——Hook 进程内回调中查询 grant 的时延与正确性（内存直查，探针留证）；4) 写入工具集合来源锁定：`server.py` 注册表中 `type ∈ {write, edge_write}` 全集（云端 `WRITE_TOOLS` 32 + 边缘 10），登录类集合 `{login, edge_get_token}`——均以**符号/type 锚**表述，防漂移单测按 type 解析比对 |
| 要做的事 | grants.py 计划域票据（窗口语义+消费时机）、adapter hooks 注入与验票回调、登录类工具 deny、防御性兜底、confirm 端点、gate_blocked 事件、独立审计 JSONL、建档统一走 execute_archive_task、Fail-Closed 语义、单测 + V7 探针 |
| 通过标准（可执行判据） | 1) webchat pytest 全过：无 grant 调写入工具被 deny、有效 grant 窗口内多次放行（覆盖 batch/逐台序列）、窗口过期后被拒、edge 工具按 plan_id/task_id 验票、登录类工具被 deny、未知/内置工具防御性 deny、只读/规划工具与 Skill 不受影响、gate_blocked 事件入流、审计台账落盘；2) V7 探针留证（时延+正确性+建档闭环一次确认）；3) 主 pytest 基线全绿（mcp_server 零改动）；4) IDE 回归：IDE 会话（无 Hook）行为不变 |
| 执行顺序与依赖 | 依赖 C3（实例与 hooks 挂接点、`tools=[]` 工具面）；C5（产物交付）/C6（转换执行、路线 A 白名单）在本变更之后；前端确认卡片（含参数摘要）属 C7 |

## Requirements

### Requirement: 写入类操作必须持有计划域授权票据才可执行

系统 MUST 对写入类工具调用（`server.py` 注册表 `type ∈ {write, edge_write}`
全集：云端写工具与边缘写工具）实施服务端验票：仅当存在该会话针对**同一
目标**的**有效** grant 时才允许执行。

验票目标 MUST 按"活动 task 作用域优先"推导：一次建档任务在流程中产生
`task_id` 后，凡本次入参携带该 `task_id`（或既有 `plan_id`）的写入，其目标
MUST 归并到该 task 作用域，使一次确认在滑动窗口内覆盖该任务下的全部写入
（含分批续跑与逐台 edge 写）；不携带 `task_id`/`plan_id` 的零星写入 MUST
回退 `tool_name` 粒度，各自需一次确认，MUST NOT 被隐式并入免确认范围。
task 作用域起点为首次产生 `task_id`，终点为新 `task_id` 覆盖或窗口按 TTL
到期回收。

grant 为**计划域窗口语义**：在 TTL 窗口内可被同一目标的多次调用复用，一次
确认覆盖整个已确认作用域。grant 采用**滑动消费**：Hook 每次命中放行即把
窗口起点顺延一个 TTL，使持续写入的长轮次不因窗口到期中途被拦（避免确认
风暴）；工具执行失败 MUST NOT 退票；一旦停止放行满一个 TTL，窗口过期后同
目标写入 MUST 被拒绝并要求重新确认。

授权信号的来源 MUST 有二：登记入参的工具经**参数卡提交**铸票；无需补参的
写入经**会话内口令 `/确认`**铸票。二者都 MUST 先经后端验票语义再放行，
MUST NOT 由模型自授权。登录类工具 MUST 被禁用（见"运行时工具面收敛"），
只读/探测/规划类工具与 Skill MUST NOT 要求 grant。

#### Scenario: 无票据时写入被拒

- **WHEN** 模型在未获得用户确认的情况下调用写入类工具
- **THEN** 调用被 deny（Fail-Closed），拒绝原因回传模型，
  会话事件流出现 gate_blocked 事件

#### Scenario: 有效票据窗口内多次放行

- **WHEN** 用户确认后模型以有效 grant 多次调用同一目标的写入工具
  （如 batch/cursor 分批续跑，或共享 active_plan_id 的逐台 edge 写序列）
- **THEN** 窗口内每次调用均放行并滑动续期，无需逐次重新确认
- **THEN** 一旦停止放行超过 TTL（无新命中），同目标写入被 deny，需用户再次确认

#### Scenario: 同一 task 作用域一次确认覆盖多目标写

- **WHEN** 一次建档任务已产生 `task_id`，用户对首个写入回 `/确认`，随后模型
  以携带同一 `task_id` 的多个不同写工具连续调用
- **THEN** 这些写入在同一滑动窗口内均放行，无需逐一确认

#### Scenario: 不带 task 的零星写回退单目标确认

- **WHEN** 一个不携带 `task_id`/`plan_id` 的写入被拦
- **THEN** 其目标回退 `tool_name` 粒度，需就该目标单独确认一次，MUST NOT 因
  存在其它 task 作用域票据而被隐式放行

#### Scenario: 确认信号来自口令或卡片两途

- **WHEN** 分别经参数卡提交与会话口令 `/确认` 触发铸票
- **THEN** 两条路径均对相应目标铸出有效 grant，其后同目标写入在窗口内放行

#### Scenario: 执行失败不退票

- **WHEN** 一次写入调用被放行但工具执行失败
- **THEN** grant 不因失败而重铸或额外延长（窗口仅在命中放行时滑动续期），防重放窗口

#### Scenario: 只读与规划工具不受门禁影响

- **WHEN** 模型调用只读/探测/规划类工具或 Skill
- **THEN** 不需要 grant，调用行为与门禁无关

### Requirement: 建档执行必须走一键编排入口

webchat 建档执行 MUST 统一走 `execute_archive_task`（单工具、
`stages="all"`、服务端编排全阶段），使一次调用对应一张 plan/task 域 grant
与一次用户确认即覆盖整条建档闭环；分批续跑 MUST 复用同一 grant 窗口，
MUST NOT 因多阶段/多台设备产生逐次确认风暴。

#### Scenario: 一次确认覆盖建档闭环

- **WHEN** 用户确认一个建档计划后模型调用 `execute_archive_task`
  （`stages="all"`）
- **THEN** 该次调用在 grant 窗口内放行，服务端编排完成建档→挂载→参数
  保存→时钟→下发→召测全阶段，无需每阶段/每台重新确认

#### Scenario: 分批续跑复用票据

- **WHEN** 建档以 `batch_size`/`budget` 分批执行并返回 cursor，模型携
  cursor 续跑
- **THEN** 续跑调用复用同一 plan/task 域 grant（窗口内），不触发新确认

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

### Requirement: 门禁必须 Fail-Closed

验票环节的任何异常（存储不可达、内部错误、超时）MUST 拒绝写入调用，
MUST NOT 放行；拒绝路径 MUST 与"无票据"同构（统一 deny 响应），不泄露
内部状态。

#### Scenario: 验票内部异常时拒绝

- **WHEN** Hook 验票回调内部抛出异常
- **THEN** 写入调用被 deny，会话事件流出现 gate_blocked 事件，
  前端可重新确认

### Requirement: 运行时工具面必须收敛为 MCP 工具且登录类工具禁用

Web 会话实例的默认工具面 MUST 收敛为 MCP 工具、已启用 Skill 与受限的外部检索
工具；内置命令工具 `Bash` MUST 保持关闭。内置写入工具（`Write`、`Edit`、
`MultiEdit`、`NotebookEdit`）MUST 仅在同时满足以下条件时放行：

- 工具入参提供非空 `file_path`；
- 该路径经 `resolve()` 解析后位于 `${会话工作区}/xlpa-output/` 目录内；
- 文件扩展名属于文本类文档白名单（`.md`、`.txt`、`.csv`、`.tsv`、`.json`、
  `.jsonl`、`.html`、`.htm`、`.xml`、`.yaml`、`.yml`、`.log`、`.sql`）。

不满足任一条件（含 `..` 目录逃逸、工作区外绝对路径、缺失 `file_path`、
非白名单扩展名、未注入会话工作区）时 MUST 防御性 deny，且该类 deny
`confirmable` MUST 为 false——策略限制不可经用户确认解除。放行与拒绝 MUST 走既有
`gate_blocked` 事件与审计台账。本变更 MUST NOT 依赖任何 agent 可写的路径/命令
白名单配置文件，门禁裁决 MUST 位于 webchat 后端进程内。

内置检索工具 `WebSearch` MUST 被显式放行并记审计；`WebFetch`、读取类、命令类
及其他未登记的内置工具 MUST 保持 deny（不放行服务端 URL 拉取，避免 SSRF 面）。

PreToolUse Hook MUST 对云平台业务登录工具 `login` 显式且**绝对禁止**（deny 不进入
票据校验，webchat 会话已持族凭据、禁对话内业务登录改变会话角色）。对边缘会话开辟
工具 `edge_get_token` MUST 实施**需确认放行**：无有效 grant 时 deny 并要求用户确认，
经 confirm 端点铸票后在 TTL 窗口内放行，其 grant 目标为 `edge_get_token`（与写入类
同构的计划域窗口语义）。对任何不属于已知 MCP 工具集、也不属于上述受限内置写入
放行集与 `WebSearch` 的工具名 MUST 防御性 deny。

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

- **WHEN** PreToolUse 收到不属于已知 MCP 工具集、也不属于受限内置写入放行集
  与 `WebSearch` 的工具名
- **THEN** 调用被 deny（Fail-Closed），不放行未知工具面

#### Scenario: 会话产物目录内文本写入放行

- **WHEN** 模型调用 `Write` 写入 `${会话工作区}/xlpa-output/report.md`
- **THEN** 调用被放行，产物在 turn 收尾被扫描登记并产 `artifact` 事件

#### Scenario: 产物目录外写入被拒

- **WHEN** 模型调用 `Write` 写入 `xlpa-output/../secret.md`、工作区外绝对路径、
  非文本扩展名（如 `.docx`），或未提供 `file_path`
- **THEN** 调用被 deny 且不可经确认解除，事件流出现 `gate_blocked` 记录

#### Scenario: 命令工具仍关闭

- **WHEN** 模型调用 `Bash` 或其他内置命令工具
- **THEN** 调用被 deny（Fail-Closed）

#### Scenario: 网页检索放行且留痕

- **WHEN** 模型调用内置 `WebSearch` 检索公开资料
- **THEN** 调用被放行并写入门禁审计；`WebFetch`、`Bash` 仍被拒绝

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

### Requirement: 门禁决策必须有独立审计台账

每次门禁决策（confirm 铸票、allow 放行、deny 拒绝）MUST 追加写入 webchat
侧独立的门禁审计台账（JSONL），台账 MUST NOT 随会话生命周期清理（会话结束
后仍留存），条目至少含 ts、session_id、target、tool_name、decision、reason，
供验收举证与汇报引用。

#### Scenario: 会话结束后审计仍可查

- **WHEN** 会话结束并被回收
- **THEN** 该会话产生的 confirm/allow/deny 审计条目仍完整留存于台账

### Requirement: 门禁逻辑必须结构性位于工作区之外

门禁与验票逻辑 MUST 完全位于 webchat 后端进程内（SDK 进程内回调），
MUST NOT 以任何配置文件形式落位于会话工作区或 agent 可写目录；agent
MUST NOT 具备放宽门禁的任何途径。

#### Scenario: 工作区内无门禁配置文件

- **WHEN** 检查会话工作区与 agent 可写目录
- **THEN** 不存在任何承载门禁/验票规则的文件
