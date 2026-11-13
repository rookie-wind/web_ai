## Why

Web 助手目前只有 xlpa MCP 工具与产物写入能力，无法查询外部公开资料（协议标准、
厂商手册、最新信息）。同时用户需要明确：某条输入应该走网页检索还是走 xlpa
平台工具，避免把内部设备/协议问题发到外网，也避免该联网时只用模型记忆。

技术路线已用真实模型 + 真实 MCP 冒烟验证（`_smoke_websearch_v5.py` →
`_smoke_v5.out`）：

- 当前生产形态（`tools=["Write","Edit","Skill"]`）下模型看不到 WebSearch；
- 追加 `"WebSearch"` 并在门禁/权限回调放行后，模型成功调用 WebSearch 并返回
  真实检索结果，同时 xlpa MCP 仍保持 `connected`、77 个工具可用、无工具错误。

因此本变更只需暴露并放行内置 WebSearch，加上路由约定，无需新增 MCP 工具或外网代理。

## What Changes

- **暴露 WebSearch 内置工具**：`tools` 追加 `"WebSearch"`；`can_use_tool` 放行；
  门禁新增 WebSearch 允许类别（仍写 `gate_blocked` 审计与事件）。`WebFetch`、
  `Bash` 等其他内置工具保持关闭（不做 URL 拉取，避免 SSRF 面）。
- **路由规则（模型判定）**：系统提示明确边界——平台/设备/建档/协议转换/边缘操作
  只走 xlpa MCP 工具；公开资料/协议标准/厂商手册/URL/最新信息走 WebSearch；
  两者都需要时可先检索资料再用 MCP 落地；不确定时默认按 xlpa 理解或向用户确认。
- **可选前缀**：`/web <任务>` 强制本次走网页检索，`/xlpa <任务>` 强制本次走协议
  助手；不带前缀则自动判定。前缀只影响当前一条消息，不改变会话模式、不新增 API
  字段、不要求用户每次输入都带前缀。
- **数据边界**：MUST NOT 把凭据、设备地址、内部协议文档内容送入 WebSearch；
  需要外部检索时应先脱敏或仅发送公开主题词。
- **前端零改动**：仍以普通文本发送；后续如需 IDE 式斜杠命令或"自动/网页/协议"
  按钮，另开变更。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `agent-runtime-session`: 新增"外部检索与协议助手的路由必须可判定且前缀可选"
  要求（含 WebSearch 可用性、默认路由、前缀语义与数据边界）。
- `write-gate-isolation`: 运行时工具面放行集合增加 `WebSearch`；`WebFetch`、
  `Bash` 等保持拒绝。

## Impact

- **webchat 后端**：`sdk_runtime/adapter.py`（tools、can_use_tool、系统提示）、
  `grants.py`（WebSearch 允许类别）。
- **前端**：零改动。
- **mcp_server**：零改动（WebSearch 是 CLI 内置工具，不走 MCP）。
- **测试**：工具面/门禁放行/系统提示断言；重跑 WebSearch 冒烟。
- **风险**：模型误路由；检索服务不可用或限流；查询内容外发。缓解：默认偏 xlpa、
  可选前缀、系统提示的数据边界与"不确定先确认"。
