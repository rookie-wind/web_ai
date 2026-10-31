# web-account-auth Delta

## ADDED Requirements

### Requirement: 账号库变更必须热加载

账号库文件变更 MUST 在下次鉴权读取时自动生效，MUST NOT 要求重启 webchat
服务。实现 MUST 以文件修改时间（mtime）判定变更并重载；重载后新增/禁用账号
立即生效，文件损坏时 MUST 进入既有"配置错误 → 503"状态，MUST NOT 崩溃或
放行。系统 MUST 支持"一人一账号"的管理方式：会话归属、并发配额与审计均按
username 区分。

#### Scenario: 新增账号无需重启

- **WHEN** 运维在账号库文件中新增一个账号条目并保存
- **THEN** 下一次登录请求即可使用该账号，无需重启服务

#### Scenario: 账号库损坏即时拒绝

- **WHEN** 账号库被改为非法 JSON
- **THEN** 下一次鉴权读取进入配置错误状态，登录返回 503，既有进程不崩溃
