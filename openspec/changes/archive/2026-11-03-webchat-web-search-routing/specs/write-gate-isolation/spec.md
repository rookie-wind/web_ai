# write-gate-isolation Delta

## MODIFIED Requirements

### Requirement: 运行时工具面必须收敛为 MCP 工具且登录类工具禁用

Web 会话实例的默认工具面 MUST 收敛为 MCP 工具、已启用 Skill 与受限的外部检索
工具；内置命令工具 `Bash` MUST 保持关闭。内置写入工具（`Write`、`Edit`、
`MultiEdit`、`NotebookEdit`）MUST 仅在同时满足以下条件时放行：

- 工具入参提供非空 `file_path`；
- 该路径经 `resolve()` 解析后位于 `${会话工作区}/xlpa-output/` 目录内；
- 文件扩展名属于文本类文档白名单（`.md`、`.txt`、`.csv`、`.tsv`、`.json`、
  `.jsonl`、`.html`、`.htm`、`.xml`、`.yaml`、`.yml`、`.log`、`.sql`）。

不满足任一条件（含 `..` 目录逃逸、工作区外绝对路径、缺失 `file_path`、
非白名单扩展名、未注入会话工作区）时 MUST 防御性 deny，且该类 deny
`confirmable` MUST 为 false——策略限制不可经用户确认解除。放行与拒绝 MUST 走既有
`gate_blocked` 事件与审计台账。本变更 MUST NOT 依赖任何 agent 可写的路径/命令
白名单配置文件，门禁裁决 MUST 位于 webchat 后端进程内。

内置检索工具 `WebSearch` MUST 被显式放行并记审计；`WebFetch`、读取类、命令类
及其他未登记的内置工具 MUST 保持 deny（不放行服务端 URL 拉取，避免 SSRF 面）。

PreToolUse Hook MUST 对云平台业务登录工具 `login` 显式且**绝对禁止**（deny 不进入
票据校验，webchat 会话已持族凭据、禁对话内业务登录改变会话角色）。对边缘会话开辟
工具 `edge_get_token` MUST 实施**需确认放行**：无有效 grant 时 deny 并要求用户确认，
经 confirm 端点铸票后在 TTL 窗口内放行，其 grant 目标为 `edge_get_token`（与写入类
同构的计划域窗口语义）。对任何不属于已知 MCP 工具集、也不属于上述受限内置写入
放行集与 `WebSearch` 的工具名 MUST 防御性 deny。

#### Scenario: 登录类工具被禁

- **WHEN** 模型在 webchat 会话中调用云平台业务登录 `login`
- **THEN** 调用被 deny（不校验任何 grant），会话事件流出现标记为
  "绝对禁止、不可经确认解除"的 gate_blocked 事件

#### Scenario: 边缘会话开辟无票据时被拒

- **WHEN** 模型在未持有效 grant 的情况下调用 `edge_get_token`
- **THEN** 调用被 deny，事件流出现标记为"需用户确认"的 gate_blocked 事件，
  前端可对该目标发起确认

#### Scenario: 边缘会话开辟经确认后放行

- **WHEN** 用户确认 `edge_get_token` 后模型再次调用该工具
- **THEN** 在 grant 有效期内放行，工具执行并返回 `task_id` 供后续读取类
  `edge_*` 工具使用；窗口过期后同目标再次调用需重新确认

#### Scenario: 未知工具防御性拒绝

- **WHEN** PreToolUse 收到不属于已知 MCP 工具集、也不属于受限内置写入放行集
  与 `WebSearch` 的工具名
- **THEN** 调用被 deny（Fail-Closed），不放行未知工具面

#### Scenario: 会话产物目录内文本写入放行

- **WHEN** 模型调用 `Write` 写入 `${会话工作区}/xlpa-output/report.md`
- **THEN** 调用被放行，产物在 turn 收尾被扫描登记并产 `artifact` 事件

#### Scenario: 产物目录外写入被拒

- **WHEN** 模型调用 `Write` 写入 `xlpa-output/../secret.md`、工作区外绝对路径、
  非文本扩展名（如 `.docx`），或未提供 `file_path`
- **THEN** 调用被 deny 且不可经确认解除，事件流出现 `gate_blocked` 记录

#### Scenario: 命令工具仍关闭

- **WHEN** 模型调用 `Bash` 或其他内置命令工具
- **THEN** 调用被 deny（Fail-Closed）

#### Scenario: 网页检索放行且留痕

- **WHEN** 模型调用内置 `WebSearch` 检索公开资料
- **THEN** 调用被放行并写入门禁审计；`WebFetch`、`Bash` 仍被拒绝
