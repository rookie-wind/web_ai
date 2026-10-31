## Purpose

定义 webchat 专属 MCP 接入凭据签发端点（mint）的行为契约：双条件准入、
签发凭据的属性（族别/TTL/owner_ref/user 级）、速率约束与审计留痕。

**变更四要素**

| 要素 | 内容 |
|---|---|
| 前置条件 | 1) mcp-token-management delta（Registry v3）已在本变更内先行交付；2) `WEBCHAT_MINT_SECRET` 环境变量已配置（部署前置，不入库）；3) webchat 回环调用通道连通（127.0.0.1 回环实测） |
| 要做的事 | MCP Server 新增 POST /api/mcp-token/mint 路由（纯新增，不动 /mcp）：双条件校验（mint secret 头 + 来源 IP 白名单默认回环）、签发 family=webchat 的 user 级接入凭据（带 TTL 上限与 owner_ref）、速率限制、审计留痕 |
| 通过标准（可执行判据） | 1) 新增 pytest：无 secret 401 / secret 错误 401 / 来源非白名单 403 / 合法请求签出可用的 user 级凭据（能过 /mcp 鉴权）/ TTL 与 owner_ref 落入 registry / 速率超限 429 / 审计记录存在；2) /mcp 端点与既有工具入参/返回零改动（既有测试全绿） |
| 执行顺序与依赖 | 在 agent-runtime-session 模块之前交付（会话创建依赖 mint 签发凭据）；属本变更（C3）内部第一块 |

## ADDED Requirements

### Requirement: mint 签发必须双条件准入

mint 端点 MUST 同时校验两个条件才允许签发：请求头携带正确的
`WEBCHAT_MINT_SECRET`（与 `MCP_AUTH_TOKEN` 相互独立，可单独轮换吊销）；
请求来源 IP 在允许清单内（`WEBCHAT_ALLOWED_IPS`，逗号分隔，默认仅回环
地址）。任一条件不满足 MUST 拒绝（secret 缺失/错误 401，来源不允许 403），
且 MUST NOT 回显 secret 或内部状态。

#### Scenario: 无 secret 或错误 secret 拒绝

- **WHEN** 请求未携带 mint secret 头或 secret 值错误
- **THEN** 返回 401，响应不含 secret 相关内部信息

#### Scenario: 来源不在白名单拒绝

- **WHEN** 携带正确 secret 但来源 IP 不在允许清单
- **THEN** 返回 403

### Requirement: 签发凭据必须为 webchat 族 user 级且带 TTL 与 owner_ref

mint 签出的接入 Token MUST 携带属性：`family=webchat`、`accessLevel=user`
（与 IDE 族一致，仅连接用途）、`expires_at`（ttl_seconds 未传时默认
7200 秒，且受可配置 TTL 上限 86400 秒约束）、`owner_ref =
SHA-256("webchat:" + 规范化 username)`（稳定归属，不随凭据轮换漂移）。
username 规范化规则 MUST 与账号库查询一致：去除首尾空白（大小写敏感），
保证同一账号不产生分裂的 owner_ref。凭据 MUST 可立即用于 /mcp 鉴权；
到期或撤销后 MUST 失效。

#### Scenario: 签出凭据立即可用且属性完整

- **WHEN** 合法 mint 请求（含 username）成功
- **THEN** 返回的 Token 可通过 /mcp 鉴权（user 级），registry 中该 Token
  记录含 family=webchat、expires_at、owner_ref

#### Scenario: 签出凭据不产生写权限

- **WHEN** 使用 mint 签出的 Token 调用云端平台写入类工具
- **THEN** 未业务登录时被 NOT_LOGGED_IN/FORBIDDEN 拒绝，写权限仍由
  permissions.json + 业务登录结果判定

### Requirement: revoke 必须仅作用于 webchat 族凭据

凭据撤销端点 MUST 与 mint 同源双条件准入（secret + 来源白名单）；
撤销 MUST 仅对 `family=webchat` 的凭据生效：对 IDE 族凭据（含
MCP_AUTH_TOKEN）的撤销请求 MUST 拒绝（403），避免 mint 通道被用于
破坏 IDE 现网凭据。

#### Scenario: 撤销 IDE 族凭据被拒绝

- **WHEN** 携带正确 secret 请求撤销一个 family=ide 的 Token
- **THEN** 返回 403，该 IDE Token 保持有效

#### Scenario: 撤销 webchat 族凭据生效

- **WHEN** 携带正确 secret 请求撤销一个 family=webchat 的 Token
- **THEN** 该 Token 立即无法通过 /mcp 鉴权

### Requirement: mint 必须限速并留审计

mint 端点 MUST 实施速率限制（可配置上限，超限 429）；每次签发成功与
被拒尝试 MUST 留审计记录（时间、来源、owner_ref、结果；不含 secret）。

#### Scenario: 签发速率超限

- **WHEN** 单位时间内 mint 请求超过配置上限
- **THEN** 后续请求返回 429，审计中可见被拒记录

#### Scenario: 审计可查

- **WHEN** 管理流程查询 mint 审计记录
- **THEN** 可见每次签发的时间、来源、owner_ref 与结果，且不含 secret 值
