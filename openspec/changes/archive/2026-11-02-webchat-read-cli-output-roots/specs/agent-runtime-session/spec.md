# agent-runtime-session Delta

## MODIFIED Requirements

### Requirement: 内置只读工具必须受根目录白名单约束

系统 MUST 暴露内置 `Read`，且仅当路径经 `resolve()` 后位于会话工作区、
canonical 技能目录或配置的额外白名单目录内时放行。额外白名单 MUST 默认
包含 CLI 大结果落盘目录（`%TEMP%/qoder-mcp-outputs` 与
`~/.qoder-cn/tmp`），并 MUST 支持 `WEBCHAT_READ_EXTRA_ROOTS` 追加
（逗号或分号分隔）。越界路径、目录穿越、缺参或未配置可读根目录 MUST 一律
拒绝，且 MUST NOT 经用户确认解除。事件库、其他会话工作区、仓库密钥与
MCP 配置 MUST 保持在白名单之外。

#### Scenario: 读取技能手册

- **WHEN** Agent 调用 `Read` 读取 `agent_assets/skills/xlpa/SKILL.md`
- **THEN** 放行并记审计

#### Scenario: 读取仓库敏感文件

- **WHEN** Agent 调用 `Read` 读取白名单之外的仓库文件（如 `.env`、
  `permissions.json` 或事件库）
- **THEN** 拒绝并产 `gate_blocked` 事件（`guard=read_path`、不可确认解除）

#### Scenario: 读取 CLI 大结果落盘文件

- **WHEN** MCP 工具结果过大，CLI 将其落盘到 `%TEMP%/qoder-mcp-outputs` 或
  `~/.qoder-cn/tmp` 并让 Agent 读取
- **THEN** 放行并返回文件内容，不再出现“操作被禁止: Read”红卡

#### Scenario: 其他会话仍不可读

- **WHEN** Agent 尝试读取另一个会话的工作区或事件库
- **THEN** 拒绝并产 `gate_blocked` 事件，不得跨会话读取
