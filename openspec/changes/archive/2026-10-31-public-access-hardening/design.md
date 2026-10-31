## Context

- **mcp_server 路由现状**：`server.py` 的 RoutingMiddleware 按路径分发，
  展示类端点（`/`、`/showcase`、`/access`、`/api/access-info`、
  `/api/showcase/data`、`/api/docs/export-skills*`）完全无鉴权；
  `/api/archive/templates/<id>?owner=` 为 file_id 即票据；`/api/logs`
  接受 Bearer 头**或** `?token=` 查询串回退（server.py 实测，URL 形态
  属凭据进地址）；mint 端点已有双条件准入 + IP allowlist + 限流范式
  （`MINT_ALLOWED_IPS`）。本机判定 `_is_local_ip`（环回 + 本机网卡 IP）。
- **webchat 现状**：纯 JSON API（端口 8800，默认绑定 127.0.0.1），零前端
  页面；事件契约 v1 已含 `ask_user` / `gate_blocked` / `artifact` 类型；
  `gate_blocked` payload 现仅含 tool_name 与 plan_id/task_id 提示
  （C4 实现），**无参数摘要**。
- **C4 硬依赖**：grant 粒度不校验参数，约定由"确认卡片带参数摘要"在
  C7 兜底（write-gate-isolation design Risks 明示）。
- **既有范式可复用**：mcp_server `static/` 目录 + 内存缓存 HTML 的托管
  方式。**纠正一处失实陈述**：playwright 并未声明在任何 requirements 文件
  中（`mcp_server/requirements.txt` 实测仅 `mcp`/`uvicorn`/`httpx` 三项），
  现有能力测试靠环境预装——因此本变更不得假设它存在，见 D7。
- **实测链路前提（2026-10-29 端到端取证）**：新建会话的接入凭据未经平台
  登录绑定，任何云端工具（**只读与写入均包括**）返回 `NOT_LOGGED_IN`；
  webchat 登录时已用账号预设凭据代登平台，但该业务凭据在 session 内无任
  何读取点。经 `/mcp` 调一次 `login` 后只读立即返回 30 条真实数据；`login`
  的 `code` 参数服务端语义为「不会过期」，且超级账号不写业务 Token 缓存
  （授权态绑在接入凭据对应的会话记录上）。⇒ 演练前必须补授权激活，见 D9。
- **身份提取实测偏差**：平台 `user.userId` 为整型、手机号键名为
  `user.mobilePhone`；webchat `_dig` 仅认字符串、`_PHONE_KEYS` 缺该键名，
  造成 `is_super` 恒 False（mcp_server 侧因用 login 入参判定而不受影响）。
  见 D10。
- **运行配置事实**：`.env` 仅由 `start.bat` 解析，`python server.py` 直接
  启动的进程不加载它；webchat 侧只读进程环境变量。部署清单必须写明这一
  点（否则改 `.env` 无效会被误判为配置已生效）。

## Goals / Non-Goals

**Goals:**
- 公网模式端点分级门控（默认关，内网零影响）。
- webchat 单页前端，覆盖 AC-1/AC-2 浏览器闭环与 FR-1~FR-8 交互面。
- AC-1~AC-4 + V11 端到端演练留证；公网部署前置清单落文档。

**Non-Goals:**
- 不改 `/mcp` 协议与 77 工具行为（IDE 路径零变化，AC-3）。
- 不做来源 B（mcp_server 原生模板/任务报告）的 Web 自动检测下载
  （维持 C5 二期边界；本变更前端只提供来源 A 下载）。
- 不做账号自助注册、密码找回（推后运维）。
- 不引入前端框架/构建链（Vite/React 等）；MUST NOT 新增**运行时** Python
  依赖（演练/测试专用依赖只进 dev 要求，见 D7）。
- 不做 WAF/证书自动签发组件选型落地（清单给判据，部署是现场动作）。

## Decisions

### D1 门控实现：路由层单一入口按端点类别裁决

在 RoutingMiddleware 分发前加一个 `_exposure_gate(path, client_ip)`
判定：端点归为三类（open-local-only 展示类 / ticket+owner 下载类 /
bearer 既有类），公网模式开启时对非本机来源逐类裁决（403 拒绝 /
要求 Bearer 且归属一致 / 原样放行）。
**备选**：各 handler 内分散检查——否决，授权逻辑必须单点可审计，
分散必漏。判定函数纯同步、无新状态。

### D2 配置面：`MCP_PUBLIC_MODE` 开关 + allowlist + 信任代理三级收紧

