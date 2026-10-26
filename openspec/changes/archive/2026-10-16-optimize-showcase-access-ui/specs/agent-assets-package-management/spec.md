## MODIFIED Requirements

### Requirement: 资源包分发必须保持现有接口兼容
系统 SHALL 保持现有 Skills ZIP 下载接口可用，并 SHALL 在不破坏现有用户接入方式的前提下扩展资源包管理能力。

#### Scenario: 旧下载端点继续可用
- **WHEN** 用户访问现有 Skills ZIP 下载端点
- **THEN** 服务端仍返回可解压的 ZIP 包
- **THEN** ZIP 包中的既有 Skill 目录结构保持兼容

#### Scenario: 接入说明兼容旧客户端
- **WHEN** 用户使用现有接入页复制 MCP 配置
- **THEN** 生成的 MCP server 配置格式保持与目标 IDE 兼容
- **THEN** 新增资源包说明不得要求 IDE 支持额外协议才能完成基础 MCP 接入
- **THEN** 新增 Qoder 平台不得改变 Trae、Cursor、VS Code Copilot、Claude Desktop、Windsurf、Cline 和 Kimi Code 的既有配置格式

### Requirement: 用户可见说明必须区分分发、安装、更新和运行
系统 SHALL 在接入页和 `/pca` Skill 文档中清晰区分资源包分发、首次安装、后续更新、运行时 MCP 调用和备用客户端调用。

#### Scenario: 接入页生成说明
- **WHEN** 接入页生成接入文本
- **THEN** 文本说明资源包下载地址、解压目标、manifest 校验点和备用 MCP 客户端位置
- **THEN** 文本不得暗示安装后会无条件自动运行 Python 脚本
- **THEN** 文本必须根据当前选择的目标平台生成对应 MCP JSON 配置

#### Scenario: Skill 前置检查说明
- **WHEN** `/pca` Skill 执行前置检查
- **THEN** Skill 明确优先使用 IDE 原生 MCP 工具调用
- **THEN** Skill 仅在原生 MCP 调用失败时提示或使用资源包内备用 MCP 客户端
- **THEN** Skill 更新流程覆盖 manifest 声明的所有资源，而不只覆盖 `SKILL.md`
