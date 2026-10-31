## Purpose

（delta 变更，主规格 Purpose 不变：MCP 接入 Token 的分配、user-only 语义、
持久化、重启复用、迁移与安全边界。本 delta 将 Registry 主键从 IP 改为
Token 并引入凭据族别。）

## MODIFIED Requirements

### Requirement: User Token 必须按 IP 固定分配

系统 SHALL 将 MCP 接入 Token 作为用户级接入凭据进行分配和持久化；Registry
主键 SHALL 为 Token 本身（v3 结构）：entries 以 Token 为键，来源 IP、凭据
族别（family）、归属引用（owner_ref）、有效期与撤销状态降为记录属性。
IDE 族凭据 SHALL 保持"同一来源再次访问接入信息时返回同一个未撤销 Token"
的复用语义；同一 IP SHALL 允许多把未撤销凭据并存（webchat 族按会话签发，
互不顶替）。MCP 接入 Token SHALL NOT 因 localhost、本机 IP 或管理员 Token
而授予云端平台写权限；写权限由登录后的 session role 决定，与 Token 来源无关。

#### Scenario: 同一 IP 再次访问接入页

- **WHEN** 同一 IP 多次访问接入信息接口
- **THEN** 系统必须返回该 IP 已登记的同一个未撤销 IDE 族 Token，除非该
  Token 已撤销或 registry 损坏
- **THEN** 系统必须将该 Token 的接入级别标记为 user
- **THEN** 系统不得因该 IP 是 localhost 或本机网卡 IP 而将该 Token 标记为 system

#### Scenario: 新 IP 首次访问接入页

- **WHEN** 一个未记录的 IP 首次访问接入信息接口
- **THEN** 系统必须为该 IP 生成新的 user Token（IDE 族）
- **THEN** 系统必须保存来源 IP 与 Token 的绑定属性（可复用登记信息）

#### Scenario: 同 IP 多凭据并存

- **WHEN** 同一来源 IP 既存在 IDE 族凭据，又通过 mint 端点签发了 webchat
  族凭据
- **THEN** 两把凭据同时有效、互不顶替
- **THEN** 新签发的 webchat 凭据 MUST NOT 使既有 IDE 凭据失效

#### Scenario: 本机 IP 获取管理员 Token

- **WHEN** 请求来源为本机 IP 或 localhost
- **THEN** 系统必须返回管理员配置 Token（`MCP_AUTH_TOKEN`）或该 IP 已登记的 IDE 族接入 Token，并持久化登记（source=admin）
- **THEN** 该 Token 与远端 Token 权限完全相同（仅用于连接，不直接授予写权限）
- **THEN** 系统必须说明云端平台写权限需要业务登录账号命中超级账号配置

### Requirement: Token Registry 必须保留管理元数据

系统 SHALL 为每个持久化接入 Token 记录必要管理元数据，至少包括来源标识
（IP）、Token（作为主键）、创建时间、最后访问时间、撤销状态、凭据族别
（family：`ide` | `webchat`）；webchat 族 MUST 额外记录 owner_ref 与
expires_at（TTL 到期时间）。registry MUST 携带 schema_version 以支持结构
迁移。元数据中的权限级别仅表达 user-only 接入语义，不构成云端平台写权限
来源。

#### Scenario: 访问已存在 Token

- **WHEN** 已记录来源再次访问接入信息接口或使用 Token 调用 MCP
- **THEN** 系统必须更新该记录的最后访问时间
- **THEN** 系统不得改变该 Token 值
- **THEN** 系统必须保持接入级别语义为 user

#### Scenario: Token 被撤销

- **WHEN** 某来源的 Token 记录被标记为撤销
- **THEN** 系统必须拒绝该 Token 的 MCP 鉴权
- **THEN** IDE 族来源再次访问接入信息接口时可以获得新的 user Token；
  webchat 族凭据的撤销由签发方（webchat 后端）在会话结束时触发

#### Scenario: webchat 族凭据到期

- **WHEN** webchat 族 Token 超过 expires_at 后用于 MCP 鉴权
- **THEN** 系统必须拒绝该 Token（与撤销同等对待）

#### Scenario: 清理长期未使用 Token

- **WHEN** 管理流程清理长期未使用的 Token 记录
- **THEN** 系统必须只清理满足过期或撤销条件的 user Token
- **THEN** 系统不得清理 MCP_AUTH_TOKEN 环境变量配置
- **THEN** 系统不得把清理 MCP 接入 Token 解释为撤销云端业务账号或边缘建档账号

### Requirement: Token Registry 必须支持 v1 到 v2 迁移

系统 SHALL 在启动时检测旧版 `.token_registry.json`（schema_version 非
v3），并 SHALL 将旧 registry 迁移为 Token 主键的 v3 结构；迁移前必须备份
旧文件；迁移时既有有效未撤销 Token MUST 归入 IDE 族并保持可用（长期有效
语义不变）；迁移后不得保留可授予 system 权限的 registry 语义。

#### Scenario: 发现旧版 registry

- **WHEN** 系统启动时发现 `.token_registry.json` 的 schema_version 为 v2
  （或更旧）
- **THEN** 系统必须先创建旧文件备份
- **THEN** 系统必须将全部有效未撤销 Token 迁移为 IDE 族 user 级记录
  （Token 为键、IP 为属性）
- **THEN** 迁移后既有 IDE Token 立即可用于 /mcp 鉴权，行为与迁移前一致

#### Scenario: 旧 registry 损坏

- **WHEN** 旧 `.token_registry.json` 无法解析
- **THEN** 系统必须保留损坏文件的备份或错误说明
- **THEN** 系统必须创建空的 v3 registry
- **THEN** 系统不得因为 registry 损坏而授予 system 权限

#### Scenario: 迁移后鉴权

- **WHEN** 迁移后的 Token 被用于 MCP 请求
- **THEN** 系统必须只将其视为 user 级 MCP 接入凭据
- **THEN** 云端平台写权限必须由业务登录账号和超级账号配置单独判断
