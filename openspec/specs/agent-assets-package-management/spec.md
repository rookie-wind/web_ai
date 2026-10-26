## Purpose

定义协议转换 Agent 资源包的分发、安装、更新与校验行为，使 Skill 文档、配套工具、模板、校验器、参考资料和 manifest 能作为一个可版本化、可验证、可回滚的整体交付。

## Requirements

### Requirement: 资源包必须支持多类型 Agent 资源
系统 SHALL 将 Agent 分发单元定义为 XLPA 资源包，而不 SHALL 限定为单个 `SKILL.md` 文件；资源包 MUST 支持 Skill 文档、Agent 配置、工具脚本、模板、校验器、参考资料和 manifest 等资源类型。

#### Scenario: 资源包包含 Skill 配套文件
- **WHEN** 服务端生成可下载资源包
- **THEN** 资源包包含每个 Skill 目录内声明的 `SKILL.md`、`agents/`、`tools/`、`templates/`、`validators/`、`references/` 和 `manifest.json` 文件
- **THEN** 资源包必须包含 `xlpa` 入口 Skill 及其备用 MCP 客户端
- **THEN** 未声明或不存在的可选目录不得阻塞资源包生成

#### Scenario: 后续新增资源类型
- **WHEN** 后续某个 Skill 新增模板、校验器或参考资料等资源文件
- **THEN** 系统通过 manifest 声明和资源包打包规则交付该文件
- **THEN** 不要求为每一种新增文件类型单独重写安装或更新流程

### Requirement: 资源包必须提供 manifest 驱动的校验信息
系统 SHALL 为 XLPA 资源包提供 manifest 信息，用于描述包版本、资源清单、必需文件、可选文件、Skill 版本、模板版本和更新后校验规则。

#### Scenario: 首次安装读取 manifest
- **WHEN** 用户或 Agent 首次安装资源包
- **THEN** 安装流程读取资源包 manifest
- **THEN** 安装流程校验 manifest 中声明的必需文件均存在
- **THEN** 缺失必需文件时不得声称安装完成

#### Scenario: 更新后校验 manifest
- **WHEN** 用户或 Agent 完成资源包更新
- **THEN** 更新流程读取更新后的 manifest
- **THEN** 更新流程校验必需文件、关键 Skill 目录、Agent 配置文件和 XLPA 自动建档模板存在
- **THEN** 校验失败时必须报告缺失项和已创建的备份路径

### Requirement: 首次接入与后续更新必须复用同一资源包语义
系统 SHALL 使用同一套 XLPA 资源包结构和 manifest 校验语义支持首次接入和后续更新，避免安装流程与更新流程对文件范围的理解不一致。

#### Scenario: 首次接入安装资源包
- **WHEN** 接入页生成安装说明
- **THEN** 说明必须以 XLPA Agent 资源包为交付对象
- **THEN** 说明必须要求保留 manifest 中声明的目录结构和必需文件

#### Scenario: 后续更新资源包
- **WHEN** 用户主动要求更新 Agent 资源包或检测到远端版本较新
- **THEN** 更新流程必须先备份当前本地 Skills 目录
- **THEN** 更新流程必须从服务端下载资源包并全量覆盖资源包管理范围
- **THEN** 更新流程必须在覆盖后执行 manifest 校验
- **THEN** 更新完成后必须提示用户重新加载 `/xlpa` 会话或重启客户端

### Requirement: MCP 客户端工具必须随资源包分发且作为备用通道
系统 SHALL 将通用 MCP 客户端工具作为 `xlpa` Skill 的配套资源随资源包分发，并 SHALL 明确其仅作为 IDE 原生 MCP 调用不可用时的备用通道。

#### Scenario: 资源包包含备用 MCP 客户端
- **WHEN** 用户下载或更新 Agent 资源包
- **THEN** 资源包中包含 `xlpa/tools/mcp_client.py`
- **THEN** manifest 将该文件声明为需要校验的资源
- **THEN** 资源包不得要求存在 `pca/tools/mcp_client.py`

#### Scenario: 原生 MCP 调用正常
- **WHEN** IDE 原生 MCP 连接可用且 `list_mcp_tools` 探测成功
- **THEN** Agent 优先使用 IDE 原生 MCP 工具调用
- **THEN** Agent 不自动运行备用 MCP 客户端脚本

