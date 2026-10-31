# agent-runtime-session Delta

## ADDED Requirements

### Requirement: 确认与凭据收集必须由前端卡片先行

Web 会话 MUST 在 Agent 首次调用受门禁保护的工具（含 `edge_get_token`）时即渲染
确认/参数卡片，供用户在当前卡片内填写凭据与确认，MUST NOT 要求用户先通过聊天
文本提供凭据再触发卡片。系统 MUST 通过系统提示告知 Agent：需要确认或凭据时直接
调用相应工具（缺失参数可留空）以触发表单，MUST NOT 在聊天中索要密码或验证码，
MUST NOT 要求用户以聊天回复"确认"作为授权方式。卡片提交后，MUST 由既有 confirm
端点铸票并自动携带所填参数续跑，无需用户再次输入。

#### Scenario: 请求边缘设备树时卡片先行

- **WHEN** 用户请求读取某边缘后端设备树，而会话尚未提供该环境凭据
- **THEN** Agent 直接调用 `edge_get_token`，前端立即出现确认/参数卡片，
  用户可在卡片内填写账号、密码、验证码并提交，无需先在聊天中粘贴凭据

#### Scenario: 卡片提交自动铸票续跑

- **WHEN** 用户在卡片内填写必填参数并点击「确认并提交」
- **THEN** 后端铸造该目标的一次性窗口票据，并把所填参数随续跑消息发给 Agent，
  Agent 重试调用时在窗口内放行

#### Scenario: Agent 不得引导聊天确认

- **WHEN** Agent 需要用户授权某受门禁工具
- **THEN** 其回复 MUST 引导用户使用确认卡片，MUST NOT 声称"回复确认"即可授权
