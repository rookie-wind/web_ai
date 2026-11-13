## Context

现有商品形态（已归档）：

- `adapter._build_options` 固定 `tools=["Write","Edit","Skill"]`、
  `allowed_tools=["Write","Edit"]`、`permission_mode="acceptEdits"`、
  `disallowed_tools=["Bash"]`、`skills=["xlpa"]`，并挂 PreToolUse 与 can_use_tool。
- `WriteGate.decide` 对非 `mcp__` 工具仅放行 Skill 与产物目录内的内置写入，
  其他一律 deny；`can_use_tool` 对 MCP 放行、对受限写入校验路径。
- 会话只启用 xlpa 技能，没有独立路由技能；工具选择由模型根据描述与系统提示决定。

实测证据：`_smoke_v5.out` 变体 W（追加 WebSearch 并放行）中 WebSearch 调用成功、
MCP 仍 connected（77 工具）、无工具错误；变体 P（现状）模型明确表示无 WebSearch。

## Goals

- 让模型能检索外部公开资料，同时保持 xlpa MCP 工具面不变。
- 用户不记前缀也能用；需要强制路由时可选用 `/web` 或 `/xlpa`。
- 明确"内部信息不外发"的数据边界。

## Routing Model

### 自动判定（默认，无需前缀）

| 用户意图 | 路由 | 判据 |
|---|---|---|
| 平台数据、设备树、网关、建档、参数下发、召测、协议转换、边缘操作 | **xlpa MCP** | 需要访问平台/边缘真实数据或执行写操作 |
| 公开协议标准、厂商手册、行业新闻、给定 URL 的公开内容、最新版本信息 | **WebSearch** | 与内部系统无关、公开可检索 |
| 先查公开资料、再用平台数据落地（如"查规范后在平台上加一条大类"） | **WebSearch → xlpa** | 混合任务，先检索后执行 |
| 无法判断 | **默认 xlpa 理解或向用户澄清** | 避免内部信息外发 |

### 可选前缀（强制覆盖自动判定）

| 输入 | 行为 |
|---|---|
| `/web <任务>` | 本次强制 WebSearch；前缀在任务文本中剥离 |
| `/xlpa <任务>` | 本次强制 xlpa；前缀在任务文本中剥离 |
| 不带前缀 | 按上表自动判定 |
| `/web` 后无任务 | 向用户追问检索主题，不发起空查询 |
| 其他 `/xxx` | 视为普通文本，不按路由前缀处理 |

前缀约束：

- 仅识别消息**开头**（允许前后空白），大小写不敏感；
- 只影响**当前一条消息**，不改变会话模式、不写入 API 字段、不持久化；
- 执行前 MUST 从任务文本剥离前缀，MUST NOT 把 `/web` 当检索词；
- 用户不要求每次输入都带前缀。

## Decisions

### D1 只暴露 WebSearch，不暴露 WebFetch（本次）

- WebSearch 由 CLI/后端检索服务执行，模型只传查询词；WebFetch 会让服务端拉取
  任意 URL，存在 SSRF 与外泄面，本次不开放。`Bash`、读取类内置工具同样保持关闭。
- 门禁新增 `WEB_SEARCH_TOOL_NAMES = {"WebSearch"}`，放行并写审计；其余非
  MCP/非受限写入的内置工具仍 Fail-Closed deny。
- WebFetch 列为**后续评估项**：需先设计 URL 白名单/域名限制/重定向与内网地址
  拦截，不在本变更交付。

### D2 路由以系统提示为主，前缀为可选强制定向

- 系统提示写入上表规则与"不确定先澄清"的降级策略。
- 前缀由系统提示解释并在执行前剥离；不需要前端拦截，也不需要改消息 API。
- 若实测模型对前缀遵循不稳定，再考虑前端把前缀转成显式模式徽标（另开变更）。

### D3 数据边界（隐私）

- 系统提示 MUST 禁止把凭据（账号/密码/验证码/Token）、设备 IP/名称、内部协议
  文档原文送入 WebSearch；需要外部资料时只发送公开主题词。
- 若用户要求检索的内容包含内部信息，Agent MUST 先脱敏或向用户确认。
- 检索失败或不可用时，Agent MUST 如实告知，MUST NOT 以模型记忆冒充检索结果。

### D4 输入区提示（前端最小改动）

- 输入框 placeholder 增加一行可选前缀说明：
  "可选前缀：/web 强制网页检索、/xlpa 强制协议助手（默认自动判断）"。
- 不新增模式开关、不拦截 `/`、不改变发送逻辑；用户不填前缀照常使用。

## Risks

- 模型可能误把内部问题发到 WebSearch：默认偏 xlpa + 明确禁止内部信息 + 可选
  前缀缓解。
- WebSearch 依赖后端检索服务，可能不可用/限流：工具错误会作为 tool_result 回到
  模型，由模型如实告知用户。
- 前缀依赖模型遵循系统提示；如不稳定，再评估前端显式模式。

## Verification Plan

- 重跑 `_smoke_websearch_v5.py` 变体 W（或等价用例），确认 WebSearch 调用成功、
  MCP 工具数不变（77）、无错误。
- 单元测试：工具面包含 WebSearch；门禁放行 WebSearch 且 WebFetch/Bash 仍 deny；
  系统提示包含路由表、前缀语义与数据边界；placeholder 含前缀说明。
- 行为验收：外部标准问题走 WebSearch；平台设备问题走 xlpa；`/web`、`/xlpa`
  强制生效；不带前缀自动判定；内部信息检索被拒绝或先脱敏。
- 回归：webchat 全量 pytest 与主项目基线全绿。