`MCP_PUBLIC_MODE=1` 开启门控（默认 0）；`MCP_PUBLIC_ALLOWLIST`
（逗号分隔 IP）放行展示类；`MCP_TRUSTED_PROXY`（逗号分隔 IP）决定
何时采信 `X-Forwarded-For` 最左值——未配置信任代理时一律用直连
`scope.client`，伪造头无效（spec 场景锚定）。与 mint 端点既有
`MINT_ALLOWED_IPS` 语义对齐但不共用变量（作用对象不同）。

### D3 URL 凭据端点的归属一致判定：复用 `derive_owner_id`

templates 下载与 `/api/logs` 的 `?token=` 回退在公网模式下收紧：前者
非本机来源要求 Bearer，用既有 `derive_owner_id(token)`
与 URL `owner` 参数摘要比对，一致才读快照；无 Bearer/无效 → 401，
不一致 → 404（不泄漏存在性，与 report_store 越权语义一致）；后者
非本机来源 MUST NOT 采信查询串 token，仅接受 Bearer 头（凭据不进
URL）。本机来源两者均保持既有行为。
**备选**：改造成 header 化的新下载端点——否决，会破坏既有内网客户端，
且 C5 已定"新链路在 webchat 侧、旧端点加门控"的分工。

### D4 前端形态：零构建单页静态资源挂 webchat

`webchat/static/`（index.html + 相邻 css/js，原生 ES 模块，无构建步骤），
FastAPI `StaticFiles` 挂载 + `/` 重定向；与 mcp_server `static/` 同范式。
凭据仅存 JS 内存变量，sessionStorage / localStorage 一律不存；全部 API 经
`Authorization: Bearer` 头；事件流用 `EventSource`（last-event-id 重连）。
**备选**：Vue/React 单文件框架 CDN 引入——否决，公网模式若关展示端点
反而依赖外网 CDN 更脆； vanilla 足够覆盖 6 个界面态。

### D5 gate_blocked payload 增参数摘要（后端最小改动）

adapter `_pre_tool_use` 拒绝分支在 payload 增 `arg_summary`（从
tool_input 提取白名单键：brand/model/plan_id/task_id/batch 计数等，
脱敏截断），前端确认卡片据此渲染。**摘要源分层**：
`execute_archive_task`（一键建档）的 tool_input 不含逐台设备参数，
其影响台数/品牌型号摘要 MUST 经 plan_id/task_id 反查计划域数据
（plan_device_archive 产物/快照元数据）获得，而非仅取 tool_input 白名单
键；反查不到时卡片明示"摘要不可用，仅显示计划标识"，MUST NOT 静默
展示空摘要冒充完整参数。**granted 事件已存在则复用**；
若实现验证发现需要"预告待确认"事件（deny 前模型无提示），仍以
gate_blocked 摘要 + 模型重试语义闭环（deny → 模型呈卡片 → confirm
→ 重试 allow），不新增事件类型——事件契约 v1 加字段是向后兼容扩展。

### D6 SSE 经代理的缓冲处置

部署清单要求代理关闭响应缓冲（Caddy `flush_interval -1` / nginx
`proxy_buffering off`），webchat 事件流端点已有心跳；前端 EventSource
`onerror` 自动重连带 last-event-id，断线不丢事件（spec 场景）。

### D7 验收演练工具与证据

浏览器演练用 playwright，将其声明为 **webchat 的开发/演练依赖**（当前
未声明于任何 requirements 文件，不得假设环境已装）；用例在使用点以
`pytest.importorskip` 声明，浏览器二进制经 `PCA_TEST_BROWSER` 指向已有
chromium（mcp_server 侧已验证可用）以避免重复下载 100+ MB。生产运行时
依赖零新增。脚本化 AC-1/AC-2
关键路径 + 截图落 `validation/public-access-hardening/`；交互式部分
（真实账号写入）人工执行留截图。IDE 回归同期跑主 pytest 全绿 +
`list_mcp_tools` 输出比对（基线 77）。V11 压测脚本记录限流现象。

### D8 回滚路径

`MCP_PUBLIC_MODE=0` 即刻恢复全部既有行为（门控代码路径不生效）；
前端为纯新增静态目录，不碰既有 API；gate payload 新字段旧前端忽略。

### D9 会话授权激活：mint 后用预设凭据自动调一次 login

