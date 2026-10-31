## Why

C1~C6 已把 Web 会话运行时、写入门禁、产物交付与转换执行补齐，但系统仍是
"内网假设"：mcp_server 的 `/api/access-info` 会对任意来源自动分配并回显
Token，`/api/showcase/data`、Skills 导出与 `/api/archive/templates/<id>?owner=`
（file_id 即票据）等端点无需鉴权或把凭据放进 URL —— C5/C6 均明确将这些
端点的公网门控**延至本变更（公网前置清单）**。同时 webchat 只有 JSON API
**没有任何前端 UI**，用户无法在浏览器完成登录、聊天、确认写入与下载产物；
C4 归档时明确"确认卡片带参数摘要兜底"是其 grant 粒度不校验参数的**硬依赖**。
需求文档 §5 的 AC-1~AC-4 端到端验收也从未以真实浏览器路径完整走通。

**本变更范围已据实测扩张**（原 proposal 未声明以下三项，现纳入，因为它们
是 AC 验收能否跑起来的前置条件，不修则 AC-1/AC-2 一次正常云端查询都
无法完成）：真实链路端到端取证发现（i）新建会话的接入凭据从未完成平台
登录绑定，任何云端工具（只读与写入）均返回未登录；（ii）主 spec 将
`ask_user` 定为「基于 SDK elicitation 通道」，经核对该通道在本系统不可达，
而提问实际靠本轮结束后的多轮对话实现；（iii）登录限流不识别真实客户端
IP，经反代后退化为全站登录互锁。三者分属 C3 运行时与 C2 账号层的实现
缺陷，因其阻塞 AC 验收而非顺手重构，在本变更一并修复。

## What Changes

- **mcp_server 网络暴露模式（服务端改造 + 部署清单，用户已确认该形态）**：
  新增开关（默认关闭 = 既有内网行为零变化）；开启后对既有 HTTP 端点分级
  门控——无鉴权展示类端点（access-info / showcase / skills 导出 / 静态页）
  仅本机或显式 allowlist 放行；URL 携凭据类端点（templates 票据下载、
  `/api/logs` 的 `?token=` 查询串鉴权回退）非本机来源要求 Bearer 头且
  归属一致；`/mcp` 与 mint 既有鉴权不变。
- **webchat 自身公网暴露口径**：保持默认仅绑定环回地址；对外服务 MUST
  经反向代理只暴露 webchat 所需路径（HTTPS 终止 + SSE 关缓冲），webchat
  端口与 mcp_server 均不得直接暴露公网；部署前置清单 MUST 同时覆盖
  webchat（8800）与 mcp_server（8765）两台服务的处置项。
- **webchat 前端 UI（新增，当前为零 UI 纯后端）**：单页应用由 webchat
  静态挂载（端口 8800），覆盖登录、会话列表/创建、消息输入与 SSE 事件流
  实时渲染（含断线重连与游标重放回看）、ask_user 补充输入、**写入确认卡片
  （带计划/工具参数摘要，调用 C4 confirm 端点铸造 grant）**、产物上传入口
  与 artifact 事件下载（来源 A；header/grant 取回，凭据不进 URL）。
- **端到端验收演练**：真实浏览器完成 AC-1 建档闭环（未确认零写入）、
  AC-2 转换闭环（上传文档 → 映射 → 配置 → 沙箱测试通过 → 页面下载）、
  AC-3 IDE 回归（IDE 既有 71+6 工具用法零变化）、AC-4 交互要求 1~5 逐条
  演示；V11 限流表现验证；证据归档 `validation/public-access-hardening/`。
- **验收前提修复（新增，见 design D9~D11）**：会话创建后用预设凭据自动
  调一次 `login` 完成平台授权激活（失败即拒绝创建）；身份提取补齐
  `mobilePhone` 键名与整型取值，修正 `is_super` 恒 False；webchat 登录限流
  改为可信代理下取真实客户端 IP，并拆开账号级与来源级阈值。
- 遵循 CN-SDK 部署契约（需求文档 §7.3 规则 5）：PAT 用
  `QODERCN_PERSONAL_ACCESS_TOKEN`，MCP 鉴权用 registry ide/user 级 token。

## Capabilities

### New Capabilities
- `public-network-exposure-gating`: mcp_server HTTP 端点的网络暴露分级门控
  （公网模式开关、默认内网行为不变、非本机来源的鉴权收紧）与公网部署
  前置清单（HTTPS、SSE 缓冲、真实客户端 IP）。
- `web-chat-ui`: webchat 单页前端——登录、会话、事件流渲染与重放、ask_user、
  确认卡片（参数摘要 + confirm 铸票）、产物上传与下载入口。
- `web-e2e-acceptance`: Web 路径端到端验收标准（AC-1~AC-4）作为可重复
  行为契约，证据落 `validation/`。

### Modified Capabilities
- `agent-runtime-session`: 事件契约中 `ask_user` 的来源（剔除不可达的
  elicitation 单一通道说法，改为事件型与本轮结束型两种来源）与
  `turn_done` 字段语义（`turn` 必为真实轮次序号、`duration_ms` 不可丢失）；
  新增「会话接入凭据必须完成平台授权激活」要求。
- `mcp-token-management`: "Token Registry 必须作为本地敏感运行态文件处理"中
  接入信息接口对任意来源分配并回显 Token 的行为，增加公网模式约束
  （非本机来源在公网模式下不再分配/展示 Token）。

（说明：`showcase-access-experience` 经逐条比对无需 Modified——展示/接入页
的访问范围收紧由新能力 `public-network-exposure-gating` 的门控需求覆盖，
其既有需求在公网模式下仍全部成立。）

## Impact

- **mcp_server（代码）**：`server.py` 路由层加端点分级门控（约一个判定函数 +
  各 handler 前置检查）；新环境变量与 `.env.example`/README 说明；工具面
  （77 工具）与 `/mcp` 协议零改动。
- **webchat（代码）**：新增静态前端目录与挂载点（不新增运行时 Python 依赖；
  如引入构建步骤则限定在静态目录内）；既有 API（sessions/messages/events/
  confirm/artifacts）契约不变，前端为纯消费方。**因范围扩张而需改后端**：
  `sessions_api.py`/`runtime.py`（授权激活）、`platform_auth.py`
  （`mobilePhone` 与类型宽容）、`config.py`/`api.py`（可信代理与限流阈值
  拆分）；`webchat/requirements-dev.txt` 新增 playwright 声明（仅 dev）。
- **docs**：新增公网部署前置清单（`docs/deployment/`）；`mcp_server/.env.example`
  为**新建**文件（当前不存在，`.env` 需按 `permissions.template.json` 范式出模板）。
- **测试与证据**：端点门控 pytest（本机/非本机 × 开关 on/off 矩阵）；
  授权激活、`is_super`、限流真实 IP 三项各配回归用例；
  webchat pytest 与主 pytest 基线保持全绿；AC-1~AC-4 演练证据（截图/
  测试输出）归集 `validation/public-access-hardening/`。
- **兼容**：IDE 路径与内网客户端零影响（开关默认关）；公网模式为显式启用，
  启用后行为变化仅涉无鉴权展示端点与 URL 凭据端点的非本机来源。
- **依赖**：C1~C6 全部完成（已满足）；V11（免费档位限流）在本变更验证收口。
