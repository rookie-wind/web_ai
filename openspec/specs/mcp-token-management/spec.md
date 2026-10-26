## Purpose

定义 MCP 接入 Token 的按 IP 分配、user-only 语义、持久化、重启复用、v1→v2 迁移和安全边界；接入 Token 仅用于连接 MCP endpoint，云端平台写权限由业务登录会话单独判定。

## Requirements

### Requirement: User Token 必须按 IP 固定分配
系统 SHALL 将 MCP 接入 Token 作为用户级接入凭据进行分配和持久化；同一访问来源再次访问接入信息时 SHOULD 返回同一个未撤销 Token。MCP 接入 Token SHALL NOT 因 localhost、本机 IP 或管理员 Token 而授予云端平台写权限；写权限由登录后的 session role 决定，与 Token 来源无关。

#### Scenario: 同一 IP 再次访问接入页
- **WHEN** 同一 IP 多次访问接入信息接口
- **THEN** 系统必须返回同一个未撤销 MCP 接入 Token，除非该 Token 已撤销或 registry 损坏
- **THEN** 系统必须将该 Token 的接入级别标记为 user
- **THEN** 系统不得因该 IP 是 localhost 或本机网卡 IP 而将该 Token 标记为 system

#### Scenario: 新 IP 首次访问接入页
- **WHEN** 一个未记录的 IP 首次访问接入信息接口
- **THEN** 系统必须为该 IP 生成新的 user Token
- **THEN** 系统必须保存该 IP 与 Token 的绑定关系或等价的可复用登记信息

#### Scenario: 本机 IP 获取管理员 Token
- **WHEN** 请求来源为本机 IP 或 localhost
- **THEN** 系统必须返回管理员配置 Token（`MCP_AUTH_TOKEN`）或该 IP 已登记的接入 Token，并持久化登记（source=admin）
- **THEN** 该 Token 与远端 Token 权限完全相同（仅用于连接，不直接授予写权限）
- **THEN** 系统必须说明云端平台写权限需要业务登录账号命中超级账号配置

### Requirement: User Token 必须在服务器重启后继续有效
系统 SHALL 持久化 user-only MCP Token Registry，并 SHALL 在 MCP Server 重启后加载该绑定关系用于接入页展示和 Bearer Token 校验。

#### Scenario: 重启后使用旧 Token 调用 MCP
- **WHEN** MCP Server 重启且 Token Registry 中存在未撤销 Token
- **THEN** 使用该 Token 的 MCP 请求必须通过鉴权
- **THEN** 该请求的 MCP 接入级别仍必须为 user
- **THEN** 该请求不得因来源 IP 是 localhost 而自动获得云端平台写权限

#### Scenario: 重启后访问接入页
- **WHEN** MCP Server 重启后同一来源再次访问接入页
- **THEN** 接入页必须展示重启前为该来源分配的同一个未撤销 Token，或展示稳定配置 Token
- **THEN** 接入页必须说明该 Token 仅用于 MCP 接入

#### Scenario: Token Registry 不存在
- **WHEN** MCP Server 启动时 Token Registry 不存在
- **THEN** 系统必须创建空的 user-only Token 绑定状态或按首次访问延迟创建
- **THEN** 系统不得因此阻止 MCP_AUTH_TOKEN 或新 user Token 的接入验证

### Requirement: Token Registry 必须保留管理元数据
系统 SHALL 为每个持久化接入 Token 记录必要管理元数据，至少包括来源标识（IP）、Token、创建时间、最后访问时间和撤销状态；registry MUST 携带 schema_version 以支持结构迁移。元数据中的权限级别仅表达 user-only 接入语义，不构成云端平台写权限来源。

#### Scenario: 访问已存在 Token
- **WHEN** 已记录来源再次访问接入信息接口或使用 Token 调用 MCP
- **THEN** 系统必须更新该记录的最后访问时间
- **THEN** 系统不得改变该 Token 值
- **THEN** 系统必须保持接入级别语义为 user

