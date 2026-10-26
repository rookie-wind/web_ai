## Purpose

定义 `/pca` 作为协议转换统一入口时必须具备的前置检查、后端业务 Token 本地复用、Skills 全量更新、IPv4 接入展示与权限提示行为，使用户每次进入协议转换流程前都能获得一致、可理解、可验证的运行状态。

## ADDED Requirements

### Requirement: PCA 入口必须执行前置状态检查
系统 SHALL 在 `/pca` 入口开始业务流程前执行前置状态检查，至少包括 MCP 连接状态、当前 MCP 权限级别、本地后端业务 Token 是否存在、Skills 版本状态和后续流程可用性提示。

#### Scenario: MCP 探测成功
- **WHEN** 用户发起 `/pca` 需求且 MCP 连接可用
- **THEN** 系统必须展示当前 MCP 服务名、工具数量、`access_level` 和请求来源
- **THEN** 系统必须说明当前权限对只读查询和平台写入的影响

#### Scenario: MCP 探测失败
- **WHEN** 用户发起 `/pca` 需求但 MCP 连接或鉴权探测失败
- **THEN** 系统必须展示失败原因或错误返回
- **THEN** 系统不得声称平台查询、平台写入或 Skills 更新已完成
- **THEN** 系统可以继续执行仅依赖本地文件的协议分析流程，并必须标注本地来源

### Requirement: PCA 入口必须按本地业务 Token 状态提示登录
系统 SHALL 区分 MCP 接入 Token 与后端业务 Token，并 SHALL 在没有可用本地后端业务 Token 时提示用户提供 `login(phoneNum, code)` 登录参数；获取一次 Token 后 SHALL 保存到本地供后续 `/pca` 会话复用。

#### Scenario: 本地已有业务 Token
- **WHEN** 用户发起 `/pca` 需求且本地存在后端业务 Token
- **THEN** 系统不得重复要求用户输入 `phoneNum` 和 `code`
- **THEN** 系统必须优先使用本地业务 Token 调用只读平台查询工具
- **THEN** 如果任一平台工具返回认证失效，系统必须丢弃或标记该 Token 失效，并重新提示用户登录

#### Scenario: 本地没有业务 Token
- **WHEN** 用户发起 `/pca` 需求且本地不存在后端业务 Token
- **THEN** 系统必须提示用户可提供 `phoneNum` 和 `code` 以启用平台查询
- **THEN** 用户未提供登录参数时，系统必须说明本次仅使用本地 references 或不需要登录的流程
- **THEN** 系统不得调用需要后端业务 Token 的 MCP 工具

#### Scenario: 登录成功并保存 Token
- **WHEN** 用户提供 `phoneNum` 和 `code` 且 `login` 返回成功
- **THEN** 系统必须将返回的后端业务 Token 保存到本地缓存
- **THEN** 系统必须说明该 Token 仅作为后端 API 工具的 `token` 参数使用
- **THEN** 系统不得把后端业务 Token 写入 MCP 配置或作为 `Authorization: Bearer` 使用

#### Scenario: 登录失败
- **WHEN** `login(phoneNum, code)` 返回失败、网络错误或业务错误
- **THEN** 系统必须展示错误返回
- **THEN** 系统不得创建或复用新的本地业务 Token
- **THEN** 系统必须等待用户决定重试、跳过登录或停止

### Requirement: PCA 入口必须提供全量 Skills 更新操作
系统 SHALL 在 `/pca` 入口提供检查并更新本地 Skills 的操作；更新范围为全部 `.trae/skills`，更新前必须备份，用户确认后允许覆盖本地 Skills，更新后必须提示重新加载会话或重启客户端以生效。

#### Scenario: 用户选择检查 Skills 更新
- **WHEN** 用户在 `/pca` 入口选择检查或更新本地 Skills
- **THEN** 系统必须读取本地 Skills 版本信息
- **THEN** 系统必须从 MCP Server 获取可用的远端 Skills 包或版本信息
- **THEN** 系统必须展示本地版本、远端版本或无法比较的原因

#### Scenario: 用户确认全量更新
- **WHEN** 用户确认更新本地 Skills
- **THEN** 系统必须先备份当前 `.trae/skills` 目录
- **THEN** 系统必须下载远端 Skills ZIP 并覆盖更新全部本地 Skills
- **THEN** 系统必须验证关键 Skill 目录和 `agents/openai.yaml` 存在
- **THEN** 系统必须提示用户重新加载 `/pca` 会话或重启客户端以使用新版 Skill

#### Scenario: 用户未确认更新
- **WHEN** 系统展示 Skills 更新计划但用户未明确确认
- **THEN** 系统不得覆盖、删除或移动本地 `.trae/skills` 内容
- **THEN** 系统可以继续执行当前已安装版本支持的流程，并必须提示可能存在版本差异

### Requirement: 用户可见接入信息必须使用 IPv4
系统 SHALL 在接入页面、配置片段、Skills 下载链接和 `/pca` 输出中优先使用 IPv4 地址，并 SHALL NOT 在用户可复制的接入配置中生成 IPv6 地址；服务端内部可以继续识别 IPv6 localhost 以保持兼容。

#### Scenario: 生成接入配置
- **WHEN** 系统为用户生成 MCP 接入配置或 Skills 下载链接
- **THEN** 配置中的 URL 必须使用 `127.0.0.1`、`localhost` 或局域网 IPv4 地址
- **THEN** 配置中不得出现形如 `[::1]` 或包含冒号分段的 IPv6 主机地址

#### Scenario: 服务器检测到 IPv6 localhost
- **WHEN** 请求来源为 IPv6 localhost
- **THEN** 系统可以按 localhost 判定权限
- **THEN** 系统对用户展示或复制的 baseUrl 仍必须使用 IPv4 或 `localhost` 表达

### Requirement: PCA 入口输出必须给出用户可执行下一步
系统 SHALL 在 `/pca` 前置检查和任一子流程结束时输出用户可执行的下一步建议，且建议必须与当前登录状态、权限级别、产物状态和用户选择一致。

#### Scenario: 本地配置已生成但未同步平台
- **WHEN** 协议转换流程生成本地 JSON 且用户未确认平台同步
- **THEN** `/pca` 汇总输出必须说明本地文件路径、平台同步未执行、未调用写入工具
- **THEN** `/pca` 必须给出后续可选操作，例如测试验证、打包分发或在 system 权限下同步平台

#### Scenario: 当前权限为 user
- **WHEN** 当前 MCP `access_level` 为 `user`
- **THEN** `/pca` 必须说明平台写入不可用
- **THEN** 如用户请求写入或同步，系统必须提示需要在服务器本地以 system 权限执行
