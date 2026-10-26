## Purpose

定义协议转换 Agent 资源包的分发、安装、更新与校验行为，使 Skill 文档、配套工具、模板、校验器、参考资料和 manifest 能作为一个可版本化、可验证、可回滚的整体交付。

## ADDED Requirements

### Requirement: 资源包必须支持多类型 Agent 资源
系统 SHALL 将 Agent 分发单元定义为资源包，而不 SHALL 限定为单个 `SKILL.md` 文件；资源包 MUST 支持 Skill 文档、Agent 配置、工具脚本、模板、校验器、参考资料和 manifest 等资源类型。

#### Scenario: 资源包包含 Skill 配套文件
- **WHEN** 服务端生成可下载资源包
- **THEN** 资源包包含 `.trae/skills/` 下每个 Skill 目录内声明的 `SKILL.md`、`agents/`、`tools/`、`templates/`、`validators/`、`references/` 和 `manifest.json` 文件
- **THEN** 未声明或不存在的可选目录不得阻塞资源包生成

#### Scenario: 后续新增资源类型
- **WHEN** 后续某个 Skill 新增模板、校验器或参考资料等资源文件
- **THEN** 系统通过 manifest 声明和资源包打包规则交付该文件
- **THEN** 不要求为每一种新增文件类型单独重写安装或更新流程

### Requirement: 资源包必须提供 manifest 驱动的校验信息
系统 SHALL 为资源包提供 manifest 信息，用于描述包版本、资源清单、必需文件、可选文件、Skill 版本和更新后校验规则。

#### Scenario: 首次安装读取 manifest
- **WHEN** 用户或 Agent 首次安装资源包
- **THEN** 安装流程读取资源包 manifest
- **THEN** 安装流程校验 manifest 中声明的必需文件均存在
- **THEN** 缺失必需文件时不得声称安装完成

#### Scenario: 更新后校验 manifest
- **WHEN** 用户或 Agent 完成资源包更新
- **THEN** 更新流程读取更新后的 manifest
- **THEN** 更新流程校验必需文件、关键 Skill 目录和 Agent 配置文件存在
- **THEN** 校验失败时必须报告缺失项和已创建的备份路径

### Requirement: 首次接入与后续更新必须复用同一资源包语义
系统 SHALL 使用同一套资源包结构和 manifest 校验语义支持首次接入和后续更新，避免安装流程与更新流程对文件范围的理解不一致。

#### Scenario: 首次接入安装资源包
- **WHEN** 接入页生成安装说明
- **THEN** 说明必须以 Agent 资源包为交付对象
- **THEN** 说明必须要求保留 manifest 中声明的目录结构和必需文件

#### Scenario: 后续更新资源包
- **WHEN** 用户主动要求更新 Agent 资源包或检测到远端版本较新
- **THEN** 更新流程必须先备份当前 `.trae/skills` 目录
- **THEN** 更新流程必须从服务端下载资源包并全量覆盖资源包管理范围
- **THEN** 更新流程必须在覆盖后执行 manifest 校验
- **THEN** 更新完成后必须提示用户重新加载 `/pca` 会话或重启客户端

### Requirement: MCP 客户端工具必须随资源包分发且作为备用通道
系统 SHALL 将通用 MCP 客户端工具作为 `pca` Skill 的配套资源随资源包分发，并 SHALL 明确其仅作为 IDE 原生 MCP 调用不可用时的备用通道。

#### Scenario: 资源包包含备用 MCP 客户端
- **WHEN** 用户下载或更新 Agent 资源包
- **THEN** 资源包中包含 `pca/tools/mcp_client.py`
- **THEN** manifest 将该文件声明为需要校验的资源

#### Scenario: 原生 MCP 调用正常
- **WHEN** IDE 原生 MCP 连接可用且 `list_mcp_tools` 探测成功
- **THEN** Agent 优先使用 IDE 原生 MCP 工具调用
- **THEN** Agent 不自动运行备用 MCP 客户端脚本

#### Scenario: 原生 MCP 调用失败
- **WHEN** IDE 原生 MCP 连接不可用、Token 失效或连接未加载
- **THEN** Agent 可以使用资源包内的 `pca/tools/mcp_client.py` 执行备用 MCP 调用
- **THEN** 备用调用必须读取本地 `.trae/mcp.json` 中的端点和 Token，或通过用户确认的参数覆盖

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

### Requirement: 用户可见说明必须区分分发、安装、更新和运行
系统 SHALL 在接入页和 `/pca` Skill 文档中清晰区分资源包分发、首次安装、后续更新、运行时 MCP 调用和备用客户端调用。

#### Scenario: 接入页生成说明
- **WHEN** 接入页生成接入文本
- **THEN** 文本说明资源包下载地址、解压目标、manifest 校验点和备用 MCP 客户端位置
- **THEN** 文本不得暗示安装后会无条件自动运行 Python 脚本

#### Scenario: Skill 前置检查说明
- **WHEN** `/pca` Skill 执行前置检查
- **THEN** Skill 明确优先使用 IDE 原生 MCP 工具调用
- **THEN** Skill 仅在原生 MCP 调用失败时提示或使用资源包内备用 MCP 客户端
- **THEN** Skill 更新流程覆盖 manifest 声明的所有资源，而不只覆盖 `SKILL.md`