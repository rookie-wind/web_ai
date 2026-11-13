## Why

一次真实客户端建档测试暴露两类会卡死长会话的凭据/门禁缺陷：门禁票据固定 300s
窗口在跑满上百台设备的长轮次里中途过期，触发"确认风暴"；MCP 接入 Token 铸票后
绝对到期（默认 2 小时、活动不续期），会话跨线后所有工具调用（含只读）返回
`-32001 Unauthorized: Invalid token`，且客户端无换发入口，整会话直接死掉。同时
前端对绝对禁止/护栏自纠错类拦截也弹出会暂停进度的确认卡，制造噪声、打断进度。

## What Changes

- 门禁票据（grant）由"固定窗口、放行不延长"改为**滑动消费**：窗口内每次命中放行
  把到期时间顺延一个 TTL，持续写入的长轮次不再中途被拦；停手满 TTL 才回收。
- webchat 族 MCP 接入 Token 改为**滑动续期 + 绝对寿命封顶**：每次 `/mcp` 活动按
  签发窗口顺延 `expires_at`，但不超过 `createdAt + TTL 上限`；停止活动满窗口后
  自然到期。IDE 族（无 `expires_at`）不参与。
- 前端确认卡触发面**收窄**：仅「需用户补充信息（参数表单卡）」与「写入/删除
  （可确认解除）」两类弹卡并暂停进度；绝对禁止类与护栏自纠错类降级为一行弱提示，
  不打断进度。
- 安全底线不变：门禁票据唯一铸造入口是确认卡片手势，聊天框文字"确认/授权"不铸票。

## Capabilities

### New Capabilities
- 无（本次均为既有能力的 Requirement 变更）。

### Modified Capabilities
- `write-gate-isolation`：改动 Requirement「计划域授权票据语义」中"grant 在 Hook
  放行时即记为消费、不因使用延长"为滑动消费；调整 Scenario「有效票据窗口内多次
  放行」「执行失败不退票」。
- `mcp-token-management`：改动 Requirement「Token Registry 必须保留管理元数据」下
  webchat 族到期语义——新增「webchat 族凭据随活动滑动续期」Scenario，明确续期窗口
  与绝对寿命封顶。
- `web-chat-ui`：改动 Requirement「写入确认卡片必须呈现参数摘要且未确认零写入」——
  把"MUST 弹卡"限定为可确认解除类，绝对禁止/护栏自纠错类 MUST 降级为弱提示且不暂停。

## Impact

- 代码：`mcp_server/server.py`（`TokenManager.touch_token`/`mint_token`）、
  `webchat/webchat/grants.py`（`GrantStore.check` + 模块 docstring）、
  `webchat/webchat/static/js/app.js`（`gate_blocked` 分流 + `renderForbiddenNotice`）。
- 测试：`mcp_server/tests/test_refactor.py`、`webchat/tests/test_grants.py` 增补滑动语义用例。
- 文档：新增 `GLOSSARY.md`、`docs/adr/0001~0003`；归档时同步三处主 spec。
- 兼容性：无接口/入参破坏性变更；仅凭据与票据的时间语义、前端渲染分流变化。
