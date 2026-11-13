# agent-runtime-session Specification（delta）

## ADDED Requirements

### Requirement: Web 会话系统提示必须约定图布局紧凑规则

webchat 会话的系统提示追加段 MUST 包含图布局紧凑规则：流程图默认 TB（上下）
方向；并行分支/泳道数量尽量不超过 3；节点文案尽量精简（建议 ≤10 字），
MUST NOT 在单节点内书写长句；并说明 Web 页面展示宽度有限、图越紧凑越可读。
该约定与富内容输出格式约定（表格用 markdown、流程图用 mermaid 代码块）
并存且互不替代，MUST NOT 改动 SKILL.md、agent_assets 资源包或 IDE 路径。

#### Scenario: webchat 会话输出流程图方向紧凑

- **WHEN** 用户在 webchat 会话请求多环节流程说明
- **THEN** 助手输出的 mermaid 以 TB 方向组织、并行分支不超过约定上限

#### Scenario: 节点文案精简

- **WHEN** 助手输出 mermaid 图
- **THEN** 节点文案为精短短语，不出现长句节点

#### Scenario: IDE 路径不受影响

- **WHEN** 检查 SKILL.md、agent_assets 资源包与 IDE 会话的提示来源
- **THEN** 无任何改动，IDE 会话行为与本变更前一致
