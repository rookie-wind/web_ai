# agent-runtime-session Delta

## ADDED Requirements

### Requirement: 会话运行时必须持有一个持久 SDK 客户端

每个 Web 会话 MUST 绑定恰好一个持久的 `QoderSDKClient` 实例：会话创建时
`connect()`，会话结束或空闲回收时 `disconnect()`；同一会话的多个轮次 MUST
复用同一客户端，MUST NOT 每轮重新拉起 CLI 进程。客户端 MUST 在其 `connect()`
所在的同一 asyncio 上下文内使用；MUST NOT 跨事件循环或跨任务组共享。客户端实例
MUST 限于适配层内，MUST NOT 泄漏到事件契约或前端接口。

#### Scenario: 多轮复用同一客户端

- **WHEN** 同一会话连续执行两轮用户消息
- **THEN** 两轮由同一客户端实例处理，第二轮的 `session_id` 与第一轮一致
- **THEN** 不出现每轮新建 CLI 子进程的行为

#### Scenario: 会话结束释放客户端

- **WHEN** 用户结束会话或会话被空闲回收
- **THEN** 该客户端 `disconnect()`，CLI 实例终止，接入凭据按既有契约撤销

### Requirement: 每会话必须只有一个消息接收循环

每个客户端 MUST 只启动一个常驻 `receive_messages()` 接收循环，跨轮持续接收；
轮次逻辑 MUST NOT 自行新建第二个接收循环。接收循环 MUST 把消息按本轮归属归类后
再归一化为事件契约 v1，MUST NOT 把上一轮尾部消息计入下一轮。接收循环异常退出
MUST 产生 `error` 事件并使该会话进入明确的不可继续状态，MUST NOT 静默丢弃消息。

#### Scenario: 单接收循环跨两轮

- **WHEN** 同一会话依次发送两条消息
- **THEN** 一个接收循环连续消费两轮消息，两轮各自的 `turn_done` 均按序产生
- **THEN** 两轮事件归属无交叉、无丢失

#### Scenario: 接收循环异常

- **WHEN** 接收循环因 SDK 异常退出
- **THEN** 事件流出现 `error` 事件说明接收中断，后续发送消息被明确拒绝而非挂起

### Requirement: 中断后同一会话必须可继续

`interrupt()` 成功结束当前轮后，同一会话 MUST 可继续发送下一轮消息，且模型
MUST 能引用中断前已完成的对话上下文；`session_id` MUST 保持不变。空闲状态下
调用中止 MUST 安全返回，MUST NOT 破坏会话。中断 MUST NOT 自动断开客户端。
中断 MUST NOT 被假定为能停止已进入执行的 MCP 工具调用：中止流程 MUST 继续通过
服务端批次取消契约止损，已完成的写入不回滚。

#### Scenario: 中断后继续并保留上下文

- **WHEN** 一轮执行中被告知中止，随后用户在同一会话发送新消息
- **THEN** 新轮次正常返回，且能基于中断前的对话内容作答
- **THEN** 会话 `session_id` 与中断前一致

#### Scenario: 空闲置停

- **WHEN** 会话空闲时收到中止请求
- **THEN** 接口安全返回，随后发送消息仍可正常执行

#### Scenario: 中断不停止已执行的 MCP 工具

- **WHEN** 中断发生在某个 MCP 写工具已开始执行之后
- **THEN** 轮次立即结束，但该工具可能仍完成；服务端取消契约为 MUST 保留项，
  补偿清单可查

### Requirement: 流式增量与完整文本必须去重

启用流式 partial 消息时，事件层 MUST 对同一段文本只产出一次：存在增量时
MUST 仅由增量产出 `text_delta`，随后到达的完整文本 MUST NOT 再次产出；无增量
到达时 MUST 以完整文本兜底产出一条 `text_delta`。该规则 MUST 在长文本、多工具
连续轮次下同样成立。

#### Scenario: 短回复不重复

- **WHEN** 一轮回复产生 1 个增量且随后到达内容相同的完整文本消息
- **THEN** 前端只收到一条对应的 `text_delta`，不出现重复展示

#### Scenario: 无增量时兜底

- **WHEN** 本轮未产生任何增量（例如仅工具调用或极短回复）
- **THEN** 完整文本仍以一条 `text_delta` 产出，文本不丢失

## MODIFIED Requirements

### Requirement: 执行中的任务必须可中止

Web 会话 MUST 支持中止当前任务：`POST /api/sessions/{id}/abort`（租约校验）
MUST 取消当前轮次并调用 `QoderSDKClient.interrupt()`；本轮因中断产生的
`error_during_execution` 结果 MUST 映射为 `turn_aborted` 事件，MUST NOT 记为
普通错误。中止 MUST 复位 `turn_running`、清理本会话旧确认票据，并 MUST NOT
断开客户端，以便同一会话继续下一轮。

中止流程 MUST 先使用会话 MCP Token 请求服务端建档批次中止
（`POST /api/archive/tasks/{task_id}/cancel`）；服务端 MUST 在当前工作单元
完成后停止并返回 `cancelled=true`、`cursor`、`remaining` 与 `report_id`。
中止 MUST NOT 自动回滚已完成的写入，补偿清单 MUST 保留可查。当 `interrupt()`
失败或超时，流程 MUST 回退到取消轮次任务的兜底路径并产生说明原因的 `error`
事件，MUST NOT 静默挂起。

#### Scenario: 中止执行中的轮次

- **WHEN** 轮次正在执行时用户点击「停止」
- **THEN** 轮次被中断，事件流出现 `turn_aborted`，界面不再显示“执行中”
- **THEN** 同一会话随后发送的新消息可正常执行

#### Scenario: 中止服务端建档批次

- **WHEN** 客户端超时但 MCP 服务端仍在执行建档批次
- **THEN** 取消请求使服务端在当前单元后停止，返回 `cancelled=true` 与续跑游标，
  已建设备与补偿清单保留

#### Scenario: 中止后旧确认不生效

- **WHEN** 中止完成后再调用此前已确认的写工具
- **THEN** 旧票据已清理，需重新确认后才放行
