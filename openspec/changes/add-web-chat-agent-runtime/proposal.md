## Why

当前客户端形态是"IDE 加载 Skills + 配置 MCP"，业务闭环只能在有人值守的 IDE 里完成。
现场与移动端使用者没有 IDE，也无法在手机上走完"取建档模板 → 填报 → 上传 → 确认下发"
的链路；对外交付也需要一个可直接访问的对话入口。同时现有 IDE 接入路径与 MCP 工具行为
必须保持不变，因此不能把交互与会话状态长在 MCP Server 里。

## What Changes

- 新增 **Web 交互层**（PC/移动自适应）：手机号+验证码登录后方可对话、多会话列表、
  流式中间输出、计划确认卡片、文档/照片上传、产物下载、断线重连后事件重放。
- 新增 **独立后端（Host 层）**：与 MCP Server 同机、独立进程与独立 venv。负责会话生命
  周期、CLI 实例池、身份与接入凭据绑定、事件规范化与 SSE 广播、写门禁票据签发、
  单写者租约与只读旁观、配额限流、事件流双写自有存储、后端本地 OCR。
- 新增 **Agent 运行时**：经 Qoder Agent SDK 驱动 CLI，每个用户会话对应一个独立 CLI
  实例与一把专属接入凭据（1:1，严禁共享）。CLI 加载现有资源包 Skills，自行决定走协议
  转换技能还是调用 MCP 工具。**一期禁用 Bash 工具**，写/读仅限会话工作区与资源包母本。
- MCP Server 保持纯工具层：`/mcp` 协议与既有工具行为不变；仅新增一个受独立服务凭据
  保护的会话 Token 签发端点（mint）。
- **BREAKING（规格级）** Token Registry 主键由 IP 改为 Token/Owner 维度并做 v2→v3
  迁移；"同一 IP 返回同一 Token"改为"同一主体返回同一未撤销 Token"，并区分 IDE 接入
  Token（长期有效、重启仍可用）与 web 会话 Token（带 TTL、可撤销）两族语义。
- **BREAKING（规格级）** 归属主体与接入凭据解耦：web 路径的 `owner_id` 由稳定用户引用
  （登录手机号）派生，不再等于 `sha256(接入 Token)`；IDE 路径维持现状。
- 明确不在本变更内：协议转换的执行类服务端工具（`execute_conversion_test` 等）与
  对应 SKILL.md 改写另立变更，因其会改变交付给 IDE 客户端的资源包语义并触发版本升级。

## Capabilities

### New Capabilities
- `web-chat-session`: Web 会话的建立与准入、会话↔CLI 实例↔接入凭据的 1:1 关系、事件
  契约与重放、单写者租约与旁观、配额与保留期、登录身份与归属解耦的对外行为。
- `agent-runtime-isolation`: agent 运行时的能力边界契约——禁 Bash、路径白名单、
  Hook 配置不得位于可写工作区、写门禁一次性票据与 Fail-Closed、mint 端点的服务凭据
  与准入控制、拦截事件的可观测要求。
- `web-chat-artifact-delivery`: 产物与上传物的落点归属、后端代理下载与一次性 grant、
  禁止凭据进 URL 的具体形态、按产物分类的保留期与清理时机。

### Modified Capabilities
- `mcp-token-management`: Token 分配主键由 IP 改为 Token/Owner 维度；新增"按会话签发
  短期凭据"的需求；保留 IDE 路径的长期有效语义；v2→v3 迁移与损坏回退策略。
- `client-session-permission`: Session 绑定键与归属主体由接入 Token 改为稳定用户引用，
  以支持同一用户多会话（多设备）共享归属、且凭据轮换/撤销不丢登录角色与业务产物。

## Impact

- 代码：
  - `mcp_server/server.py`：`CompositeApp` 新增 mint 路由；`TokenManager` 主键与
    `is_valid`/`revoke_token`/`touch_ip_last_seen`/`get_token_info` 改造；Registry
    schema 版本号提升与迁移分支；`AuthMiddleware` 为 web 会话来源补充归属标签。
  - 新增顶层目录 `webchat/`（独立后端，名称可在实现期定）：Host 层、SDK adapter、
    事件契约、租约、票据、OCR、自有会话存储。仅通过 HTTP 回环 `/mcp` 调工具，
    **禁止直调工具函数**，否则绕过 `mcp_token_var`、鉴权与审计。
  - `mcp_server/cleanup.py`：新增 web 产物分类映射（沿用 input/result/audit 必留、
    temp/sensitive_temp 可删的既有语义）。
- 依赖：`qoder-agent-sdk`（Python 3.10+，内置 qodercli 运行时）；本地 OCR 库及其模型
  文件（离线部署需预置）；后端独立 venv，不与 `mcp_server/requirements.txt` 混装。
- 配置：`WEBCHAT_MINT_SECRET`、`WEBCHAT_ALLOWED_IPS`、Qoder 账号/PAT（不进工作区、
  不拼入子进程命令行）、web 准入手机号白名单（独立文件，不写进 `permissions.json`）、
  配额三值（默认每用户 100 轮/日、全局活跃实例 4、单轮 `max_turns` 25，均可配）。
- 数据：`.token_registry.json` v3 迁移（备份沿用 `_backup_registry` 范式）；会话事件流
  与产物按 owner 分区落盘；含凭据的建档 Excel 保留期短于普通产物。
- 前置验证（任一失败需回到本变更修订设计）：SDK 能否连自家 `/mcp`、会话可恢复到什么
  程度、canUseTool/Hook 能否拿到含 `plan_id` 的完整 arguments、Hook 能否回调后端、
  `edge_sessions` 是否仅在内存、PAT 注入方式。
- 兼容性：IDE 接入路径、`/mcp` 端点、71 个工具的入参与返回均不变；现有接入页与
  showcase 不受影响。
