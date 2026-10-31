## MODIFIED Requirements

### Requirement: Token Registry 必须作为本地敏感运行态文件处理

系统 SHALL 将 Token Registry 视为本地敏感运行态文件，不得将其打入 Agent
资源包，不得在用户可复制说明中暴露其他 IP 的 Token。开启网络暴露模式
后，接入信息接口 MUST NOT 对非本机且未命中 allowlist 的来源分配或回显
Token（该来源请求被门控拒绝，不触达分配逻辑）。

#### Scenario: 导出 Agent 资源包

- **WHEN** 系统生成 Agent 资源包 ZIP
- **THEN** ZIP 中不得包含 Token Registry 文件
- **THEN** ZIP 中不得包含任何已分配 user Token 清单

#### Scenario: 生成接入页信息

- **WHEN** 用户访问接入页或接入信息接口
- **THEN** 系统只展示当前访问来源对应的 Token
- **THEN** 系统不得展示其他 IP 的 Token 或完整 Token Registry 内容

#### Scenario: 公网模式下远程来源不得获取 Token

- **WHEN** 网络暴露模式开启且非本机、非 allowlist 来源请求接入信息接口
- **THEN** 请求被拒绝，系统不为该来源分配 Token，也不回显任何 Token 信息

#### Scenario: 版本控制安全

- **WHEN** 项目生成或更新 Token Registry 文件
- **THEN** 该文件必须被视为不得提交到版本控制的本地文件
- **THEN** 文档必须提示该文件包含敏感 Token 信息
