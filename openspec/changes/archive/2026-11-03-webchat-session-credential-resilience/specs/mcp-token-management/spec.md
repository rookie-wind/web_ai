# mcp-token-management Delta

## MODIFIED Requirements

### Requirement: Token Registry 必须保留管理元数据

系统 SHALL 为每个持久化接入 Token 记录必要管理元数据，至少包括来源标识
（IP）、Token（作为主键）、创建时间、最后访问时间、撤销状态、凭据族别
（family：`ide` | `webchat`）；webchat 族 MUST 额外记录 owner_ref、
expires_at（TTL 到期时间）与签发窗口（用于滑动续期）。签发窗口 MUST 随 registry
持久化，并在加载/归一化（`_normalize_entry`）后原样保留；仅对从未记录窗口的
历史条目才允许一次性按「到期-创建」回推，MUST NOT 因归一化丢失已有窗口而令
续期退化为复利放大。registry MUST 携带
schema_version 以支持结构迁移。元数据中的权限级别仅表达 user-only 接入语义，
不构成云端平台写权限来源。webchat 族接入凭据 SHALL 采用滑动续期：每次通过
`/mcp` 鉴权即按签发窗口顺延 `expires_at`，但不超过绝对寿命上限
（创建时间 + 可配置 TTL 上限），使持续活跃的长会话不会中途失效；停止活动
满一个窗口后自然到期。IDE 族凭据 `expires_at` 为空，保持长期有效语义、
不参与续期。

#### Scenario: 访问已存在 Token

- **WHEN** 已记录来源再次访问接入信息接口或使用 Token 调用 MCP
- **THEN** 系统必须更新该记录的最后访问时间
- **THEN** 系统不得改变该 Token 值
- **THEN** 系统必须保持接入级别语义为 user
- **THEN** webchat 族该次访问同时按签发窗口滑动续期 `expires_at`（封顶绝对
  寿命）；IDE 族不受影响

#### Scenario: Token 被撤销

- **WHEN** 某来源的 Token 记录被标记为撤销
- **THEN** 系统必须拒绝该 Token 的 MCP 鉴权
- **THEN** IDE 族来源再次访问接入信息接口时可以获得新的 user Token；
  webchat 族凭据的撤销由签发方（webchat 后端）在会话结束时触发

#### Scenario: webchat 族凭据到期

- **WHEN** webchat 族 Token 超过 expires_at 后用于 MCP 鉴权
- **THEN** 系统必须拒绝该 Token（与撤销同等对待）

#### Scenario: webchat 族凭据随活动滑动续期

- **WHEN** 未过期的 webchat 族 Token 一次通过 /mcp 鉴权（更新最后访问时间）
- **THEN** 系统 SHALL 把其 expires_at 按签发窗口顺延（滑动续期），
  使持续活跃的长会话不会中途失效
- **THEN** 续期后的 expires_at MUST NOT 超过绝对寿命上限
  （创建时间 + 可配置 TTL 上限）；IDE 族（expires_at 为空）不参与续期

#### Scenario: 清理长期未使用 Token

- **WHEN** 管理流程清理长期未使用的 Token 记录
- **THEN** 系统必须只清理满足过期或撤销条件的 user Token
- **THEN** 系统不得清理 MCP_AUTH_TOKEN 环境变量配置
- **THEN** 系统不得把清理 MCP 接入 Token 解释为撤销云端业务账号或边缘建档账号

#### Scenario: 签发窗口随 registry 重载保留

- **WHEN** 服务重启或 registry 重新加载归一化后，已带签发窗口的 webchat 族
  凭据再次用于滑动续期
- **THEN** 系统仍按原签发窗口顺延 expires_at（`ttl_seconds` 在归一化中被保留、
  未丢失）
- **THEN** 系统 MUST NOT 因窗口字段缺失而回退为按「到期时间-创建时间」推算
  （该推算会随每次顺延复利放大直至撞绝对封顶）；仅未记录过窗口的历史条目走一次性回推
