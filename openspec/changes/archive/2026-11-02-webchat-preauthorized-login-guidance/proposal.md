## Why

Web 会话的 MCP 接入凭据在创建时已由服务端用账号内置 `phone/code` 调用
`login` 完成平台授权激活（`runtime.create` → `call_login_tool`），但
canonical 技能仍保留面向 IDE/独立客户端的“请提供手机号+验证码并调用 login”
流程，系统提示也没有说明 Web 预激活。实测出现自相矛盾的对话：

- Agent 按技能要求向用户索要手机号/验证码；
- 用户提供后 Agent 调用 `login`，门禁以“webchat 会话已持凭据”绝对拒绝；
- Agent 随后直接调用 `get_*` 又成功（证明业务 Token 已生效）。

这既浪费轮次，也把手机号/验证码写进了聊天与事件历史。

## What Changes

- 系统提示明确：Web 会话已预激活，Agent MUST NOT 调用 `login`、MUST NOT
  索要手机号/验证码，直接调用 `get_*`；认证失效时如实告知并由服务端重新激活。
- canonical `xlpa` 与 `modbus-conversion` 技能的登录章节增加 Web 会话例外，
  避免 `/xlpa` 全文注入后与系统提示冲突。
- `login` 门禁保持绝对禁止，不做放行。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `agent-runtime-session`: 明确“预激活后 Agent 不得调用 login 或索取凭据”。
