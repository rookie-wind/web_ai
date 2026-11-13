# agent-runtime-session Delta

## ADDED Requirements

### Requirement: 外部检索与协议助手的路由必须可判定且前缀可选

Web 会话 MUST 向模型暴露内置 `WebSearch` 工具（由门禁显式放行并记审计），使外部
公开资料可被检索；MUST NOT 暴露 `WebFetch`、`Bash` 等可拉取任意 URL 或执行命令的
工具。系统提示 MUST 声明路由边界：平台数据、设备、建档、参数下发、协议转换与边缘
操作 MUST 走 xlpa MCP 工具；公开协议标准、厂商手册、行业信息与用户给定 URL 的公开
内容 MUST 走 WebSearch；两者都需要的任务可先检索资料再用 MCP 落地。无法判定时
MUST 默认按 xlpa 理解或向用户澄清，MUST NOT 静默把内部业务内容发往外部检索。

路由 MUST 支持可选前缀 `/web` 与 `/xlpa`：仅对当前一条消息强制指定路由，执行前
MUST 从任务文本中剥离；不带前缀时 MUST 自动判定。前缀 MUST NOT 改变会话模式、
MUST NOT 要求用户每次输入都携带。系统提示 MUST 禁止把凭据（账号/密码/验证码/
Token）、设备地址与内部协议文档原文送入 WebSearch；需要检索内部相关内容时 MUST
先脱敏或征得用户确认。检索失败或不可用时，Agent MUST 如实告知用户，MUST NOT 以
模型记忆冒充检索结果。

#### Scenario: 外部协议标准问题走网页检索

- **WHEN** 用户询问"Modbus TCP 默认端口是多少"或要求查阅公开协议标准
- **THEN** Agent 调用 `WebSearch` 并基于检索结果回答（附来源），不调用 xlpa 写工具

#### Scenario: 平台设备问题走 xlpa

- **WHEN** 用户询问某边缘网关上存在哪些设备
- **THEN** Agent 走 xlpa MCP 工具（必要时先经确认卡片获取凭据），不调用 WebSearch

#### Scenario: 前缀强制路由

- **WHEN** 用户发送 `/web <任务>` 或 `/xlpa <任务>`
- **THEN** 本次消息按指定路由执行，前缀在任务文本中被剥离，后续消息恢复自动判定

#### Scenario: 前缀边界

- **WHEN** 用户发送 `/web`（无任务）、在消息中间出现 `/web`，或使用未约定的 `/xxx`
- **THEN** 无任务时追问检索主题；非开头的 `/` 与其他 `/xxx` 均按普通文本处理，
  不触发路由覆盖

#### Scenario: 混合任务先检索后执行

- **WHEN** 用户要求"先查某公开协议规范，再在平台上创建对应类型"
- **THEN** Agent 先调用 WebSearch 获取公开资料，再用 xlpa MCP 工具执行平台操作

#### Scenario: 内部信息不得外发

- **WHEN** 用户要求检索的内容包含账号、密码、设备地址或内部协议文档原文
- **THEN** Agent 先脱敏或向用户确认，MUST NOT 原样送入 WebSearch
