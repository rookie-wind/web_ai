## ADDED Requirements

### Requirement: MCP 接入 Token 必须按主体固定分配
系统 SHALL 以"接入主体"而非访问来源地址作为 MCP 接入 Token 的分配维度；同一主体再次
获取接入信息时 SHOULD 返回同一个未撤销 Token。接入主体对 IDE 接入路径为该访问来源地址，
对 Web 会话路径为该会话的稳定用户引用。MCP 接入 Token SHALL NOT 因 localhost、本机地址
或管理员 Token 而授予云端平台写权限；写权限由登录后的 session role 决定，与 Token 来源
无关。

#### Scenario: 同一来源地址再次访问接入页
- **WHEN** 同一来源地址多次访问接入信息接口
- **THEN** 系统必须返回同一个未撤销 MCP 接入 Token，除非该 Token 已撤销或 registry 损坏
- **THEN** 系统必须将该 Token 的接入级别标记为 user
- **THEN** 系统不得因该地址是 localhost 或本机网卡地址而将该 Token 标记为 system

#### Scenario: 新来源地址首次访问接入页
- **WHEN** 一个未记录的来源地址首次访问接入信息接口
- **THEN** 系统必须为该地址生成新的 user Token
- **THEN** 系统必须保存该地址与 Token 的绑定关系或等价的可复用登记信息

#### Scenario: 本机地址获取管理员 Token
- **WHEN** 请求来源为本机地址或 localhost
- **THEN** 系统必须返回管理员配置 Token（`MCP_AUTH_TOKEN`）或该地址已登记的接入 Token，并持久化登记（source=admin）
- **THEN** 该 Token 与远端 Token 权限完全相同（仅用于连接，不直接授予写权限）
- **THEN** 系统必须说明云端平台写权限需要业务登录账号命中超级账号配置

#### Scenario: 同一来源地址承载多个 Web 会话
- **WHEN** 多个 Web 用户的会话经由同一服务端地址接入
- **THEN** 系统必须为每个会话主体返回各自独立的接入 Token
- **THEN** 系统不得让后签发的 Token 使先前已签发且未撤销的 Token 失效

### Requirement: 系统必须支持为 Web 会话签发短期接入凭据
系统 SHALL 支持由受信调用方为指定 Web 会话主体签发带有效期的接入凭据，并 SHALL 支持按
凭据自身撤销而不影响同主体其它凭据。该签发能力 MUST 仅对持有独立服务凭据且来源在允许
清单内的调用方可用；签发凭据 SHALL 一律为 user 级接入凭据。

#### Scenario: 签发并通过有效期控制
- **WHEN** 受信调用方为某 Web 会话主体签发凭据并请求有效期
- **THEN** 系统必须返回不超过允许上限的有效期
- **THEN** 超过有效期的凭据在 MCP 鉴权时必须被拒绝

#### Scenario: 按凭据撤销
- **WHEN** 撤销某一个 Web 会话的接入凭据
- **THEN** 系统必须只拒绝该凭据
- **THEN** 同一主体的其它未撤销凭据必须继续可用

#### Scenario: 撤销接入凭据不注销业务身份
- **WHEN** Web 会话的接入凭据被撤销或自然过期
- **THEN** 系统不得据此撤销该用户的云端业务账号或边缘建档账号
- **THEN** 该用户归属下的业务产物与审计记录必须仍可回看

#### Scenario: 未获授权的签发请求
- **WHEN** 调用方未持有独立服务凭据或来源不在允许清单内
- **THEN** 系统必须拒绝签发并记录该次尝试

### Requirement: Token Registry 必须支持 v2 到 v3 迁移
系统 SHALL 在启动时检测 `.token_registry.json` 的结构版本，并 SHALL 将以访问来源地址为
主键的 v2 结构迁移为以凭据为主键、来源地址降级为属性的 v3 结构；迁移前 MUST 备份旧文件，
迁移后 MUST 保持既有 IDE 接入凭据继续可用。

#### Scenario: 发现 v2 registry
- **WHEN** 系统启动时发现 registry 的结构版本为 v2
- **THEN** 系统必须先创建旧文件备份
- **THEN** 系统必须以凭据为主键重建登记表，并把来源地址、创建时间、最后访问时间、撤销状态与凭据族别作为属性保留
- **THEN** 系统必须保持迁移前已分配且未撤销的 IDE 接入凭据仍然有效

