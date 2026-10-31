# agent-runtime-session Delta

## MODIFIED Requirements

### Requirement: SDK 事件必须归一化为自有事件契约 v1

后端 MUST 将 SDK 消息归一化为自有事件契约（版本字段 v=1），事件统一携带
v、seq（会话内单调递增）、session_id、ts；事件类型至少覆盖：
session_started、text_delta（实时增量，基于 SDK 流式能力）、tool_call、
tool_result、ask_user（基于 SDK elicitation 通道，Agent 向用户提问）、
gate_blocked（写入门禁拒绝，Agent 等待用户确认）、artifact（产物就绪，含产物
标识与下载入口提示，供前端渲染下载入口，MUST NOT 含凭据或一次性下载 grant
（grant 由按需铸造端点下发））、turn_done、
session_closed、error。SDK 类型与字段名 MUST NOT
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

#### Scenario: 写入门禁拒绝事件

- **WHEN** Agent 的写入类工具调用被门禁 Hook 拒绝（gate_blocked 语义，
  详见 write-gate-isolation 能力）
- **THEN** 前端收到 gate_blocked 事件（含 tool_name 与目标提示），
  可渲染"等待用户确认"提示；用户确认后 Agent 可重试该调用

#### Scenario: 产物就绪事件

- **WHEN** Agent 产出可下载产物：来源 A 为内置写入工具在
  会话工作区 `xlpa-output/` 内生成的文本类文档（turn 收尾扫描检测）；
  来源 B 为白名单 MCP 工具返回 `file_id` 的原生产物（事件时后端立即回源落盘，
  详见 web-artifact-delivery 能力）
- **THEN** 前端收到 artifact 事件（含产物标识与下载入口提示），据此渲染下载入口
- **THEN** artifact 事件 MUST NOT 含凭据或一次性 grant；下载 grant 由按需铸造端点
  下发，实际下载经 web-artifact-delivery 的代理下载 + 一次性 grant 流程完成

#### Scenario: SDK 事件类型不外泄

- **WHEN** 检查事件契约与前端接口的响应结构
- **THEN** 不出现 SDK 的类型名（如 AssistantMessage/StreamEvent）作为契约字段