#### Scenario: 原生 MCP 调用失败
- **WHEN** IDE 原生 MCP 连接不可用、Token 失效或连接未加载
- **THEN** Agent 可以使用资源包内的 `xlpa/tools/mcp_client.py` 执行备用 MCP 调用
- **THEN** 备用调用必须读取本地客户端 MCP 配置中的端点和 Token，或通过用户确认的参数覆盖

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
系统 SHALL 在接入页和 `/xlpa` Skill 文档中清晰区分资源包分发、首次安装、后续更新、运行时 MCP 调用和备用客户端调用；首次安装说明 SHALL 引导目标工具内的 Agent 直接把 MCP server 写入其真实配置文件（零脚本），并 SHALL 在验证失败时提供手动粘贴兜底。

#### Scenario: 接入页生成说明
- **WHEN** 接入页生成接入文本
- **THEN** 文本说明资源包下载地址、解压目标、manifest 校验点和备用 MCP 客户端位置
- **THEN** 文本必须根据当前选择的目标平台生成对应 MCP JSON 配置
- **THEN** 文本必须给出针对所选平台的真实配置文件路径与由 Agent 直接写入/合并的操作说明（幂等、保留其它 server、损坏先备份）
- **THEN** 文本必须要求写入后调用 `list_mcp_tools` 验证，失败时回退到该平台可手动粘贴的 JSON 片段与文件路径
- **THEN** 文本不得暗示安装后会在无人触发的情况下自动常驻运行 Python 脚本
- **THEN** 文本不得继续以 PCA 作为主入口名称

#### Scenario: Skill 前置检查说明
- **WHEN** `/xlpa` Skill 执行前置检查
- **THEN** Skill 明确优先使用 IDE 原生 MCP 工具调用
- **THEN** Skill 仅在原生 MCP 调用失败时提示或使用资源包内备用 MCP 客户端
- **THEN** Skill 更新流程覆盖 manifest 声明的所有资源，而不只覆盖 `SKILL.md`

### Requirement: 资源包不得内嵌工具专属注册程序
系统 SHALL 以**文本驱动**方式支持 MCP 客户端接入，由目标工具内的 Agent 依据接入说明直接写入其配置文件；资源包 MUST NOT 内嵌为某一具体 IDE 定制的注册程序，也 MUST NOT 因接入需要而把服务端资源包发布源置于该 IDE 目录下。

#### Scenario: 备用客户端仍是唯一随包工具
- **WHEN** 服务端生成资源包
- **THEN** 资源包继续包含备用 MCP 客户端 `xlpa/tools/mcp_client.py`
- **THEN** 资源包不得新增仅服务某 IDE 的注册可执行程序

#### Scenario: 打包源保持工具中立
- **WHEN** 服务端打包 Agent 资源包
- **THEN** 打包源必须为中性目录 `agent_assets/skills`，与客户端最终安装目录（按平台区分）解耦

### Requirement: 版本信息必须来自配置和 manifest
系统 SHALL 从明确的事实源读取 MCP Server 版本和 Agent 资源包版本；用户可见输出不得继续使用代码硬编码版本作为事实源。

#### Scenario: 展示 MCP Server 版本
- **WHEN** 用户调用 list_mcp_tools、访问接入页或执行 `/xlpa` 前置检查
- **THEN** 系统必须从服务端版本配置读取 MCP Server 版本
- **THEN** 如果版本配置缺失或无效，系统必须展示无法比较的原因

#### Scenario: 展示资源包版本
- **WHEN** 用户检查资源包版本或下载资源包
- **THEN** 系统必须从资源包 manifest 读取资源包版本
- **THEN** 系统不得以 MCP Server 版本替代资源包版本

### Requirement: 资源包更新成功后必须清理不可复用备份
系统 SHALL 在资源包更新完成、manifest 校验成功且用户确认新版可用后删除旧版本备份；系统 SHALL 保留仍可用于回滚或审计的备份，直到其不再需要。

#### Scenario: 更新后校验失败
- **WHEN** 资源包覆盖后 manifest 校验失败
- **THEN** 系统必须保留旧版本备份
- **THEN** 系统必须报告缺失项、失败原因和备份路径

#### Scenario: 用户确认新版可用
- **WHEN** 资源包更新完成、manifest 校验成功且用户确认新版可用
- **THEN** 系统必须删除本次更新产生且后续不可复用的旧版本备份
- **THEN** 系统必须保留用户输入、结果产物、审计产物和可复用缓存

#### Scenario: 清理临时产物
- **WHEN** 更新流程结束
- **THEN** 系统可以删除临时下载包、临时解压目录和无复用价值的安装残留
- **THEN** 系统不得删除可用于回滚、审计或后续复用的产物
