## MODIFIED Requirements

### Requirement: Session 按 MCP 接入 Token 绑定
系统 SHALL 维护调用方身份会话（phone、role、fallback_token、loginAt）。IDE 接入路径
SHALL 以 MCP 接入 Token 为 key；Web 会话路径 SHALL 以稳定用户引用为 key，使同一用户的
多个会话共享同一身份判定，且接入凭据轮换或撤销不会丢失已建立的角色判定。session 在服务端
进程生命周期内有效。

#### Scenario: 同一 Token 多次调用工具
- **WHEN** 客户端使用同一 MCP Token 在 login 后连续调用多个云端工具
- **THEN** 系统必须从同一 session 读取权限信息
- **THEN** 不得要求客户端重复 login

#### Scenario: 服务端重启
- **WHEN** MCP Server 进程重启
- **THEN** 所有 session 必须清空
- **THEN** 客户端必须重新 login 后才能使用云端工具

#### Scenario: Web 会话凭据轮换后仍保持角色
- **WHEN** 某 Web 用户的会话接入凭据被重新签发，而该用户此前已完成 login
- **THEN** 系统必须以该用户的稳定用户引用继续提供其 session 的角色判定
- **THEN** 系统不得因接入凭据变化而把该用户降为未登录状态

#### Scenario: 同一用户跨设备共享角色判定
- **WHEN** 同一手机号在两个 Web 会话中分别以各自的接入凭据调用云端工具
- **THEN** 系统必须按同一稳定用户引用读取同一份角色判定
- **THEN** 该用户在任一会话中完成 login 后，另一会话不得再要求其重复登录

## ADDED Requirements

### Requirement: 接入凭据与业务身份必须唯一对应
系统 MUST 保证一个接入凭据上只承载一个业务登录身份，不同业务账号 MUST NOT 共用同一
session；已承载某身份的接入凭据被另一账号用于 login 时，系统 MUST 拒绝而非覆盖既有
身份判定。

#### Scenario: 不同账号先后使用同一接入凭据 login
- **WHEN** 一个已承载账号 A 角色判定的接入凭据被用于账号 B 的 login
- **THEN** 系统必须拒绝该 login 并说明该接入凭据已绑定其它身份
- **THEN** 系统不得把 session 覆盖为账号 B 的角色，使账号 A 的后续调用获得账号 B 的权限

#### Scenario: 同一账号重复 login
- **WHEN** 同一账号在同一接入凭据上重复 login
- **THEN** 系统必须复用或刷新该身份对应的 session，角色判定保持一致

#### Scenario: Web 会话之间凭据天然隔离
- **WHEN** 两个不同 Web 用户各自持有独立签发的接入凭据
- **THEN** 系统必须为二者维护互不可见的 session
- **THEN** 任一用户的写入权限判定不得受另一用户登录状态影响

### Requirement: Web 会话的权限判定必须与实际登录账号一致
系统 SHALL 在 Web 路径上依据稳定用户引用读取角色判定，并 SHALL 在工具调用的审计记录中
同时体现归属主体与承载该次调用的接入凭据族别，使"谁做的"与"用哪把凭据做的"可分别追溯。

#### Scenario: 超级账号从 Web 发起写操作
- **WHEN** 命中超级账号配置的 Web 用户执行写入类工具
- **THEN** 系统必须按该用户 session 的 role 判定放行，并要求一次性授权
- **THEN** 审计记录必须能区分归属主体与该会话使用的接入凭据族别

#### Scenario: 普通账号从 Web 尝试写操作
- **WHEN** 未命中超级账号配置的 Web 用户执行写入类工具
- **THEN** 系统必须返回需要超级账号权限的拒绝结果
- **THEN** 系统不得因其接入凭据由受信服务端签发而放宽判定
