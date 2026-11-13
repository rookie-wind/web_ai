# agent-runtime-session Specification（delta）

## ADDED Requirements

### Requirement: Web 会话系统提示必须约定富内容输出格式

webchat 会话的系统提示追加段 MUST 包含输出格式约定：结构化数据与点表
MUST 以 markdown 表格语法输出；流程、时序与状态说明 MUST 以 mermaid
代码块输出。该约定 MUST 仅经 webchat 会话系统提示追加段注入（不替换
CLI 原生系统提示），MUST NOT 改动 SKILL.md、agent_assets 资源包或任何
IDE 路径的提示来源；IDE 会话 MUST NOT 受该约定影响。

#### Scenario: webchat 会话输出点表用表格语法

- **WHEN** 用户在 webchat 会话请求协议点表或结构化清单
- **THEN** 助手以 markdown 表格语法输出该内容，前端可渲染为可读表格

#### Scenario: webchat 会话输出流程说明用 mermaid

- **WHEN** 用户在 webchat 会话请求流程/时序/状态说明
- **THEN** 助手输出 mermaid 代码块，前端可渲染为图形

#### Scenario: IDE 路径不受影响

- **WHEN** 检查 SKILL.md、agent_assets 资源包与 IDE 会话的提示来源
- **THEN** 无任何改动，IDE 会话行为与本变更前一致
