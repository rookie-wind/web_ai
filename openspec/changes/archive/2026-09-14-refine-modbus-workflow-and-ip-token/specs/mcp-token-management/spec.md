## Purpose

定义 MCP 接入 Token 的按 IP 固定分配、持久化、重启复用、撤销预留和安全边界，使远程用户在服务器重启后不需要重复更新客户端接入配置。

## ADDED Requirements

### Requirement: User Token 必须按 IP 固定分配
系统 SHALL 将非本机访问者的 MCP 接入 Token 与客户端 IP 绑定；同一 IP 再次访问接入信息时必须返回同一个未撤销 Token。

#### Scenario: 同一 IP 再次访问接入页
- **WHEN** 同一非本机 IP 多次访问接入信息接口
- **THEN** 系统必须返回同一个 user Token
- **THEN** 系统必须将该 Token 的权限标记为 user

#### Scenario: 新 IP 首次访问接入页
- **WHEN** 一个未记录的非本机 IP 首次访问接入信息接口
- **THEN** 系统必须为该 IP 生成新的 user Token
- **THEN** 系统必须保存该 IP 与 Token 的绑定关系

#### Scenario: 本机 IP 获取管理员 Token
- **WHEN** 请求来源为本机 IP 或 localhost
- **THEN** 系统必须继续返回管理员 Token 或系统级接入信息
- **THEN** 系统不得把本机管理员 Token 作为普通 user Token 写入 IP Token 绑定表

### Requirement: User Token 必须在服务器重启后继续有效
系统 SHALL 持久化非本机 IP 的 user Token 绑定关系，并 SHALL 在 MCP Server 重启后加载该绑定关系用于接入页展示和 Bearer Token 校验。

#### Scenario: 重启后使用旧 Token 调用 MCP
- **WHEN** MCP Server 重启且 Token Registry 中存在某 IP 的未撤销 Token
- **THEN** 使用该 Token 的 MCP 请求必须通过鉴权
- **THEN** 该请求仍必须按来源 IP 判定为 user 权限

#### Scenario: 重启后访问接入页
- **WHEN** MCP Server 重启后同一非本机 IP 再次访问接入页
- **THEN** 接入页必须展示重启前为该 IP 分配的同一个 Token
- **THEN** 接入页必须说明该 Token 绑定当前访问 IP

#### Scenario: Token Registry 不存在
- **WHEN** MCP Server 启动时 Token Registry 不存在
- **THEN** 系统必须创建空的 Token 绑定状态或按首次访问延迟创建
- **THEN** 系统不得因此阻止管理员 Token 或本机访问

### Requirement: Token Registry 必须保留管理元数据
系统 SHALL 为每个持久化 user Token 记录必要管理元数据，至少包括 IP、Token、权限级别、创建时间、最后访问时间和撤销状态。

#### Scenario: 访问已存在 Token
- **WHEN** 已记录 IP 再次访问接入信息接口或使用 Token 调用 MCP
- **THEN** 系统必须更新该记录的最后访问时间
- **THEN** 系统不得改变该 IP 的 Token 值

#### Scenario: Token 被撤销
- **WHEN** 某 IP 的 Token 记录被标记为撤销
- **THEN** 系统必须拒绝该 Token 的 MCP 鉴权
- **THEN** 该 IP 再次访问接入信息接口时可以获得新的 Token

#### Scenario: 清理长期未使用 Token
- **WHEN** 管理流程清理长期未使用的 Token 记录
- **THEN** 系统必须只清理满足过期或撤销条件的 user Token
- **THEN** 系统不得清理管理员 Token 配置

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
