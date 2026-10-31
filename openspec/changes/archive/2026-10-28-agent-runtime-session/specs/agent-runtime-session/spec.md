## Purpose

定义 Web 会话运行时的行为契约：会话生命周期、会话与 CLI 实例及接入凭据的
1:1:1 绑定、SDK 事件向自有事件契约 v1 的归一化、SSE 下发与断线重放、
单写者租约、实例池与配额、会话工作区布局与隔离。

**变更四要素**

| 要素 | 内容 |
|---|---|
| 前置条件（含需先验证事项） | 1) C1/C2 已归档；2) V1/V3/V4/V9/V10 已 PASS（v1v3 + C2 证据）；3) **需补验**：V1b（SDK 会话恢复粒度：resume/session_id + SessionStore 载体已确认存在，行为待实测）、V2（`/xlpa` 技能在无头 SDK 会话中是否展开；失败回退：系统提示词注入路由表）、实例冷启动成本（采样记录）；4) MCP Server 可启动且 mint 端点就绪（mcp-token-mint spec 同变更交付） |
| 要做的事 | SDK adapter（SDK 类型只出现在 webchat/webchat/sdk_runtime/ 单层）、会话管理（创建/发消息/列表/历史/结束）、1:1:1 绑定、事件契约 v1（归一化+持久化+seq 重放）、SSE 端点、单写者租约、实例池与配额、会话工作区布局、IDE 兼容回归 |
| 通过标准（可执行判据） | 1) webchat pytest 全过（1:1:1 隔离断言：两并发会话的实例/凭据/工作区/事件流互不串扰；seq 重放补齐；租约抢占；配额超限拒绝；结束会话凭据撤销）；2) 主 pytest 基线全绿；3) V1b/V2/冷启动结论留证（含失败回退决策记录）；4) 一次真实"登录→建会话→发消息→收到事件流→断线重连补齐"端到端演练取证；5) IDE 回归：/mcp 与接入页行为不变 |
| 执行顺序与依赖 | 依赖 C2（票据体系）与本变更的 mcp-token-management delta + mcp-token-mint（同变更内先交付）；C4/C5 依赖本变更 |

## ADDED Requirements

### Requirement: Web 会话必须与 CLI 实例及接入凭据 1:1:1 绑定

每个 Web 会话 MUST 对应恰好一个专属 CLI 实例与一把专属 MCP 接入凭据；
凭据在实例启动时随配置绑定，运行期 MUST NOT 切换；实例与凭据 MUST NOT
跨会话共享；会话结束时凭据 MUST 撤销、实例 MUST 终止、工作区按保留策略
处置。

#### Scenario: 并发会话互不串扰

- **WHEN** 用户 A 与用户 B 各自创建会话并同时在各自会话中执行任务
- **THEN** 两会话使用不同的 CLI 实例、不同的接入凭据、不同的工作区目录
- **THEN** 任一会话的工具调用审计归属各自的 owner_ref，互不混淆

#### Scenario: 会话结束即回收

- **WHEN** 会话被用户结束或超时回收
- **THEN** 该会话的接入凭据立即撤销（后续 /mcp 调用 401），CLI 实例终止，
  事件流以收尾事件关闭

### Requirement: SDK 事件必须归一化为自有事件契约 v1

后端 MUST 将 SDK 消息归一化为自有事件契约（版本字段 v=1），事件统一携带
v、seq（会话内单调递增）、session_id、ts；事件类型至少覆盖：
session_started、text_delta（实时增量，基于 SDK 流式能力）、tool_call、
tool_result、ask_user（基于 SDK elicitation 通道，Agent 向用户提问）、
turn_done、error、session_closed。SDK 类型与字段名 MUST NOT
泄漏到契约之外（业务层与前端只见自有事件）；未知事件类型 MUST 保留透传
（type=unknown，前端降级展示）。流式增量与完整文本块 MUST NOT 重复
产出（已产出 partial 增量的文本不再产出完整 text_delta 事件）。

#### Scenario: 消息轮产生完整事件序列

- **WHEN** 会话中一轮用户消息被处理
- **THEN** 前端按序收到该轮的 tool_call / tool_result / text_delta / turn_done
  事件，seq 单调递增且无空洞
