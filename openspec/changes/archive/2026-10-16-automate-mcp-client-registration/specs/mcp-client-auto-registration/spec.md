## Purpose

定义通过接入说明文本驱动目标客户端内的 Agent，把 protocol-converter 自动、幂等地写入该工具真实 MCP 配置文件并完成验证的行为契约；同时约束服务端资产与逻辑与具体工具解耦。本能力为**零脚本**：不新增随包分发的注册程序，接入的正确性由文本内容与 Agent 遵循行为保证。

## ADDED Requirements

### Requirement: 接入文本必须给出目标客户端的真实配置文件路径与条目
系统 SHALL 在接入页生成的安装文本中，针对所选平台给出该客户端**实际读取**的 MCP 配置文件路径（用户级或项目级），以及符合该客户端格式的 `protocol-converter` 条目，指示 Agent 把该条目写入此文件，而非仅提示"在设置界面粘贴"。

#### Scenario: Qoder 接入文本指向真实文件
- **WHEN** 用户选择 Qoder 平台生成接入文本
- **THEN** 文本必须指明目标文件为 Qoder 用户级 `~/.qoder/mcp.json`
- **THEN** 文本必须给出使用 `url` 与 `headers.Authorization`、不含 `type` 字段的条目
- **THEN** 文本必须指示 Agent 把该条目写入上述文件

#### Scenario: 项目级配置客户端指向项目文件
- **WHEN** 用户选择使用项目级配置的目标（如 Trae、Cursor、VS Code）
- **THEN** 文本必须指明对应项目根目录下的配置文件（如 `.trae/mcp.json`、`.cursor/mcp.json`、`.vscode/mcp.json`）
- **THEN** 端点主机必须为 IPv4 或 `localhost`，文本不得给出 IPv6 地址

#### Scenario: 未知平台不臆造路径
- **WHEN** 目标平台不在接入页支持列表内
- **THEN** 文本不得编造该平台的配置文件路径
- **THEN** 系统必须说明该平台的接入需人工确认配置位置

### Requirement: 接入文本必须内嵌幂等、合并与备份约束
系统 SHALL 在安装文本中要求 Agent 以"先读后写、仅新增或更新 `protocol-converter` 条目、保留其它 server、重复执行结果一致、写入前对无法解析的既有文件先备份"的方式修改配置，MUST NOT 指示整体覆盖配置文件。

#### Scenario: 保留其它已注册 server
- **WHEN** 目标配置文件已包含其它 MCP server 条目
- **THEN** 文本必须要求 Agent 保留这些条目，仅新增或更新 `protocol-converter`

#### Scenario: 文件缺失时创建
- **WHEN** 目标配置文件或其父目录不存在
- **THEN** 文本必须要求 Agent 创建缺失的目录与仅含 `protocol-converter` 的合法配置

#### Scenario: 既有配置损坏时先备份
- **WHEN** 目标配置文件存在但不是合法 JSON
- **THEN** 文本必须要求 Agent 先备份原文件再中止并提示，而不是直接覆盖

### Requirement: 接入文本必须要求写入后验证连接与鉴权
系统 SHALL 在安装文本中要求 Agent 在写入配置后调用 `list_mcp_tools` 验证连通与鉴权，并 SHALL 仅在验证通过时声明接入完成；验证失败时 MUST 提供手动兜底指引。

#### Scenario: 验证通过
- **WHEN** Agent 写入配置并成功调用 `list_mcp_tools`
- **THEN** 文本流程必须报告接入完成，并展示工具数量与 `access_level`

#### Scenario: 验证失败回退手动
- **WHEN** 写入后 `list_mcp_tools` 失败或返回鉴权错误
- **THEN** 文本流程必须报告失败原因且不得声称接入完成
- **THEN** 文本必须给出该平台可直接粘贴的完整 JSON 片段与目标文件路径作为手动兜底

### Requirement: 接入凭据不得泄露或误用
系统 SHALL 在接入文本中仅把接入 Token 作为 `Authorization: Bearer` 用于连接用途，MUST NOT 指示把后端业务 Token 写入 MCP 配置，并 SHOULD 提示 Token 属敏感信息、不要在日志或公开渠道回显完整明文。

#### Scenario: 区分接入 Token 与业务 Token
- **WHEN** 文本描述要写入配置的内容
- **THEN** 仅包含 MCP 接入 Token（连接用途）
- **THEN** 文本不得要求把后端业务 Token 写入客户端 MCP 配置

### Requirement: 服务端必须与具体工具解耦
系统 SHALL 保证服务端资源与逻辑不与任何单一 AI 工具绑定：Agent 资源包从中性目录打包，服务端产物与代码 MUST NOT 写死或默认生成某个工具专属目录/配置文件；面向工具的路径只出现在供客户端消费的接入文本中。

#### Scenario: 资源包打包源为中性目录
- **WHEN** 服务端生成可下载 Agent 资源包
- **THEN** 打包源必须为与 IDE 无关的中性目录（`agent_assets/skills`）
- **THEN** 服务端不得要求把资源包发布源放在某个具体 IDE 的目录下

#### Scenario: 服务端不默认写工具专属配置
- **WHEN** 服务端安装/部署流程运行
- **THEN** 服务端不得默认生成仅对某一工具生效的配置文件作为唯一接入手段
- **THEN** 工具侧配置的写入由目标工具内 Agent 依据接入文本完成
