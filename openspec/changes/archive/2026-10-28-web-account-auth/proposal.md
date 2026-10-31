## Why

Web/移动端接入方案（`docs/requirements/web-mobile-access-requirements.md`，C2）
要求用户进入对话界面前先以**账号、密码**登录（可配置、不写死），且准入登录必须与
平台业务登录（手机号+验证码）建立明确映射——这是后续 C3（会话运行时）签发会话
凭据、C4（写入门禁）判定写权限的身份基座。当前系统没有任何 Web 侧账号体系，
`permissions.json` 的超级账号名单只回答"能不能写平台"，不回答"能不能进门"。

## What Changes

- **新增独立后端服务骨架 `webchat/`**（与 `mcp_server/` 平级、独立 venv、
  独立进程、独立 requirements）：Web/移动端接入路径的 Host 层载体；
  本变更只交付其中的账号准入模块，会话/实例/事件流属后续变更（C3+）。
- **账号库**：`webchat/webchat_accounts.json`（gitignore，含模板文件入库），
  每条 = `username + password 哈希（PBKDF2-HMAC-SHA256，标准库实现，格式
  pbkdf2_sha256$iter$salt$hash）+ 绑定的平台 phone/code + enabled`。
- **准入端点**：`POST /api/auth/login`（账号密码 → 会话票据）、
  `POST /api/auth/logout`、`GET /api/auth/me`（票据校验）；
  票据为 `secrets.token_urlsafe` 随机值，服务端内存存储，TTL 可配置。
- **登录限流**：按 IP + username 的内存滑动窗口计数，超限拒绝并计数留痕。
- **业务凭据绑定（难点 b 落地）**：登录成功后由 webchat 后端直接 HTTP 调
  平台 `/api/Auth/LoginByCode`（用账号库绑定的 phone/code），业务 Token 仅存
  webchat 会话内存；**准入 ≠ 授权**——写权限唯一判据仍是
  `permissions.json`（superAccounts）+ 业务登录结果，两份名单不合并。
- **密码哈希工具**：`python -m webchat.hash_password`（或等价入口）生成
  PBKDF2 哈希行，供管理员配置账号库。
- 明确**不在本变更内**：CLI 实例/SDK、MCP 接入凭据签发（Registry v3/mint）、
  SSE 事件流、前端页面、写入门禁——属 C3~C6；`/mcp` 端点与 71 个既有工具
  零改动。

## Capabilities

### New Capabilities

- `web-account-auth`: Web/移动端账号密码准入——账号库与密码哈希约定、
  登录/登出/票据校验行为、票据 TTL 与失效语义、登录限流、与平台业务凭据
  的绑定及"准入不等于写权限"的边界、账号库文件的敏感文件纪律。

### Modified Capabilities

（无——`mcp-token-management` 的 Registry v3 变更属 C3；本变更不触碰
MCP Server 任何行为。）

## Impact

- **代码**：新增 `webchat/` 包（独立 venv：fastapi/uvicorn/httpx——
  与 `mcp_server/requirements.txt` 完全隔离）+ `webchat/tests/`；
  `mcp_server/` 零改动。
- **配置**：`webchat/webchat_accounts.json`（gitignore）+ 模板入库；
  环境变量 `WEBCHAT_SESSION_TTL`、`WEBCHAT_LOGIN_RATE_LIMIT`、
  `WEBCHAT_ACCOUNTS_PATH`、`WEBCHAT_PERMISSIONS_PATH`、
  `PCA_API_BASE_URL`（沿用既有语义）。
- **测试**：主 pytest 基线（`mcp_server/tests`）不受影响须保持全绿；
  webchat 自有 pytest 用例（哈希校验、错误密码、票据 TTL/过期、限流、
  两份名单不混用断言）由 webchat venv 运行，回归命令两条并存。
- **依赖方**：C3 会话运行时依赖本变更的票据体系；运维需为管理员提供
  生成密码哈希的入口（哈希工具命令）。
- **前置验证**：V10（PAT 注入不出现在子进程命令行）在本变更 tasks 中
  验证并留证——它是 C3 SDK 实例化的先决项，按需求文档 §7.2 归属本变更
  前置条件。
