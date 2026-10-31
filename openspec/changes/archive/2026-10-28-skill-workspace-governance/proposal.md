## Why

Web/移动端接入方案（`docs/requirements/web-mobile-access-requirements.md`，C1）
要求技能目录作为**只读母本**被多个并发会话共享；但现状是技能作业过程会把
中间产物与最终产物写进技能目录自身（上一轮已隔离 132 个残留文件，
`validation/quarantine/`），且 `output/` 产物目录约定仍留在技能目录内
（`modbus-conversion` 与 `modbus-cq-adapt` 共 14 处引用）。不先完成治理，
多会话并发会互相污染工作区，后续 Web 运行时变更（C3~C6）无法安全开展。

## What Changes

- **产物落位迁移**：`modbus-conversion` 与 `modbus-cq-adapt` 的最终产物
  从技能目录内 `output/` 迁出，改为落位到会话工作区（IDE 现状为用户
  指定或默认的工作目录）；SKILL.md 中全部 14 处 `output/` 引用同步改写，
  `modbus-conversion → modbus-cq-adapt` 的跨技能交接路径随之调整。
- **技能目录只读约定固化**：所有 SKILL.md 明确"技能目录只读，作业产物
  一律落会话工作区"；目录结构说明中的 `output/` 条目移除。
- **残留清理**：删除技能目录内运行残留（3 处 `__pycache__/`、
  1 个 Word 锁文件 `~$原子标签定义.docx`——需 Word 释放后删除）。
- **凭据停止跟踪**：`git rm --cached` 停止跟踪 `mcp_server/.env` 与
  `mcp_server/.token_registry.json`，补齐 `.gitignore` 条目；
  仓库历史中的凭据轮换列为运维建议（不强制在本变更内完成）。
- **资源包升版**：`agent_assets/skills/package-manifest.json`
  0.24.0 → 0.25.0，交付语义随 SKILL.md 改写同步更新。
- 明确**不在本变更内**：Web 后端、CLI 运行时、新 MCP 工具、登录——
  本变更是纯治理前置，为后续 C2~C7 铺路。

## Capabilities

### New Capabilities

- `skill-workspace-governance`: 技能目录只读母本与作业产物落位约定——
  技能目录在作业过程中零写入；中间产物与最终产物一律落会话工作区；
  跨技能交接通过工作区路径完成；技能目录残留的清理与防再生规则；
  分发源中凭据文件不得纳入版本跟踪。

### Modified Capabilities

（无——资源包升版属实现细节，不改变 `agent-assets-package-management`
的既有需求语义。）

## Impact

- **代码 / 资源**：
  - `agent_assets/skills/modbus-conversion/SKILL.md`（7 处 output/ 引用、
    目录结构说明、产出确认流程文字）
  - `agent_assets/skills/modbus-cq-adapt/SKILL.md`（7 处 output/ 引用、
    输入读取路径、交接示例）
  - 其余 7 个 SKILL.md：补一段"目录只读"通用约定（无行为改动处不动）
  - `agent_assets/skills/package-manifest.json`（版本 0.24.0 → 0.25.0）
  - `.gitignore`（补 `mcp_server/.env`；确认既有条目覆盖后无需重复）
  - 技能目录残留文件删除（`__pycache__/` ×3、`~$*.docx` ×1）
- **既有测试**：pytest 基线须全绿；`mcp_server` Python 代码零改动，
  预期无测试回归风险；SKILL.md 文本变更需人工核对引用一致性。
- **依赖方**：IDE 侧用户需更新资源包至 0.25.0 才获得新落位约定；
  旧版（≤0.24.0）继续在技能目录内写 `output/`，行为不中断但不再被
  分发源承认（由后续 Web 运行时的路径白名单 Hook 拦截，不在本变更内）。
- **验收依赖**：Word 进程须已释放 `~$原子标签定义.docx` 的句柄，
  否则锁文件删除失败（实施时如仍被占用，记录并单独跟进）。
