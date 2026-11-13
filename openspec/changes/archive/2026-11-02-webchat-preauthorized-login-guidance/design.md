## Context

- 会话创建链路：`/api/auth/login` 取得平台业务身份 → `POST /api/sessions`
  以账号库 `phone/code` 调 `runtime.create` → `call_login_tool` 用该会话
  MCP 凭据调一次 `login`，绑定业务 Token；失败则创建会话 502。
- `login` 工具在门禁中是绝对禁止（`LOGIN_TOOL_NAMES`），因为 Web 不允许
  Agent 使用任意账号。
- 技能是按 IDE/独立客户端场景写的，登录步骤与 Web 预激活冲突。

## Decisions

### D1 以系统提示为运行时事实源

`WEBCHAT_SYSTEM_APPEND` 增加平台登录约定：已预激活、不得调用 `login`、
不得索要手机号/验证码、认证失效时由服务端重新激活。系统提示每轮注入，
优先级高于技能文档。

### D2 技能增加 Web 例外

`xlpa/SKILL.md` 的“本地后端业务 Token 检查”和 `modbus-conversion/SKILL.md`
的“步骤 0：登录与 Token”增加 Web 例外段落：Web 会话跳过该步骤，IDE/独立
客户端仍按原文执行。`/xlpa` 前缀注入全文时不会再把模型引向 `login`。

### D3 门禁不放行

`login` 仍绝对禁止；预激活在服务端完成，Agent 无需也不得调用。若激活失败
或过期，应由服务端重新激活，而不是降级为 Agent 登录。

## Risks / Trade-offs

- 若账号库未配置 `phone/code`，会话不会激活；此时 `get_*` 会返回未登录，
  Agent 按提示如实告知用户，不再索取凭据。
- 技能文档同时服务 IDE 与 Web，采用“Web 例外”段落而非删除登录流程。
