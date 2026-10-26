## ADDED Requirements

### Requirement: 资源包不得内嵌工具专属注册程序
系统 SHALL 以**文本驱动**方式支持 MCP 客户端接入，由目标工具内的 Agent 依据接入说明直接写入其配置文件；资源包 MUST NOT 内嵌为某一具体 IDE 定制的注册程序，也 MUST NOT 因接入需要而把服务端资源包发布源置于该 IDE 目录下。

#### Scenario: 备用客户端仍是唯一随包工具
- **WHEN** 服务端生成资源包
- **THEN** 资源包继续包含备用 MCP 客户端 `xlpa/tools/mcp_client.py`
- **THEN** 资源包不得新增仅服务某 IDE 的注册可执行程序

#### Scenario: 打包源保持工具中立
- **WHEN** 服务端打包 Agent 资源包
- **THEN** 打包源必须为中性目录 `agent_assets/skills`，与客户端最终安装目录（按平台区分）解耦

## MODIFIED Requirements

### Requirement: 用户可见说明必须区分分发、安装、更新和运行
系统 SHALL 在接入页和 `/pca` Skill 文档中清晰区分资源包分发、首次安装、后续更新、运行时 MCP 调用和备用客户端调用；首次安装说明 SHALL 引导目标工具内的 Agent 直接把 MCP server 写入其真实配置文件（零脚本），并 SHALL 在验证失败时提供手动粘贴兜底。

#### Scenario: 接入页生成说明
- **WHEN** 接入页生成接入文本
- **THEN** 文本说明资源包下载地址、解压目标、manifest 校验点和备用 MCP 客户端位置
- **THEN** 文本必须给出针对所选平台的真实配置文件路径与由 Agent 直接写入/合并的操作说明（幂等、保留其它 server、损坏先备份）
- **THEN** 文本必须要求写入后调用 `list_mcp_tools` 验证，失败时回退到该平台可手动粘贴的 JSON 片段与文件路径
- **THEN** 文本不得暗示安装后会在无人触发的情况下自动常驻运行 Python 脚本

#### Scenario: Skill 前置检查说明
- **WHEN** `/pca` Skill 执行前置检查
- **THEN** Skill 明确优先使用 IDE 原生 MCP 工具调用
- **THEN** Skill 仅在原生 MCP 调用失败时提示或使用资源包内备用 MCP 客户端
- **THEN** Skill 更新流程覆盖 manifest 声明的所有资源，而不只覆盖 `SKILL.md`
