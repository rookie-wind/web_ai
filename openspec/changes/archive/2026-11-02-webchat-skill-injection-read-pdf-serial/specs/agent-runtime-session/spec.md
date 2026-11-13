# agent-runtime-session Delta

## ADDED Requirements

### Requirement: 技能必须从 canonical 目录索引并按需注入

Web 会话启动时 MUST 读取 `agent_assets/skills`（或 `WEBCHAT_SKILLS_ROOT`
指定目录）下各 `SKILL.md` 的 name/description/when_to_use，形成索引写入
系统提示，并 MUST 给出每个 SKILL.md 的真实路径。模型 MUST 能通过内置 Read
按需读取全文。用户消息以 `/技能名` 开头时，该技能 SKILL.md 全文 MUST 在
**当轮**注入；未匹配的前缀 MUST 按普通文本处理，不得误注入其他技能。
技能来源 MUST NOT 使用仓库 `.qoder/skills` 等客户端副本。

#### Scenario: 用户显式 /xlpa 提问

- **WHEN** 用户发送 `/xlpa 帮我生成脚本`
- **THEN** 本轮用户消息前包含 canonical `xlpa/SKILL.md` 全文，且系统提示含技能索引

#### Scenario: 普通消息不注入

- **WHEN** 用户发送不带技能前缀的普通消息
- **THEN** 不注入任何技能全文，行为与存量会话一致

#### Scenario: 技能目录缺失

- **WHEN** 技能母本目录不存在或不可读
- **THEN** 服务仍可启动，系统提示明确说明未发现技能目录，不得伪造技能内容

### Requirement: 内置只读工具必须受根目录白名单约束

系统 MUST 暴露内置 `Read`，且仅当路径经 `resolve()` 后位于会话工作区或
canonical 技能目录内时放行。越界路径、目录穿越、缺参或未配置可读根目录
MUST 一律拒绝，且 MUST NOT 经用户确认解除。

#### Scenario: 读取技能手册

- **WHEN** Agent 调用 `Read` 读取 `agent_assets/skills/xlpa/SKILL.md`
- **THEN** 放行并记审计

#### Scenario: 读取仓库敏感文件

- **WHEN** Agent 调用 `Read` 读取工作区与技能目录之外的仓库文件
- **THEN** 拒绝并产 `gate_blocked` 事件（`guard=read_path`、不可确认解除）

### Requirement: 同一会话的轮次必须串行

同一会话在一个轮次执行期间 MUST NOT 接受新的用户消息；服务端 MUST 返回
409 并提示「上一轮仍在执行，请稍候」，不得排队、不得拉起第二个 CLI 轮次。
确认端点 MUST 在响应中给出当前会话是否仍有执行中轮次；前端在该轮仍在执行
时 MUST NOT 自动发送续跑消息。

#### Scenario: 执行中重复发送

- **WHEN** 上一轮仍在执行时用户再次发送消息
- **THEN** 返回 409，事件流不出现重复或缺失的轮次序号

#### Scenario: 执行中确认写入

- **WHEN** 轮次仍在执行时用户在确认卡片上确认
- **THEN** 票据照常铸造，前端不自动续跑，提示助手将在当前轮重试
