## Why

Web/移动端接入方案（`docs/requirements/web-mobile-access-requirements.md`，C3）
的会话与实例运行时：C2 已交付账号准入与业务凭据绑定，但用户登录后还无法开始
对话——没有会话管理、没有 CLI 实例、没有事件流、没有 MCP 接入凭据签发通道。
本变更是 Web 路径"能对话"的第一块基石，也是全方案工作量与风险最大的变更。

技术死结（实测）：现有 `TokenManager` 以**来源 IP 为主键**（`server.py:447`
`ip_tokens: dict[ip, entry]`），同一 IP 签发第二把 Token 必然顶掉第一把；
webchat 后端作为所有 Web 会话的单一出口 IP，共享凭据 = 会话互相顶号 = 越权。
多会话并存必须换主键。

## What Changes

- **BREAKING（规格级）：Token Registry v2 → v3，主键从 IP 改为 Token**。
  - entries 以 Token 为键；IP、接入主体引用（owner_ref）、凭据族别
    （`family: ide | webchat`）、有效期、撤销状态降为属性；
  - IDE 族凭据：长期有效、重启仍可用（沿用现有语义）；
  - webchat 族凭据：带 TTL、可撤销、服务重启后仍可按 TTL 判定；
  - 迁移沿用既有备份范式（v2 备份后迁移，损坏回退空表、绝不授予特权）。
  - **对 IDE 用户的可见影响**：同一 IP 可同时存在多把有效 Token（此前只有
    一把）；既有 IDE Token 迁移后继续有效，行为不变。
- **mint 签发端点（MCP Server 新增路由，属"新增"而非修改既有端点）**：
  `POST /api/mcp-token/mint`——仅 webchat 后端可调：须同时持有
  `WEBCHAT_MINT_SECRET`（环境变量，独立于 MCP_AUTH_TOKEN）且来源为允许的
  回环地址；签出的接入 Token 一律 user 级、带 TTL 上限、族别 webchat、
  绑定 owner_ref（`SHA-256("webchat:" + username)`）。
- **webchat 会话运行时**（在 C2 的 webchat 包内新增模块）：
  - **SDK adapter**：SDK 类型只出现在 `webchat/webchat/sdk_runtime/` 单层内；
  - **会话:实例:凭据 = 1:1:1**：每个 webchat 会话对应一个 CLI 实例 + 一把
    专属接入凭据，凭据随实例启动绑定，运行期不可切换，绝不共享；
  - **实例池与配额**：全局活跃实例上限（默认 4，可配）、每用户并发会话上限、
    单轮 max_turns 上限；超限明确排队/拒绝；
  - **事件契约 v1**：自定义事件（session_started / text_delta / tool_call /
    tool_result / turn_done / error 等，统一带 v/seq/session_id/ts），后端
    持久化为自有事实源，SSE 下发 + `Last-Event-ID` 断线重放；SDK 事件类型
    不得泄漏到业务层与前端；
  - **租约**：单写者租约（默认 45s TTL + 前端心跳），后来者只读旁观；
  - **会话端点**：创建会话 / 发送消息 / SSE 事件流 / 会话列表与历史回看 /
    结束会话（凭据随会话终结撤销）。
- **待补验**（实施期完成，失败有回退路线）：V1b 会话恢复粒度、V2 无头技能
  路由（`/xlpa` 是否在 SDK 会话中展开）、实例冷启动成本。
- 明确**不在本变更内**：写入门禁验票与路径白名单（C4）、产物与上传（C5）、
  转换执行工具（C6）、前端页面（C7 验收期）；`/mcp` 端点协议与 71 个既有
  工具的入参/返回零改动。

## Capabilities

### New Capabilities

- `agent-runtime-session`: Web 会话运行时——会话生命周期与 1:1:1 绑定
  （会话:CLI 实例:接入凭据）、SDK 事件归一化为自有契约 v1、SSE 下发与
  seq 断线重放、单写者租约与旁观、实例池与配额、会话工作区布局。
- `mcp-token-mint`: webchat 专属接入凭据的签发端点——双条件准入
  （mint secret + 回环来源）、签发凭据的族别/TTL/owner_ref 属性、速率
  约束、审计留痕。

### Modified Capabilities

- `mcp-token-management`: Registry 主键从 IP 改为 Token（v2→v3 迁移）、
  同 IP 多凭据并存、凭据族别与 TTL/撤销语义、IDE 族语义保持不变。
  （delta spec 落于 `specs/mcp-token-management/spec.md`，需先同步
  主规格同名 requirement 的完整内容后修改。）

## Impact

- **代码**：
  - `mcp_server/server.py`：TokenManager 主键重构（is_valid/revoke/
    get_token_info/touch 改为按 Token 判定）+ CompositeApp 新增 mint 路由
    + AuthMiddleware 补 webchat 族归属标签；**AuthMiddleware 验证链与
    /mcp 端点行为不变**；
  - `mcp_server/.token_registry.json`：v3 迁移（自动，带备份）；
  - `webchat/webchat/` 新增：sessions 扩展、sdk_runtime/（adapter）、
    events（契约+存储+重放）、instance_pool、lease、API 路由扩展；
  - `webchat/requirements.txt`：新增 qoder-agent-sdk 依赖。
- **既有测试**：涉及 TokenManager 的用例需按 v3 语义更新（预期集中在
  test_auth_revamp.py / test_session_permission.py）；既有 pytest 基线
  必须保持全绿（v3 迁移含 IDE 兼容断言）。
- **配置**：`WEBCHAT_MINT_SECRET`（高熵、可轮换）、`WEBCHAT_ALLOWED_IPS`
  （默认仅回环）、实例上限等环境变量。
- **风险**：Registry v3 是规格级 BREAKING；SDK 行为（V1b/V2）存在未验项，
  失败时回退路线为"降实例并发 + 缩短会话寿命"，架构不回退。
