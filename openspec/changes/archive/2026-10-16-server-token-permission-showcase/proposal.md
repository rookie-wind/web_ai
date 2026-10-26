## Why

当前权限模型要求每个客户端自行 login 获取业务 Token 并在每次工具调用时传入 `token` 参数，导致：(1) 未登录时 showcase 平台数据降级为 static；(2) 40+ 工具签名冗余，Skill 编排复杂度高；(3) 客户端用户必须持有有效云端账号才能使用读功能。需要改为服务端统一持有系统 Token、客户端 login 仅做身份识别的模型，同时让 showcase 展示数据完全动态化，消除硬编码。

## What Changes

- **BREAKING** 移除所有云端工具（~40 个）的 `token: str` 必填参数，服务端内部使用 system_token 调用平台 API
- **BREAKING** `login(phone, code)` 不再返回业务 Token，改为返回 `{success, role: "super"|"user", message}`
- 服务端启动时使用 permissions.json 中的 systemAccount（phone/code）自动登录，获取并维护 system_token
- 实现透明 Token 刷新：40100 时自动重登并重试，对客户端无感
- 按 MCP 接入 Token 绑定 session（含 role、fallback_token），session 在服务端重启时清空
- 云端工具必须先 login 才可用；login / list_mcp_tools / edge_xxx 工具免登录
- 非 super 用户 login 时，服务端获取 fallback_token 作为备用写入凭据
- systemAccount 失效 + super 用户命中 → 用客户端参数覆盖 systemAccount 并持久化到 permissions.json
- 全部 Token 不可用时返回 AUTH_EXPIRED，Skill 层自行降级到本地模式
- showcase 页面 delivery.stats（品牌数/设备类型数）改为平台 API 实时查询
- showcase "已生成配置" 改为 .stats.json 事件计数（初始 19，gen_script 成功 +1）
- showcase "回归测试" 数量改为启动时运行 test_protocol_converter.py 动态统计
- install.bat 自动生成含默认 systemAccount 的 permissions.json

## Capabilities

### New Capabilities
- `server-system-token`: 服务端启动自动登录、Token 透明刷新、fallback 策略、permissions.json systemAccount 管理
- `client-session-permission`: 按 MCP 接入 Token 绑定 session、login 身份判定（super/user）、写权限门控逻辑
- `showcase-stats-persistence`: .stats.json 事件计数器、启动测试统计、平台数据实时查询、前端动态渲染

### Modified Capabilities
- `mcp-token-management`: 移除 localhost 管理员 Token 授予写权限的旧模型；MCP 接入 Token 变为 session 绑定标识，不再携带 access_level（system/user）权限语义

## Impact

- `mcp_server/server.py`: 工具签名（~40 个删 token 参数）、AuthMiddleware（移除 access_level contextvar 写入）、启动流程（自动 login）、login 工具实现重写
- `mcp_server/permissions.py`: 新增 systemAccount 加载、SessionRegistry（按 MCP Token 管理）、Token 降级策略
- `mcp_server/api_client.py`: 调用方式不变，但 token 来源从参数改为服务端内部变量
- `mcp_server/static/showcase.html`: delivery.stats 从硬编码改为动态
- `mcp_server/static/access.html`: 权限说明文案更新
- `.trae/skills/*/SKILL.md`: 工具调用示例去掉 token 参数
- `mcp_server/install.bat`: 生成 permissions.json 模板
- `.gitignore`: 确认 permissions.json 已忽略（含凭据）
- 测试：test_refactor.py 需适配新签名