webchat 在 `runtime.create` mint 成功、实例启动之前，用该接入凭据对 `/mcp`
调一次 `login(account.phone, account.code)`，使凭据完成平台登录绑定；激活
失败则 MUST 使会话创建失败（不留可用但一查即错的会话）。
**备选**：（i）把 `session.business_token` 随 mint 传给 mcp_server 写缓存
——否决：实测超级账号路径 **不读也不写** 该缓存（`fallback_token` 对超级
账号置 None），传了也不能解除 `NOT_LOGGED_IN`；（ii）前端做验证码补录环
——否决：`code` 不过期且服务端已持有，让用户重输属多余且泄露凭据。
本方案只用既有 `/mcp` 工具与既有预设凭据，不改 `/mcp` 协议、不撞 Non-Goals。

### D10 身份提取与 mcp_server 对齐（is_super 修正）

`_PHONE_KEYS` 补 `mobilePhone`；webchat `_dig` 的取值改为与 mcp_server 版
一致的 `str()` 宽容（现仅认 `isinstance(value, str)`，丢掉整型 userId）。
判据优先用 `userId`/`phone` 命中 `superAccounts`，并在实现验证后考虑改用
平台直接返回的 `user.superManage` 字段。
**范围声明**：真实写权限由 mcp_server 侧判定（已实测为 super），本项修的是
`/api/auth/me` 输出给前端的角色展示——不修则合法超级用户在页面上被当
普通用户。

### D11 webchat 登录限流的真实客户端标识

webchat `_client_ip` 现仅取直连地址、完全不处理转发头，经反代后所有用户
的地址都变成代理地址，叠加现有「不区分账号的来源级计数」，实测会退化为全站
登录互锁（陌生人错 5 次即锁全部账号）。采用**信任代理模式**：配置可信
代理清单（与 mcp_server D2 的 `MCP_TRUSTED_PROXY` 语义对齐但各自配置），
仅当直连来源命中清单才采信 XFF 最左值；并将账号级与来源级阈值拆开
（来源级显著放宽），同出口 NAT 用户的互相影响边界写入文档。
**备选**：只拆阈值不认 XFF——否决，公网多用户共享反代时仍为单一计数
维度，等于没有隔离。

## Risks / Trade-offs

- [展示页公网不可达影响演示] → allowlist 加运维出口 IP；演示可走本机。
- [XFF 信任配置错误导致门控绕过] → 默认不信任任何代理头；清单含
  "伪造 XFF 直连测试"验收项与单测。
- [gate_blocked 摘要含敏感参数（如口令）] → 白名单键提取 + 脱敏，
  非白名单一律不渲染；单测断言。
- [零构建 vanilla 前端可维护性] → 界面态有限（6 个），可接受；
  超出时再立变更引入框架。
- [真实账号演练产生平台脏数据] → 演练用测试品牌/型号前缀，演练后
  走平台删除或标注保留（验收方知情）。
- [77 工具 schema 体积影响 Web 会话成本] → 工具面收敛仍是独立优化，
  不阻塞本变更（与 C6 同口径）。
- [授权激活使所有会话共用同一平台账号身份] → 与现状一致（登录已如此代登），
  本变更不改变归属模型；多账号隔离属后续变更，写入清单风险项。
- [partial 流缺失导致前端空白气泡] → 事件契约已要求 `turn_done` 无可见文本时
  MUST 回落展示本轮最终结果（见 web-chat-ui）。
- [演练产生真实平台写入] → AC-1 默认只跑到确认卡片出现即止；需要真实写入时
  使用测试品牌前缀并留清理记录。

## Migration Plan

1. mcp_server：配置项 + `_exposure_gate` + 单测（矩阵：模式 on/off ×
   本机/远程 × 端点类别）→ 主基线全绿。
2. webchat：payload `arg_summary` + static 前端 + 单测/冒烟 → webchat
   基线全绿。
3. 文档：`docs/deployment/` 公网前置清单。
4. 演练：AC-1/AC-2/AC-3/AC-4 + V11，证据归档；发现缺陷回任务修复后
   重跑对应项。
5. 回滚：任一环节失败，`MCP_PUBLIC_MODE=0` + 前端目录不挂载即恢复。

## Open Questions

- 对外形态（域名/IP:端口）与证书来源现场未定 → 清单按"Caddy 自动
  Let's Encrypt / 既有企业反代"双轨给判据，部署时二选一（不阻塞开发）。
- 确认卡片是否允许"编辑参数后再确认"→ 一期只展示摘要 + 确认/拒绝
  （编辑语义属模型侧，改参数需重新发起）；现场若强烈要求再立变更。
