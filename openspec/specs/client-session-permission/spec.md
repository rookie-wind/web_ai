# client-session-permission Specification

## Purpose

定义客户端通过 login 建立的身份会话（session）机制，控制哪些客户端可以调用哪些云端工具以及读写权限分级。

## Requirements

### Requirement: login 工具仅做身份判定
login(phoneNum, code) SHALL 验证客户端身份并判定角色（super / user），不向客户端返回任何业务 Token。

#### Scenario: 超级账号登录
- **WHEN** 客户端调用 login(phoneNum, code) 且 phoneNum 命中内置系统账号或 permissions.json.superAccounts
- **THEN** 系统必须将该 session 标记为 role="super"
- **THEN** 系统必须返回 {success: true, role: "super", message: "已授权，系统账号"}
- **THEN** 返回体中不得包含任何 Token 字段

#### Scenario: 普通账号登录
- **WHEN** 客户端调用 login(phoneNum, code) 且 phoneNum 未命中超级账号表
- **THEN** 系统必须将该 session 标记为 role="user"
- **THEN** 系统必须返回 {success: true, role: "user", message: "已登录，只读权限"}
- **THEN** 服务端必须在内部保存该用户对应的 fallback_token（用该参数向平台 login 获取）

#### Scenario: 登录参数无效
- **WHEN** 客户端调用 login(phoneNum, code) 但平台拒绝该参数
- **THEN** 系统必须返回 {success: false, error: "LOGIN_FAILED", message: "登录失败：账号或验证码错误"}
- **THEN** 该 session 不建立，后续云端工具调用返回 NOT_LOGGED_IN

### Requirement: Session 按 MCP 接入 Token 绑定
系统 SHALL 以 MCP 接入 Token 为 key 维护 session 信息（phone、role、fallback_token、loginAt），session 在服务端进程生命周期内有效。

#### Scenario: 同一 Token 多次调用工具
- **WHEN** 客户端使用同一 MCP Token 在 login 后连续调用多个云端工具
- **THEN** 系统必须从同一 session 读取权限信息
- **THEN** 不得要求客户端重复 login

#### Scenario: 服务端重启
- **WHEN** MCP Server 进程重启
- **THEN** 所有 session 必须清空
- **THEN** 客户端必须重新 login 后才能使用云端工具

### Requirement: 云端工具必须登录后调用
所有云端工具（读/写）MUST 检查调用方 session 是否存在，不存在时返回 NOT_LOGGED_IN。

#### Scenario: 未登录调用云端读工具
- **WHEN** 客户端未调用 login 直接调用 get_brand_list
- **THEN** 系统必须返回 {error: true, code: "NOT_LOGGED_IN", message: "请先调用 login 验证身份"}

#### Scenario: 未登录调用边缘工具
- **WHEN** 客户端未调用 login 直接调用 edge_get_token 或 edge_upsert_device
- **THEN** 系统必须正常执行（边缘工具免登录）

#### Scenario: 免登录工具白名单
- **WHEN** 客户端未 login 时调用 login / list_mcp_tools / 任何 edge_xxx 工具
- **THEN** 系统必须正常执行，不返回 NOT_LOGGED_IN

### Requirement: 写工具需超级账号权限
写入类工具（add_xxx / update_xxx / del_xxx）MUST 检查 session 的 role 为 "super"，否则返回 FORBIDDEN。

#### Scenario: 超级账号执行写操作
- **WHEN** role="super" 的 session 调用 add_brand
- **THEN** 系统必须使用 system_token 执行平台 API 调用

#### Scenario: 普通账号尝试写操作
- **WHEN** role="user" 的 session 调用 add_brand
- **THEN** 系统必须返回 {error: true, code: "FORBIDDEN", message: "此操作需要超级账号权限"}

### Requirement: 写工具使用 system_token 并在失效时降级
写操作默认使用 system_token；system_token 刷新失败时 SHALL 尝试使用 session 中的 fallback_token；两者都不可用时返回 AUTH_EXPIRED。

#### Scenario: system_token 正常
- **WHEN** role="super" 的 session 调用写工具且 system_token 有效
- **THEN** 系统必须使用 system_token 执行操作
- **THEN** 不得使用 session 中的 fallback_token

#### Scenario: system_token 失效 + fallback 可用
- **WHEN** system_token 刷新失败且 session 中有 fallback_token
- **THEN** 系统必须尝试使用 fallback_token 执行操作
- **THEN** fallback_token 也被平台拒绝时，必须返回 AUTH_EXPIRED

#### Scenario: 全部 Token 不可用
- **WHEN** system_token 和 fallback_token 均无法执行平台操作
- **THEN** 系统必须返回 {error: true, code: "AUTH_EXPIRED", message: "云端平台不可用，请检查账号或等待恢复"}
- **THEN** Skill 层收到此错误后应询问用户是否切换本地模式
