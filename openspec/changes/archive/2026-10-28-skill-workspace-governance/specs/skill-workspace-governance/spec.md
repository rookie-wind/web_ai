## Purpose

定义技能目录作为只读母本的行为契约：作业过程对技能目录零写入，中间产物与
最终产物一律落会话工作区，跨技能交接通过工作区路径完成，分发源中不得残留
作业产物或纳入版本跟踪的凭据文件。

**变更四要素**

| 要素 | 内容 |
|---|---|
| 前置条件（含需先验证事项） | 1) `~$原子标签定义.docx` 锁文件已被 Word 释放（实施前探测，仍占用则记录并单独跟进）；2) 核对 `modbus-conversion` / `modbus-cq-adapt` 共 14 处 `output/` 引用清单与语义（已完成 grep 核实：各 7 处）；3) 确认 `.gitignore` 既有条目（`__pycache__/`、`~$*`、`.token_registry.json` 已覆盖，`mcp_server/.env` 缺失需补）；4) pytest 基线当前全绿（实施前先跑一遍取证） |
| 要做的事 | SKILL.md 产物落位改写（output/ → 会话工作区）、目录只读约定固化、残留清理（`__pycache__` ×3、Word 锁 ×1）、`git rm --cached` 停止跟踪 `.env` 与 `.token_registry.json`、资源包 0.24.0 → 0.25.0 |
| 通过标准（可执行判据） | 1) pytest 基线全绿；2) 完整跑一轮"modbus 转换 → cq 适配"后，`agent_assets/skills/` 目录树零新增文件（含 `output/`、`temp/`、`__pycache__`）；3) 分发源内 grep 不到 `output/`、`temp/` 落位指引；4) `git ls-files` 中不再出现 `.env`、`.token_registry.json`；5) 资源包 manifest 版本为 0.25.0 且必需文件校验通过；6) IDE 人工回归清单（取模板/建档/转换各一例）通过 |
| 执行顺序与依赖 | 最先执行（C1），无前序依赖；后续 C2~C7 均依赖本变更的只读母本前提 |

## ADDED Requirements

### Requirement: 技能目录在作业过程中必须零写入

系统分发的技能目录（`agent_assets/skills/` 下各 Skill 目录）SHALL 在任何
作业过程中保持零写入：SKILL.md 的作业指引 MUST NOT 指示 Agent 向技能目录
写入任何文件或目录（含 `output/`、`temp/` 及其他中间产物目录）。

#### Scenario: 转换作业不产生技能目录写入

- **WHEN** Agent 按 `modbus-conversion` SKILL.md 完整执行一次转换作业并生成最终 JSON 配置
- **THEN** 生成的配置文件落位在会话工作区，技能目录内不存在任何新增文件或目录

#### Scenario: SKILL.md 中无技能目录落位指引

- **WHEN** 检查分发源中所有 SKILL.md 的产物落位指引
- **THEN** 不存在将中间产物或最终产物写入技能目录的指引（含 `output/`、`temp/` 路径形态）

### Requirement: 作业产物必须落位会话工作区

所有 SKILL.md MUST 指示：中间产物与最终产物（转换配置 JSON、测试报告、
逐页抽取文本、页面图等）一律落位到会话工作区；跨技能交接（如
`modbus-conversion` 的产物交给 `modbus-cq-adapt` 处理）MUST 通过会话
工作区路径完成，MUST NOT 依赖技能目录内的共享目录。

#### Scenario: 最终产物落会话工作区

- **WHEN** Agent 完成一次 Modbus 转换并经用户确认后写盘
- **THEN** JSON 配置文件写入会话工作区（如用户指定目录或默认工作目录），文件名规则保持不变

#### Scenario: 跨技能交接经由工作区

- **WHEN** 用户要求将一份已生成的 Modbus 转换配置做重庆地区适配
- **THEN** `modbus-cq-adapt` 从会话工作区读取源配置文件，适配结果写回会话工作区，全程不触碰技能目录

### Requirement: 技能目录只读约定必须显式声明

每个 SKILL.md MUST 包含显式的目录只读约定：技能目录为只读母本，任何作业
产物不得写入；该约定在资源包 manifest 版本中体现为一次版本升级。

#### Scenario: 只读约定可被检索

- **WHEN** 检查分发源中任一 SKILL.md
- **THEN** 可检索到技能目录只读、产物落会话工作区的明确约定表述

#### Scenario: 资源包版本升级

- **WHEN** 本变更的 SKILL.md 改写完成并交付
- **THEN** `package-manifest.json` 版本高于 0.24.0，且 manifest 声明的必需文件全部存在

### Requirement: 分发源不得残留作业产物

分发源技能目录 MUST NOT 包含作业运行残留：`__pycache__/` 目录、Office
锁文件（`~$*`）、历史作业产物文件。发现残留时 MUST 予以删除或隔离，
不得随资源包分发。

#### Scenario: 残留清理后分发源干净

- **WHEN** 检查分发源技能目录树
- **THEN** 不存在 `__pycache__/` 目录、`~$` 开头的 Office 锁文件或其他作业残留文件

### Requirement: 分发源凭据文件不得纳入版本跟踪

仓库 MUST NOT 跟踪含凭据内容的文件：`mcp_server/.env` 与
`mcp_server/.token_registry.json` MUST 通过 `git rm --cached` 停止跟踪并
由 `.gitignore` 覆盖；工作副本文件本身 MUST 保留在磁盘上以维持本地运行。

#### Scenario: 停止跟踪后仓库不再含凭据工作副本

- **WHEN** 执行 `git ls-files` 检查跟踪清单
- **THEN** `mcp_server/.env` 与 `mcp_server/.token_registry.json` 不在跟踪清单中，且两文件仍存在于工作目录

#### Scenario: 后续改动不再进入暂存区

- **WHEN** 上述文件内容因本地运行而变化
- **THEN** `git status` 不将其报告为已跟踪文件的改动
