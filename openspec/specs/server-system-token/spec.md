# server-system-token Specification

## Purpose

管理 MCP Server 进程持有的云端平台系统 Token 的完整生命周期，包括启动自动登录、运行期透明刷新、Token 失效降级及恢复。

## Requirements

### Requirement: 服务端启动时自动获取系统 Token
系统 SHALL 在 MCP Server 启动过程中读取 permissions.json 的 systemAccount 段（phone、code），调用云端平台 login 接口获取 system_token 并保持在进程内存中。

#### Scenario: 正常启动获取 Token
- **WHEN** MCP Server 启动且 permissions.json 包含有效 systemAccount
- **THEN** 系统必须使用 systemAccount.phone 和 systemAccount.code 调用平台 login
- **THEN** login 成功后系统必须在内存中持有有效 system_token
- **THEN** 后续所有云端平台 API 调用必须使用该 system_token

#### Scenario: 启动时网络不可达
- **WHEN** MCP Server 启动但云端平台不可达
- **THEN** 系统必须记录启动失败日志，包含错误原因
- **THEN** 系统必须继续启动（不阻塞服务）
- **THEN** showcase 平台数据标记为不可用

#### Scenario: permissions.json 无 systemAccount
- **WHEN** permissions.json 不存在或不含 systemAccount 段
- **THEN** 系统必须打印明确警告提示配置缺失
- **THEN** 系统不得获取 system_token
- **THEN** 所有云端工具调用返回 AUTH_EXPIRED 直至配置补充

### Requirement: Token 失效时透明自动刷新
系统 SHALL 在检测到平台返回认证失效（40100 / AUTH_ERROR）时，自动使用 systemAccount 重新 login 获取新 Token 并重试原始请求，整个过程对客户端透明。

#### Scenario: 单次刷新成功
- **WHEN** 工具调用收到平台 40100 响应
- **THEN** 系统必须自动用 systemAccount 重新 login
- **THEN** login 成功后必须用新 Token 重试原始请求
- **THEN** 客户端必须只看到最终结果，不感知刷新过程

#### Scenario: 刷新失败进入降级
- **WHEN** 自动重登也失败（网络断开、账号被平台禁用）
- **THEN** 系统必须向客户端返回 AUTH_EXPIRED 错误码
- **THEN** 客户端 Skill 层根据错误码决定是否走本地模式

### Requirement: systemAccount 可被超级账号用户更新
当超级账号用户的 login 参数与当前 systemAccount 不一致时，系统 SHALL 用客户端提供的参数替换 systemAccount 并持久化到 permissions.json。

#### Scenario: 内置账号失效但超级用户有效
- **WHEN** systemAccount login 失败且客户端 login 手机号命中超级账号来源
- **THEN** 系统必须用客户端提供的 phone/code 尝试 login
- **THEN** login 成功后必须将新参数写入 permissions.json.systemAccount
- **THEN** 后续系统 Token 刷新使用新参数

#### Scenario: 超级用户参数也无效
- **WHEN** 客户端 phone 命中超级账号但提供的 code 无法登录
- **THEN** 系统必须返回明确错误："账号验证失败，请检查登录参数"
- **THEN** 系统不得覆盖 permissions.json 中的 systemAccount

### Requirement: permissions.json systemAccount 为本地敏感配置
permissions.json（含 systemAccount）MUST 被排除在版本控制和 Agent 资源包之外。

#### Scenario: 资源包导出排除
- **WHEN** 系统导出 Agent 资源包 ZIP
- **THEN** ZIP 中不得包含 permissions.json

#### Scenario: 版本控制排除
- **WHEN** permissions.json 存在或被更新
- **THEN** .gitignore 必须覆盖该文件，不得被提交