- **THEN** 同一段文本不因流式增量与完整文本块双重产出而重复展示

#### Scenario: Agent 向用户提问

- **WHEN** Agent 在执行中需要用户补充信息（elicitation 请求）
- **THEN** 前端收到 ask_user 事件（含问题内容），任务挂起等待用户回答；
  用户的回答作为下一轮输入回注会话

#### Scenario: SDK 事件类型不外泄

- **WHEN** 检查事件契约与前端接口的响应结构
- **THEN** 不出现 SDK 的类型名（如 AssistantMessage/StreamEvent）作为契约字段

### Requirement: 事件必须持久化并支持断线重放

事件流 MUST 由 webchat 后端持久化为自有事实源（按会话分区、seq 有序）；
SSE 下发 MUST 支持 `Last-Event-ID` 续传：客户端断线重连后 MUST 补齐
断线期间漏掉的事件；重放与实时下发 MUST NOT 产生 seq 冲突或重复投递
（同 seq 事件幂等）。

#### Scenario: 断线重连补齐

- **WHEN** 客户端在事件 seq=10 断线、任务继续推进至 seq=25 后重连并携带
  Last-Event-ID=10
- **THEN** 服务端按序补发 seq=11..25 的事件，随后无缝转入实时下发

#### Scenario: 刷新后回看完整过程

- **WHEN** 用户刷新页面或新设备进入同一会话
- **THEN** 前端可从持久化事件源回看该会话的全部历史事件（seq 从头重放）

### Requirement: 会话必须实施单写者租约

每个会话 MUST 至多有一个持有写租约的执行者（前端 15s 心跳、租约默认
45s TTL）；无租约或租约过期的连接 MUST 以只读旁观方式接收事件；
新连接 MUST NOT 并发写入同一会话；接管 MUST 先中断当前执行轮再转移
租约。

#### Scenario: 第二个标签页只读旁观

- **WHEN** 同一用户在第二个标签页打开同一会话（不持租约）
- **THEN** 第二标签页实时收到事件但无法发送消息
- **THEN** 第一标签页的执行不受干扰

#### Scenario: 租约失联自动释放

- **WHEN** 持有租约的连接停止心跳超过租约 TTL
- **THEN** 租约自动释放，后续连接可接管

### Requirement: 实例池必须有配额与明确拒绝语义

系统 MUST 实施资源上限：全局活跃 CLI 实例上限（默认 4，可配）、每用户
并发会话上限（默认 1，可配）、单轮 max_turns 上限（默认 25）；达到上限时
MUST 返回明确的"繁忙/超限"响应（含排队或建议重试信息），MUST NOT 复用
他人实例、MUST NOT 静默排队无限等待。

#### Scenario: 全局实例上限

- **WHEN** 活跃实例数达到全局上限且有新会话创建请求
- **THEN** 新请求被明确拒绝并提示繁忙，现有会话不受影响

#### Scenario: 单轮工具迭代上限

- **WHEN** 一轮对话的工具调用轮次达到 max_turns 上限
- **THEN** 运行中止并以 error 事件说明原因，会话可继续下一轮

### Requirement: 会话工作区必须与会话绑定并受布局约束

每个会话 MUST 拥有独立工作区目录（布局含 xlpa-tmp/ 与 xlpa-output/，
遵循 C1 约定）；工作区路径 MUST 由后端分配，MUST NOT 由客户端指定
（防路径逃逸）；会话结束后工作区内容按保留策略处置（后续 C5 定义保留期，
本变更先落实"会话结束不删除、按目录隔离"）。

#### Scenario: 工作区按会话隔离

- **WHEN** 两个并发会话各自产生作业产物
- **THEN** 产物分别落位各自工作区的 xlpa-output/，互不可见

### Requirement: 会话事件流必须与会话凭据解耦

任务执行 MUST 与浏览器连接解耦：连接断开时运行中的任务 MUST 继续执行并
持续产生事件（写入持久化事件源）；重连后按重放语义补看。会话票据校验
MUST 先于 SSE 订阅（无票据或票据过期拒绝订阅）。

#### Scenario: 断线不中断任务

- **WHEN** 用户在任务执行中关闭浏览器
- **THEN** 任务继续执行至本轮结束，事件持续入库；用户重连后可看到全部过程