#### Scenario: Token 被撤销
- **WHEN** 某来源的 Token 记录被标记为撤销
- **THEN** 系统必须拒绝该 Token 的 MCP 鉴权
- **THEN** 该来源再次访问接入信息接口时可以获得新的 user Token

#### Scenario: 清理长期未使用 Token
- **WHEN** 管理流程清理长期未使用的 Token 记录
- **THEN** 系统必须只清理满足过期或撤销条件的 user Token
- **THEN** 系统不得清理 MCP_AUTH_TOKEN 环境变量配置
- **THEN** 系统不得把清理 MCP 接入 Token 解释为撤销云端业务账号或边缘建档账号

### Requirement: Token Registry 必须作为本地敏感运行态文件处理
系统 SHALL 将 Token Registry 视为本地敏感运行态文件，不得将其打入 Agent 资源包，不得在用户可复制说明中暴露其他 IP 的 Token。

#### Scenario: 导出 Agent 资源包
- **WHEN** 系统生成 Agent 资源包 ZIP
- **THEN** ZIP 中不得包含 Token Registry 文件
- **THEN** ZIP 中不得包含任何已分配 user Token 清单

#### Scenario: 生成接入页信息
- **WHEN** 用户访问接入页或接入信息接口
- **THEN** 系统只展示当前访问来源对应的 Token
- **THEN** 系统不得展示其他 IP 的 Token 或完整 Token Registry 内容

#### Scenario: 版本控制安全
- **WHEN** 项目生成或更新 Token Registry 文件
- **THEN** 该文件必须被视为不得提交到版本控制的本地文件
- **THEN** 文档必须提示该文件包含敏感 Token 信息

### Requirement: Token Registry 必须支持 v1 到 v2 迁移
系统 SHALL 在启动时检测旧版 `.token_registry.json`，并 SHALL 将旧 registry 迁移为 user-only v2 结构；迁移前必须备份旧文件，迁移后不得保留可授予 system 权限的 registry 语义。

#### Scenario: 发现旧版 registry
- **WHEN** 系统启动时发现 `.token_registry.json` 缺少 v2 schema_version 或包含旧版 accessLevel 语义
- **THEN** 系统必须先创建旧文件备份
- **THEN** 系统必须将有效未撤销 Token 迁移为 user 级记录
- **THEN** 系统必须移除或忽略所有 system、localhost、admin 权限来源字段

#### Scenario: 旧 registry 损坏
- **WHEN** 旧 `.token_registry.json` 无法解析
- **THEN** 系统必须保留损坏文件的备份或错误说明
- **THEN** 系统必须创建空的 user-only v2 registry
- **THEN** 系统不得因为 registry 损坏而授予 system 权限

#### Scenario: 迁移后鉴权
- **WHEN** 迁移后的 Token 被用于 MCP 请求
- **THEN** 系统必须只将其视为 user 级 MCP 接入凭据
- **THEN** 云端平台写权限必须由业务登录账号和超级账号配置单独判断

### Requirement: 云端平台写权限必须独立于 MCP 接入 Token
系统 SHALL 使用云端业务登录状态和本地超级账号配置判断云端平台写权限；MCP 接入 Token 仅用于访问 MCP endpoint，不得作为云端平台写入授权来源。

#### Scenario: MCP Token 有效但未登录业务账号
- **WHEN** MCP 接入 Token 验证通过但当前没有云端业务会话
- **THEN** 系统可以允许不依赖业务登录的 MCP 工具和本地流程
- **THEN** 系统不得允许云端平台写入工具执行

#### Scenario: 业务账号未命中超级账号表
- **WHEN** 用户已登录云端业务账号但账号未命中本地超级账号配置
- **THEN** 系统必须允许云端只读查询
- **THEN** 系统不得允许云端平台写入工具执行

#### Scenario: 业务账号命中超级账号表
- **WHEN** 用户已登录云端业务账号且账号命中本地超级账号配置
- **THEN** 系统可以将云端平台写入标记为可确认后执行
- **THEN** 系统仍必须要求用户对每个写入计划进行确认
