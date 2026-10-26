## MODIFIED Requirements

### Requirement: User Token 必须按 IP 固定分配
系统 SHALL 将非本机访问者的 MCP 接入 Token 与客户端 IP 绑定；同一 IP 再次访问接入信息时必须返回同一个未撤销 Token。MCP 接入 Token 仅作为 session 标识和连接凭据，不携带任何权限级别语义。

#### Scenario: 同一 IP 再次访问接入页
- **WHEN** 同一非本机 IP 多次访问接入信息接口
- **THEN** 系统必须返回同一个接入 Token
- **THEN** 系统不得在 Token 元数据中存储权限级别字段

#### Scenario: 新 IP 首次访问接入页
- **WHEN** 一个未记录的非本机 IP 首次访问接入信息接口
- **THEN** 系统必须为该 IP 生成新的接入 Token
- **THEN** 系统必须保存该 IP 与 Token 的绑定关系

#### Scenario: 本机 IP 获取管理员 Token
- **WHEN** 请求来源为本机 IP 或 localhost
- **THEN** 系统必须返回配置的 MCP_AUTH_TOKEN 作为接入凭据
- **THEN** 该 Token 与远端 Token 权限完全相同（仅用于连接，不直接授予写权限）
- **THEN** 写权限由 login 后的 session role 决定，与 Token 来源无关

### Requirement: Token Registry 必须保留管理元数据
系统 SHALL 为每个持久化接入 Token 记录必要管理元数据，至少包括 IP、Token、创建时间、最后访问时间和撤销状态。元数据中不得包含权限级别（access_level）字段。

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
- **THEN** 系统必须只清理满足过期或撤销条件的接入 Token
- **THEN** 系统不得清理 MCP_AUTH_TOKEN 环境变量配置

## REMOVED Requirements

### Requirement: User Token 必须在服务器重启后继续有效
**Reason**: Token 持久化行为不变，但本需求中"按来源 IP 判定为 user 权限"的措辞与新模型冲突（权限不再由 Token/IP 决定）。持久化能力保留在"Token Registry 必须保留管理元数据"中。
**Migration**: Token 持久化和重启复用逻辑保留不变；权限判定迁移至 client-session-permission capability 中通过 login session role 实现。
