## MODIFIED Requirements

### Requirement: PCA 入口必须执行前置状态检查
系统 SHALL 在 `/pca` 入口开始业务流程前执行前置状态检查，至少包括 MCP 连接状态、当前 MCP 权限级别、本地后端业务 Token 是否存在、MCP Server 版本、远端 Agent 资源包版本、本地 Agent 资源包版本、版本兼容风险和后续流程可用性提示。

#### Scenario: MCP 探测成功
- **WHEN** 用户发起 `/pca` 需求且 MCP 连接可用
- **THEN** 系统必须展示当前 MCP 服务名、工具数量、`access_level`、请求来源和 MCP Server 版本
- **THEN** 系统必须展示远端 Agent 资源包版本、本地 Agent 资源包版本或无法比较的原因
- **THEN** 系统必须说明当前权限对只读查询、本地 JSON 生成、平台新增和平台同步的影响

#### Scenario: MCP 探测失败
- **WHEN** 用户发起 `/pca` 需求但 MCP 连接或鉴权探测失败
- **THEN** 系统必须展示失败原因或错误返回
- **THEN** 系统不得声称平台查询、平台写入或 Agent 资源包更新已完成
- **THEN** 系统可以继续执行仅依赖本地文件的协议分析流程，并必须标注本地来源

#### Scenario: 版本存在兼容风险
- **WHEN** 本地 Agent 资源包版本低于远端版本或缺少当前流程所需特性
- **THEN** 系统必须提示版本兼容风险和可能缺失的能力
- **THEN** 系统必须说明当前任务是否仍可继续
- **THEN** 系统不得把版本更新作为默认执行动作

### Requirement: PCA 入口必须提供全量 Skills 更新操作
系统 SHALL 在 `/pca` 入口提供检查并更新本地 Agent 资源包的操作；更新范围为全部 `.trae/skills`，更新前必须备份，用户确认后允许覆盖本地 Skills，更新后必须提示重新加载会话或重启客户端以生效。

#### Scenario: 用户选择检查 Skills 更新
- **WHEN** 用户在 `/pca` 入口选择检查或更新本地 Agent 资源包
- **THEN** 系统必须读取本地资源包和 Skill 版本信息
- **THEN** 系统必须从 MCP Server 获取可用的远端 Agent 资源包版本、manifest 校验状态和兼容性信息
- **THEN** 系统必须展示本地版本、远端版本、manifest 校验状态或无法比较的原因

#### Scenario: 发现可选更新
- **WHEN** 本地版本低于远端版本但当前任务不依赖新能力
- **THEN** 系统必须提示存在可选更新
- **THEN** 系统不得强制用户先更新才能继续当前任务

#### Scenario: 当前任务依赖新能力
- **WHEN** 当前任务需要本地资源包尚不支持的能力
- **THEN** 系统必须提示建议先更新资源包
- **THEN** 系统必须展示不更新继续执行的风险或受限范围

#### Scenario: 用户确认全量更新
- **WHEN** 用户确认更新本地 Agent 资源包
- **THEN** 系统必须先备份当前 `.trae/skills` 目录
- **THEN** 系统必须下载远端 Agent 资源包 ZIP 并覆盖更新全部本地 Skills
- **THEN** 系统必须验证关键 Skill 目录、manifest 声明的必需文件和 `agents/openai.yaml` 存在
- **THEN** 系统必须提示用户重新加载 `/pca` 会话或重启客户端以使用新版 Skill

#### Scenario: 用户未确认更新
- **WHEN** 系统展示 Agent 资源包更新计划但用户未明确确认
- **THEN** 系统不得覆盖、删除或移动本地 `.trae/skills` 内容
- **THEN** 系统可以继续执行当前已安装版本支持的流程，并必须提示可能存在版本差异

### Requirement: PCA 入口输出必须给出用户可执行下一步
系统 SHALL 在 `/pca` 前置检查和任一子流程结束时输出用户可执行的下一步建议，且建议必须与当前登录状态、权限级别、版本状态、产物状态和用户选择一致。

#### Scenario: 本地配置已生成但未同步平台
- **WHEN** 协议转换流程生成本地 JSON 且用户未确认平台同步
- **THEN** `/pca` 汇总输出必须说明本地文件路径、平台同步未执行、未调用写入工具
- **THEN** `/pca` 必须给出后续可选操作，例如测试验证、打包分发或在 system 权限下同步平台

#### Scenario: 当前权限为 user
- **WHEN** 当前 MCP `access_level` 为 `user`
- **THEN** `/pca` 必须说明平台写入不可用
- **THEN** `/pca` 不得展示平台新增或平台同步的确认选项
- **THEN** 如用户请求写入或同步，系统必须提示需要在服务器本机以 system 权限执行

#### Scenario: 当前存在可选更新
- **WHEN** 前置检查发现本地 Agent 资源包落后于远端但当前任务可继续
- **THEN** `/pca` 必须将更新作为可选下一步展示
- **THEN** `/pca` 不得用更新提示阻塞当前已可执行的只读查询或本地生成流程

## ADDED Requirements

### Requirement: PCA 入口必须展示能力矩阵
系统 SHALL 在前置检查后展示当前会话能力矩阵，用于说明 MCP 工具调用、平台只读查询、本地 references 分析、本地 JSON 生成、平台新增、平台同步和资源包更新是否可用。

#### Scenario: system 权限能力矩阵
- **WHEN** 当前 MCP `access_level` 为 `system`
- **THEN** 能力矩阵必须显示只读查询和本地 JSON 生成为可用
- **THEN** 能力矩阵必须显示平台新增和平台同步为可确认后执行
- **THEN** 能力矩阵必须说明写入仍需要用户逐项确认

#### Scenario: user 权限能力矩阵
- **WHEN** 当前 MCP `access_level` 为 `user`
- **THEN** 能力矩阵必须显示只读查询和本地 JSON 生成为可用
- **THEN** 能力矩阵必须显示平台新增和平台同步为不可用
- **THEN** 能力矩阵不得把后端业务 Token 展示为写入授权来源

#### Scenario: 未登录业务 Token
- **WHEN** 当前没有可用后端业务 Token
- **THEN** 能力矩阵必须说明需要业务 Token 的平台查询不可用
- **THEN** 能力矩阵必须说明不依赖业务 Token 的本地分析仍可继续