#### Scenario: v3 registry 无法解析
- **WHEN** `.token_registry.json` 无法解析或结构非法
- **THEN** 系统必须保留损坏文件的备份或错误说明
- **THEN** 系统必须创建空的 user-only registry
- **THEN** 系统不得因为 registry 损坏而授予 system 权限

#### Scenario: 迁移后鉴权语义不变
- **WHEN** 迁移后的凭据被用于 MCP 请求
- **THEN** 系统必须只将其视为 user 级 MCP 接入凭据
- **THEN** 云端平台写权限必须由业务登录账号和超级账号配置单独判断

## MODIFIED Requirements

### Requirement: User Token 必须在服务器重启后继续有效
系统 SHALL 持久化 user-only MCP Token Registry，并 SHALL 在 MCP Server 重启后加载该绑定
关系用于接入页展示和 Bearer Token 校验。IDE 接入凭据 MUST 在重启后继续有效；Web 会话
接入凭据 SHALL 以自身有效期为准，MUST NOT 因 registry 持久化而突破有效期继续可用。

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

#### Scenario: Web 会话凭据在重启后的状态
- **WHEN** MCP Server 重启时存在仍在有效期内且未撤销的 Web 会话接入凭据
- **THEN** 系统必须允许该凭据继续通过鉴权直至其自身有效期结束
- **WHEN** MCP Server 重启时某 Web 会话接入凭据已超过有效期
- **THEN** 系统必须拒绝该凭据，不得因 registry 中仍存在记录而放行

### Requirement: Token Registry 必须保留管理元数据
系统 SHALL 为每个持久化接入凭据记录必要管理元数据，至少包括凭据本身、接入主体引用、
来源标识（地址）、凭据族别（IDE 接入或 Web 会话）、创建时间、有效期、最后访问时间和撤销
状态；registry MUST 携带 schema_version 以支持结构迁移。元数据中的权限级别仅表达
user-only 接入语义，不构成云端平台写权限来源。

#### Scenario: 访问已存在 Token
- **WHEN** 已记录来源再次访问接入信息接口或使用 Token 调用 MCP
- **THEN** 系统必须更新该记录的最后访问时间
- **THEN** 系统不得改变该 Token 值
- **THEN** 系统必须保持接入级别语义为 user

#### Scenario: Token 被撤销
- **WHEN** 某凭据记录被标记为撤销
- **THEN** 系统必须拒绝该凭据的 MCP 鉴权
- **THEN** 对应主体再次获取接入信息时可以获得新的 user Token

#### Scenario: 清理长期未使用 Token
- **WHEN** 管理流程清理长期未使用的 Token 记录
- **THEN** 系统必须只清理满足过期或撤销条件的 user Token
- **THEN** 系统不得清理 MCP_AUTH_TOKEN 环境变量配置
- **THEN** 系统不得把清理 MCP 接入 Token 解释为撤销云端业务账号或边缘建档账号

#### Scenario: 同一主体下多凭据的最后访问时间
- **WHEN** 同一服务端地址上多个 Web 会话凭据分别被使用
- **THEN** 系统必须按凭据各自更新最后访问时间
- **THEN** 系统不得因按地址聚合而让一个凭据的活跃状态掩盖另一个凭据的闲置判定

## REMOVED Requirements

### Requirement: User Token 必须按 IP 固定分配
**Reason**: 以访问来源地址作为唯一分配维度无法承载"同一服务端地址上多个 Web 用户会话"
的场景，会导致同地址后签发的凭据使先前凭据失效，并使会话身份、业务归属与审计记录互相
混淆。
**Migration**: 由新增需求"MCP 接入 Token 必须按主体固定分配"取代。IDE 接入路径的接入
主体仍是访问来源地址，其对外行为（同地址返回同一未撤销 Token、user-only 语义、本机地址
返回管理员 Token）保持不变；Web 会话路径的接入主体为稳定用户引用，并通过"系统必须支持
为 Web 会话签发短期接入凭据"获得按会话分配的凭据。
