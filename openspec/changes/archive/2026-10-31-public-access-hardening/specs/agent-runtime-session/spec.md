## Purpose

修订 `agent-runtime-session` 中与实现不符的两处契约：事件类型 `ask_user`
的来源（原写作「基于 SDK elicitation 通道」，经实测该通道在本系统不可达：
mcp_server 零 elicitation 使用、mcp 库无现成发送 API、SDK 亦无对应提问工具）
与 `turn_done` 的字段语义（实测落盘把事件序号当作轮次号，且耗时字段丢失）；
并新增「会话凭据必须完成平台授权激活」要求——实测新建会话的接入凭据未经
登录绑定，导致任何云端工具调用都被 `NOT_LOGGED_IN` 拒绝。

## MODIFIED Requirements

### Requirement: SDK 事件必须归一化为自有事件契约 v1

后端 MUST 将 SDK 消息归一化为自有事件契约（版本字段 v=1），事件统一携带
v、seq（会话内单调递增）、session_id、ts；事件类型至少覆盖：
session_started、text_delta（实时增量，基于 SDK 流式能力）、tool_call、
tool_result、ask_user（Agent 向用户提问；来源为 SDK elicitation 事件，
或本轮结束时模型文本中含待用户补充的提问——后者为当前唯一可达路径，
elicitation 通道若在其他系统落地可作为扩展来源）、
gate_blocked（写入门禁拒绝，Agent 等待用户确认）、artifact（产物就绪，含产物
标识与下载入口提示，供前端渲染下载入口，MUST NOT 含凭据或一次性下载 grant
（grant 由按需铸造端点下发））、turn_done（本轮结束，payload MUST 携带
本轮真实轮次序号 `turn` 与本轮耗时 `duration_ms`；`turn` MUST NOT 使用
事件 seq 或其他计数器替代）、session_closed、error。SDK 类型与字段名 MUST NOT
泄漏到契约之外（业务层与前端只见自有事件）；未知事件类型 MUST 保留透传
（type=unknown，前端降级展示）。流式增量与完整文本块 MUST NOT 重复
产出（已产出 partial 增量的文本不再产出完整 text_delta 事件）。

#### Scenario: 消息轮产生完整事件序列

- **WHEN** 会话中一轮用户消息被处理
- **THEN** 前端按序收到该轮的 tool_call / tool_result / text_delta / turn_done
  事件，seq 单调递增且无空洞
- **THEN** 同一段文本不因流式增量与完整文本块双重产出而重复展示

#### Scenario: Agent 向用户提问

- **WHEN** Agent 在执行中需要用户补充信息（elicitation 请求，或本轮以
  提问文本结束而未发起任何工具调用）
- **THEN** 前端可识别出这是一次待用户补充的提问（事件型走 ask_user；
  本轮结束型由前端从本轮文本判定并呈现补充输入入口），任务等待用户回答；
  用户的回答作为下一轮输入回注同一会话并保持上下文

#### Scenario: 写入门禁拒绝事件

- **WHEN** Agent 的写入类工具调用被门禁 Hook 拒绝（gate_blocked 语义，
  详见 write-gate-isolation 能力）
- **THEN** 前端收到 gate_blocked 事件（含 tool_name 与目标提示），
  可渲染"等待用户确认"提示；用户确认后 Agent 可重试该调用

#### Scenario: 产物就绪事件

- **WHEN** Agent 产出可下载产物（落会话工作区 xlpa-output/，由后端 turn 收尾扫描
  检测；来源 B mcp_server 原生产物的自动检测一期不做、降级二期）
- **THEN** 前端收到 artifact 事件（含产物标识与下载入口提示），据此渲染下载入口
- **THEN** artifact 事件 MUST NOT 含凭据或一次性 grant；下载 grant 由按需铸造端点
  下发，实际下载经 web-artifact-delivery 的代理下载 + 一次性 grant 流程完成

#### Scenario: SDK 事件类型不外泄

- **WHEN** 检查事件契约与前端接口的响应结构
- **THEN** 不出现 SDK 的类型名（如 AssistantMessage/StreamEvent）作为契约字段

#### Scenario: turn_done 字段语义正确

- **WHEN** 一轮用户消息处理完毕，事件流写入 turn_done
- **THEN** 其 `turn` 等于本轮在会话内的轮次序号（首轮为 1），而非事件序号
- **THEN** 其 `duration_ms` 为本轮实际耗时，取值来自运行时而非缺省 0

## ADDED Requirements

### Requirement: 会话接入凭据必须完成平台授权激活

webchat 为会话签发的接入凭据 MUST 在会话对用户可用之前完成平台登录绑定，
使该凭据发起的云端工具调用不处于未登录态。激活 MUST 由后端使用账号已预设
的凭据自动完成，MUST NOT 要求用户在页面输入手机号或短信验证码。激活失败
MUST 使会话创建明确失败并向用户给出可辨识原因，MUST NOT 返回一个可对话、
但任何云端操作都会被拒绝的会话。

#### Scenario: 新建会话可直接执行云端只读

- **WHEN** 用户创建会话后首次要求查询云端数据
- **THEN** agent 的工具调用返回真实数据，事件流不出现「需先登录」类拒绝，
  agent 也不向用户索取手机号或验证码

#### Scenario: 激活不向用户索取凭据

- **WHEN** 用户以账号密码登录 webchat 并创建会话
- **THEN** 全流程不出现要求用户补充平台手机号或短信验证码的环节

#### Scenario: 激活失败不留下不可用会话

- **WHEN** 会话创建过程中的平台授权激活失败
- **THEN** 创建请求返回失败且不产生可用会话，前端展示明确原因，
  不出现「会话已就绪但一查就报错」的状态
