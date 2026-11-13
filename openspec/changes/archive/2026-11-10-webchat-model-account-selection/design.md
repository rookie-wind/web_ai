## Context

动机见 proposal.md「Why」；行为契约见 specs/agent-runtime-session 与 specs/web-chat-ui
的 ADDED Requirements。当前实现约束（已核实）：

- 模型全局单一：`config.py:126` `agent_model="Qwen3.8-Flash"`（env `WEBCHAT_AGENT_MODEL`
  可配）→ `runtime.py` `_agent_model` → 首轮建句柄 `AdapterConfig(model=...)` →
  `adapter.py:272` `QoderAgentOptions.model`。`create_session` 无模型入参。
- 云凭据全局共享：`api.py:169` 读 env `QODERCN_PERSONAL_ACCESS_TOKEN` → `runtime._pat`
  → 对每个句柄注入同值；`adapter.py:252` `auth=access_token_from_env() if pat_env else
  qodercli_auth()`。`AgentHandle` 已有 `pat_env` 注入口（`adapter.py:113/232`），仅经 env、
  不进命令行。
- 客户端每会话一个、跨轮复用：`adapter.py:190` `_ensure_client` 只构建一次，
  `_build_options`（:229）随之跑一次；`auth` 与 `model` 都在构建期定型。
- SDK 已具备接口：`client.py:705` `set_model()`（流式中途切模型，本适配器恒流式）、
  `client.py:741` `get_available_models()`（账号级目录，返回 `ModelInfo`：
  value/displayName/isEnabled/isFree/priceFactor）。
- 账号库 `webchat_accounts.json` 已 gitignore（`.gitignore:24`）、明文存 phone/code；
  `Account`（`accounts.py:31`）字段 username/password_hash/phone/code/enabled。
- 前端无模型/账号 UI：`app.js:222` 新建会话直接 POST `/api/sessions`（无 body、无弹窗）；
  compose 区已有 `upload-channel` 下拉可参照。

## Goals / Non-Goals

**Goals:**

- 复用既有 `pat_env` 口与持久客户端范式，最小 plumbing 实现按会话账号 + 消息级模型。
- 账号选择与模型清单耦合（清单随账号），但账号会话级、模型消息级的不对称由架构强制。
- 自带 PAT 的混合存储（默认内存、可选记住明文）守住护栏，不引入加密基础设施。

**Non-Goals:**

- 不做 BYOK（自带模型商 key/CustomModel）；不做账号消息级热切；不改 IDE 侧。
- 不触碰 MCP 接入 Token、门禁票据、会话票据、写门禁、审计归属、平台授权激活。
- 不引入加密存储/密钥管理（ADR-0004 已否决）。

## Decisions

**D1 — 账号会话级、模型消息级（不对称）。** 账号凭据在 `_build_options` 构建期经
`auth` 定型，SDK 无账号热切换接口；模型有 `set_model()` 可在同一持久客户端上热切。
故账号在新建会话时绑定、整会话固定（换账号=新会话），模型在轮次边界经 `set_model`
切换、对下一条消息生效。*否决*：账号消息级（需每切重建句柄，破坏 1:1:1 持久客户端
范式、成本高）；模型重建句柄（`set_model` 已免费支持）。

**D2 — PAT 复用 `pat_env` 口，按会话喂值。** `runtime` 由"对每个句柄喂全局 `_pat`"
改为"按会话选定 PAT（默认=全局 `_pat`/本机登录态，自带=用户 PAT）喂 `pat_env`"。
注入仍仅经 env（`adapter.py:232`），自然遵守既有「国内版 SDK PAT 仅经 env 注入」
要求。*否决*：新增 auth 通道（已有口，徒增表面）。

**D3 — 建会话时以 `get_available_models` 一举校验+取清单（eager 连接）。** 该接口需
有效凭据且返回账号级模型目录，故用它同时完成 PAT 有效性校验与下拉清单填充；失败
（含 PAT 无效/过期/品牌不一致握手超时）即拒绝建会话。自带 PAT MUST 为国内版（与
SDK 构建品牌一致）。**连接时机**：`create` 时即建 `AgentHandle` 并 `connect()`
（eager），调 `get_available_models` 校验+取清单存会话，`run_message` 复用该持久
句柄——契合既有「会话创建时 connect()」规格，并把冷启动移到 create。*否决*：独立
校验接口（多一次调用）；临时校验客户端（两次 CLI 冷启动/云握手）；推迟到首轮
（违背"不留可对话但模型不可用的会话"）。

**D4 — 清单过滤与默认预选。** 只取 `isEnabled` 模型；按 displayName 排序，成本标记
渲染为「免费」（isFree）或价格系数（priceFactor）。默认预选：默认账号用配置
`agent_model`；自带账号用清单首个启用模型（配置默认若在清单则优先）。清单按会话
缓存（账号会话级固定）。*否决*：列全部模型含未启用（用户选了不可用）。

**D5 — 消息级模型接线。** `WebSession` 增 `current_model`；发送消息时若与客户端当前
模型不同，在轮次开始前调 `set_model`（不在执行中轮次切换，沿用 `_gen` 代际防串轮）。
模型切换 MUST NOT 动 `pat_env`/`auth`/客户端实例。*否决*：把模型塞进每轮重建选项。

**D6 — 混合存储 + 明文（ADR-0004）。** 默认 PAT 仅存 `WebSession` 内存；勾"记住"则
明文写 `Account.qoder_pat`（per-user，gitignore 库）。新增可选字段，旧账号文件无该
字段正常加载。清除入口删该字段。护栏：PAT 不进日志/命令行、UI 掩码、收紧文件权限。
*否决*：应用层加密（密钥管理单点，复杂度不抵收益）、OS 密钥库（平台绑定）——见
ADR-0004。

**D7 — UI 落点。** 新增轻量"新建会话"对话框：账号单选（默认/自带）+ PAT 掩码框 +
记住勾选（默认不勾）；`app.js` 建会话 POST 携带账号选择，`sessions_api.py:78`
`create_session` 增入参。compose 区紧挨 `upload-channel` 加模型下拉，会话建好后用
该账号清单填充。*否决*：账号选择放 compose（账号会话级，应在创建时刻）。

## Risks / Trade-offs

- [明文 PAT 落盘泄露] → gitignore + 不进日志/命令行 + UI 掩码 + 清除入口 + 文件权限；
  内部可信部署接受残余风险（ADR-0004）；不可信/合规环境需迁移加密（另立 ADR）。
- [默认账号无 PAT 且无本机登录态] → 建会话校验失败明确提示需自带，不留不可用会话。
- [自带 PAT 品牌不一致握手超时] → 校验阶段即失败并提示「需国内版 PAT」。
- [模型切换撞执行中轮次] → 仅在轮次边界 `set_model`，执行中拒绝切换（沿用串行轮次约束）。
- [SDK 临时 payload.json 明文] → SDK 用后即删且警示 never log；webchat 除记住的账号库
  外不额外落盘 PAT。
- [账号订阅变化使缓存清单过时] → 会话级缓存可接受，订阅变化经新会话刷新。

## Migration Plan

- 向后兼容：`create_session` 不带账号选择时回落默认账号 + 配置默认模型（与今天一致）；
  `Account.qoder_pat` 可选，旧账号文件正常加载。
- 部署：无新依赖（SDK 接口已存在）；env 默认 PAT 仍可用。
- 回滚：撤下前端入口与新字段即回落全局模型/共享 PAT 行为；已记住的 PAT 随字段移除失效。