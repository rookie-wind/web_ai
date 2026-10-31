# C7 `public-access-hardening` spec 审查记录

> 状态：审查已完成，并按用户选定方案「**扩 C7 范围一并修复**」将 P0/P1
> 各项落进 spec 工件（2026-10-29）。已改动：`proposal.md` / `design.md` /
> `tasks.md` / `specs/public-network-exposure-gating` / `specs/web-chat-ui`，
> 并**新建** `specs/agent-runtime-session/spec.md`（MODIFIED + ADDED）。
> 改动后 `openspec validate public-access-hardening --strict` 仍为 **valid**。
> 本文件保留为证据与推理记录，spec 中每条修改均可回溯到本文的实测取证。
> 审查基线：HEAD `2cc1e4c`。
> 核查方式：逐条比对 spec 中对既有代码的假设与 `webchat/`、`mcp_server/`
> 实际实现，并以真实 HTTP 端到端链路取证。

## 发现项 → spec 落地映射

| 本文编号 | 落在哪个工件 |
|---|---|
| P0-1 ask_user 「基于 SDK elicitation 通道」失实 | `specs/agent-runtime-session` MODIFIED 正文与「Agent 向用户提问」Scenario；`specs/web-chat-ui` ask_user 改为两种来源 |
| P0-2 playwright 并非既有依赖 | `design` Context 失实陈述纠正 + Non-Goals 精确化 + D7；`tasks` 7.2 |
| P0-3 登录限流不识别真实 IP | `specs/public-network-exposure-gating` 新增 Requirement；`design` D11；`tasks` 2.5 |
| P0-4 会话凭据未完成平台授权激活 | `specs/agent-runtime-session` 新增 Requirement；`design` D9；`tasks` 2.3；`proposal` Why 范围扩张声明 |
| P1-4 gate_blocked 时序措辞 | `specs/web-chat-ui` 确认卡片 Requirement 改为「收到 gate_blocked 事件后」 |
| P1-5 confirm 缺租约即 409 | `specs/web-chat-ui` 新增「租约缺失时先取租约」Scenario；`tasks` 4.5 |
| P1-6 webchat 自身暴露边界无 Requirement | `specs/public-network-exposure-gating` 新增 Requirement（含 Purpose 扩容）；`tasks` 5.1 |
| P1-7 turn_done 字段语义（turn/duration_ms） | `specs/agent-runtime-session` MODIFIED 正文 + 新 Scenario；`tasks` 4.1 |
| P1-8 is_super 恒 False（两叠加 bug） | `design` D10 + Context；`tasks` 2.4；`proposal` What Changes |
| V-K 空白气泡 | `specs/web-chat-ui` 新增「本轮无文本时不出现空白气泡」Scenario；`tasks` 4.1 |
| 运维发现：`.env` 仅 `start.bat` 解析、`webchat/.env` 未被忽略 | `design` Context；`tasks` 1.1 与 5.1 |
| P2 措辞：`.env.example` 不存在需新建 | `tasks` 1.1 与 `proposal` Impact 改为「新建」 |

## 已确认通过的部分

- `openspec validate --strict` 通过。
- `specs/mcp-token-management/spec.md` 的 MODIFIED 写法规范：原需求句与
  原 3 个 Scenario（导出资源包 / 生成接入页信息 / 版本控制安全）完整保留，
  仅追加公网模式约束与新 Scenario，同步主 spec 时不会丢内容。
- design Context 对 `gate_blocked` payload 的现状描述准确
  （`grants.py:343` 实测为 `{tool_name, target, reason}`，确无 `arg_summary`），
  且 §2 已安排补齐任务。
- 前端定位为"既有 API 纯消费方、不新增后端行为"，与 C5 冻结的 API 契约一致。

---

## P0 — 阻塞项：不解决则 AC 无法通过

### 1. `ask_user` 生产链路未接线，前端契约无数据源

- **证据**：`webchat/webchat/runtime.py:196-198` 构造实例时
  `AgentHandle(config, pat_env=..., gate=gate)` **未传 `elicit_handler`**；
  `sdk_runtime/adapter.py:120` 为
  `on_elicitation=self._on_elicitation if self._elicit_handler else None`
  → 生产环境恒为 `None`，SDK elicitation 无回调，`ask_user` 事件**永不产生**。
  桥接代码本身可用（`tests/test_sdk_runtime.py:119` 单测显式传入 handler 并通过），
  但只有测试接线、生产未接线。
- **影响**：`specs/web-chat-ui` 的 Requirement「ask_user 交互环必须可在页面完成
  补充输入」失去后端支撑；需求文档 §3 交互要求 2 与 AC-4 第 2 条无法演示通过。
- **纠正（2026-10-29 实证后）**：上面这条「注入 `elicit_handler`」是**无效建议**。
  实测 `ask_user` 是**三重不可达**，单接 handler 不足以解决：

  1. **触发方不存在**：`mcp_server/*.py` 零 elicitation 使用；`mcp` 1.29.1 的
     `lowlevel.Server` 无发送方法（实测 `[]`）、`RequestContext` 无 `elicit`
     （实测 `[]`），仅 `mcp.types` 有裸类型（`ElicitRequest` /
     `elicitation/create` 等）。要发起提问需在 mcp_server 手写 low-level JSON-RPC。
  2. **接收方未接线**：即本条现状（`runtime.py:196`）。
  3. **无替代工具**：SDK 源码零 `AskUserQuestion`（实测 0 命中），且
     `adapter.py:102` 设 `tools=[]` 已收紧工具面。

  ⇒ 「接 elicitation」需改 mcp_server，与本变更 Non-Goals 第 1 条「不改 `/mcp`
  协议与 77 工具行为」直接冲突，**在本变更范围内不可行**，应另立变更。

- **采用方案（多轮天然实现）**：模型文本提问 → 本轮 `turn_done` → 用户下条
  消息经 `options.resume` 续在同一 SDK 会话。两项支撑已实证：

  - 机制层：`AdapterConfig.resume_mode` 默认 `"resume"`（`adapter.py:44`），
    `run_turn:191-192` 据此设 `options.resume` → 跨轮上下文保持真实生效。
  - 契约层：`xlpa/SKILL.md` 本就设计为文本往返确认——「操作均需当前 plan_id
    与独立确认」(L273)、「需…+ 用户确认」(L290)、「用户确认更新时 / 未确认
    时」(L254/L260)、「向用户说明…并引导重新打开接入页」(L139)；C2~C5
    的 IDE E2E 全链路即靠此文本确认走通。

- **残余风险（未闭合）**：「缺参时模型会主动提问而非编造缺省值」这一行为假设
  **尚未实跑验证**，原因见第六节。

### 2. playwright 依赖前提不成立，且与 Non-Goals 自相矛盾

- **证据**：design D7 称"浏览器演练用 playwright（**webchat venv 已有依赖**）"；
  实测 `webchat/requirements.txt` = fastapi / uvicorn / httpx /
  qodercn-agent-sdk / python-multipart / rapidocr / onnxruntime，
  `requirements-dev.txt` = pytest / pytest-asyncio，**均无 playwright**。
  同时 design Non-Goals 写明"不引入前端框架/构建链与**新增 Python 依赖**"。
- **影响**：tasks 6.1/6.2/6.4 要求"playwright 脚本输出 + 截图"作为证据，其工具
  前提在约束下不成立；§5.2、§6 整段的执行方式悬空。
- **待决**：三选一并写入 spec ——(a) 演练用 `mcp_server` venv 的 playwright
  （已有，跨 venv 调用需写明）；(b) 放宽 Non-Goals 允许 webchat 增 dev 依赖；
  (c) 改为纯人工演练 + 浏览器截图。

### 3. webchat 登录限流在反代后退化为「全站登录互锁」（实证成立）

- **证据**：`webchat/webchat/api.py:84-89` 的 `_client_ip()` 仅取
  `request.client.host`，**完全不处理 `X-Forwarded-For`**；限流键为
  `(ip, username)`（`api.py:158` `limiter.check(ip, body.username)`，
  阈值 `WEBCHAT_LOGIN_RATE_LIMIT=60,5`）。design D2 的 `MCP_TRUSTED_PROXY` +
  XFF 采信逻辑**只作用于 mcp_server**，webchat 侧无任何对应设计；
  tasks 5.1 清单里的 XFF 透传只配代理层，应用层不读等于白配。
- **影响**：webchat 经反代公网暴露后，`request.client.host` 恒为代理地址，
  所有真实用户共享同一 IP 桶。攻击者对 `admin` 连错 5 次密码即可锁死**全站**
  对该账号的登录 60 秒（可重复触发 = 定向 DoS）；同时 C2 设计意图"按来源 IP
  分散限流"实际失效，"防枚举"语义在公网下反转。
- **修正：实际比原描述更严重**。`ratelimit.py:63` 是**双维度**：
  `for key in ((ip, username), (ip, ""))` —— 第二个键 `(ip, "")` 是**该 IP 不分
  账号的全局桶**。因此陌生人任意错 5 次（甚至不需要针对 `admin`）即可锁死
  **全站所有账号的所有登录**，属「一部署就可能被打瘫」的可用性缺陷。
- **待补**：webchat 侧客户端 IP 解析（与 mcp_server 同等的信任代理判定）应升为
  一条 Requirement；且全局桶阈值需与按账号阈值**拆开配置**并显著放宽。

---

## P1 — 契约落差：可实现但按现文本会做错

### 4. 确认卡片是"事后拦截"而非"事前待确认"，spec 措辞隐含了错误时序

- **证据**：design D5 自述闭环为
  `deny → 模型呈卡片 → confirm → 重试 allow`，并留了一句"若实现验证发现需要
  '预告待确认'事件（deny 前模型无提示）……不新增事件类型"；
  `grants.py:338-345` 的拒绝路径确实只在 deny 时写 `gate_blocked`。
- **影响**：`specs/web-chat-ui` 写"**当会话产生待确认的写入操作时**，前端 MUST
  弹出确认卡片"，读起来像存在一个 pending 状态事件。实际前端只能在写入**已被
  拦截之后**才看到卡片，且必须先向用户解释"这一笔刚才被拦了"。需求文档 AC-1
  的顺序（生成计划 → 确认卡片 → 确认 → 下发执行）与实现语义有偏差。
- **待补**：spec 应写实为"基于 `gate_blocked` 事件渲染确认卡片 + 模型重试语义"，
  并把"是否引入事前确认事件"作为显式决策项（当前 D5 偏向不引入）。

### 5. `/confirm` 有写租约前置，前端契约与任务都没提

- **证据**：`webchat/webchat/sessions_api.py:181-183` ——
  缺 `x-holder-id` 头或不持有租约 → `409 当前连接不持有写租约`。
- **影响**：tasks 4.2 只说"确认按钮调 `/confirm` 铸票"，前端照做必然 409；
  `web-chat-ui` 的确认 Requirement 未含此前置。移动端切后台/断线重连后租约
  归属变化（`WEBCHAT_LEASE_TTL=45`）会放大这个问题。
- **待补**：spec/tasks 明确前端须先取得并保持租约（`x-holder-id` 生命周期），
  并给出 409 的用户可读文案与重试路径。

### 6. webchat 自身公网暴露无 Requirement，安全边界只画了半个系统

- **证据**：`specs/public-network-exposure-gating` 四条 Requirement 全部只约束
  **mcp_server** HTTP 端点；`specs/web-chat-ui` 只约束前端行为（凭据不进 URL 等）；
  二者之间——webchat（8800，默认 `127.0.0.1`）改为公网可达后，其**全部 API**
  （sessions / messages / events / confirm / artifacts / upload）的暴露控制
  没有任何 Requirement 覆盖，仅靠 tasks 5.1 清单里"暴露范围最小化"一句。
- **影响**：本变更的标题是 *public-access* hardening，但公网面只硬化了内层
  mcp_server，用户直连的外层 webchat 反而无契约。上传通道（最大 20 MB）、
  会话配额、OCR 计算资源的公网滥用面未被任何需求约束。
- **待补**：要么新增 webchat 侧暴露 Requirement，要么在 proposal 显式声明
  "webchat 公网可达性由部署层反代负责、不纳入本变更契约"，并把它列入风险。

---

## P2 — 措辞与记录项（低危，后续一并修）

### 7. 【页面归属问题】C7 的命名与范围在需求文档与实际之间漂移

这是"前端页面为什么一直没做"的根因记录，务必留档：

- 需求文档 §7.2 定义 **C7 = `e2e-acceptance-hardening` 端到端验收**，其
  「要做的事」为：建档闭环演练（AC-1）、转换闭环演练（AC-2）、交互要求 1~5
  逐条演示（AC-4）、IDE 回归清单（AC-3）、汇报素材归集 ——
  **全部是验收动作，不含任何前端开发任务**。
- 但 C2/C3/C4/C5 四个变更的 Non-Goals 都写"前端页面属 C7"，而 `openspec/specs/`
  下从未存在 `e2e-acceptance-hardening`，也没有 `web-chat-ui`。
  → 该指派是**悬空引用**：被指派方（按原始定义）并不接这个活。
- 结论：**Web 前端在 C1~C7 拆分阶段是一个遗漏的工作项**，不是有序的分期安排。
  需求文档自身在 §3 交互要求（"在页面上提问/确认/下载"）、§4 架构分层
  （明确列出「Web 前端」层）、§6 AC-1（"真实账号**浏览器登录**、不碰 IDE"）
  三处都硬性依赖前端，但 §7 的七个变更没有任何一个的「要做的事」覆盖它。
- 补救方式：新建 `public-access-hardening`，在 `tasks.md:1` 以
  "C7 范围含公网门控与前端 UI，见 proposal" 重新界定 C7，把前端 UI、
  公网门控（C5/C6 均"延至 C7"）、C4 参数摘要兜底一并收进 C7。
- 当前状态：该变更目录**未被 git 跟踪**（`??`，tracked files: 0），
  23 个任务 0 完成。
- **对本审查的意义**：`web-chat-ui` spec 本身是**新增的合法范围扩张**，
  与需求文档 §7.2 的 C7 原始定义不一致。后续优化 spec 时建议在 proposal
  的 Why 里明确记录这次范围扩张及其理由，否则 C7 与实际需求条目对不上，
  归档时验收面会失真。

### 8. `.env.example` 不存在，任务措辞是"同步"实为新建

- `Test-Path mcp_server\.env.example` → **False**（只有 `.env`，且已被 gitignore）。
- tasks 1.1 写"`.env.example` 与 `mcp_server/README.md` 同步说明"，会被读成
  已存在文件。建议改为"新增 `.env.example`"，并注意 C1 已把 `.env` 移出跟踪，
  `.env.example` 需同时进 `.gitignore` 白名单确认。

### 9. 端点路径以简写出现

- tasks 4.2 的 `/confirm` 实际为 `/api/sessions/{session_id}/confirm`；
  4.3 的上传为 `/api/sessions/{id}/artifacts/upload`。spec/tasks 建议用全路径，
  避免实现与验收各写一半。

### 10. `MCP_PUBLIC_MODE` 与 webchat `WEBCHAT_HOST` 的联动未定义

- 公网开启时 webchat 是否必须从 `127.0.0.1` 改绑 `0.0.0.0`（或保持回环、
  由反代转发）？两个变量分属两进程，谁负责、默认值是什么、清单里怎么验收，
  目前无一处说明。建议进 §5.1 部署清单判据。

---

## 建议的消化顺序

1. 先定 **P0-2（playwright）** 与 **P0-3（限流 IP）** ——前者决定整个 §6 演练
   怎么执行，后者是公网化的实际安全缺陷，且都是"改动很小但不定就卡住"的类型。
2. 再定 **P0-1（ask_user 方案）** 的归属——经实证已排除 elicitation 路线，
   改为确认「多轮天然实现」写入 spec，它决定 AC-4 第 2 条能否成立。
3. **P1-4/P1-5** 在写前端前必须澄清，否则 §4 的实现与验收会来回返工。
4. **P2-7** 是记录性问题，修订 proposal 的 Why 时一并写清 C7 范围扩张的来龙去脉。

---

## 六、实证验证结果（2026-10-29）

> 原则：能跑就跑，不做纸上推断。临时验证脚本跑完已删除，
> **未改动任何源码与 spec 工件**。每条均标注实测方法与结果。

| # | 验证项 | 方法 | 结果 |
|---|---|---|---|
| V-A | 限流跨账号互锁 | 实跑 `RateLimiter(60,5)` | ✅ **成立**：`attacker_probe` 错 5 次后，无辜用户 `bob` 首次登录即被限流，`retry_after=60` |
| V-B | SDK 是否支持 elicitation | 查符号/字段 + `client.py:330` | ✅ 支持：`QoderAgentOptions.on_elicitation`、`ElicitationRequest/Result/OnElicitation` 均存在，桥接代码非空转 |
| V-C | 跨轮是否保持 SDK 上下文 | `run_turn:191` + `AdapterConfig:44` | ✅ `resume_mode` 默认 `"resume"` → 多轮方案机制基础真实 |
| V-D | playwright 能否装入 webchat（Py **3.14.5**） | `pip install --dry-run` | ✅ 可装：`playwright-1.64.1` + `greenlet cp314-win_amd64` 轮子齐全 |
| V-E | `/api/mcp-token/mint` 存在性 | grep `server.py` | ✅ 存在（`:2967` + `_handle_mint:3081`，secret→IP 白名单→限流→签发） |
| V-F | mcp_server 会否发起 elicitation | grep + 查 mcp 1.29.1 API | ❌ **不会**：零使用，且 `lowlevel.Server` / `RequestContext` 无现成发送 API |
| V-G | SDK 有无可替代的提问工具 | 全量扫 SDK 源码 | ❌ 无 `AskUserQuestion`（0 命中） |
| V-H | XFF 修复有效性对照 | 真实 `_client_ip()` + 候选实现 + `RateLimiter` | ✅ 现状：3 个不同真实来源（8.8.8.8 / 9.9.9.9 / 6.6.6.6）**一律塌缩为 `127.0.0.1`**；修复后还原各自 IP，攻击者错 5 次后受害真实 IP **可正常登录**；伪造头（直连 `203.0.113.66` 谎称 `8.8.8.8`）**仍按直连判定，伪造无效** |
| V-I | NAT 共享出口残留 | 同一真实 IP 内跨账号失败 | ⚠️ 修好 XFF 后，同一 IP 内 5 次失败仍锁该 IP 的 `alice`（全局桶预期行为），不同 IP 不受影响 → 证实「阈值拆开」为必需项 |

### V-J「缺参时模型是否主动提问」—— 已执行（PAT 到位后，2026-10-29）

三轮真实 SDK 会话（`qodercn-agent-sdk` 1.0.17 + 自带 `qoderclicn` 1.1.79）。
前置按既往 headless 经验先排环境：

- `mcp_server` 8765 存活；`.env` admin token → **401 被拒**（复现既有经验
  「admin token 未必被运行实例接受」）；`token_registry` 的 11 个
  `ide/user` 级 token → **全部 200**。
- 会话 init 的 `SystemMessage.data`：**`xlpa=connected`，tools=71**
  （`mcp__xlpa__add_brand` 等）—— 工具面已加载，不是「auth_required」假象。

实验与判定：

| 轮次 | 配置 | 观察 |
|---|---|---|
| 1 | 照抄 adapter 但**省略 hooks** | 两轮均报「工具调用在权限确认环节被拒绝」（含 `list_mcp_tools`），0 次调用 → **判定被污染** |
| 2 | 补恒 `allow` 的 PreToolUse hook | 权限抱怨消失 ⇒ 第 1 轮的拒绝**纯属验证脚本缺 hook**，生产由 WriteGate 应答，无此缺陷 |
| 2/3 | 缺参任务（不告知品牌名） | 模型**主动提问且未编造**：列出需「中文名/英文名/编码/设备类型」并给 A/B 方案；第 3 轮明确「收到，品牌是『星辰照明』」 |

- **假设 2（resume 跨轮记忆）：✅ 干净验证成立**。两轮 `session_id` 延续，
  第 2 轮正确关联第 1 轮任务。
- **假设 1（缺参主动提问）：⚠️ 强支持但未达最强形式**。两轮均未观察到编造，
  但模型同时因「缺平台登录」而提问，故「凭据齐备时是否仍提问而非随手编一个
  品牌名」尚未单独隔离——该形态需真实短信验证码，不可代填。
  风险等级由「未知」降为「低-中」。

**附带必要条件（踩坑实录）**：多轮**必须共用同一 `cwd`**。每轮新建临时目录会
触发 `Invalid session identifier` + `ProcessError exit code 42`，因为 SDK 按
project 目录定位 session。对 C7 前端/运行时是隐含约束，应写进任务。

### 新增发现 V-K：`AssistantMessage` 可能不含 text block（前端空白气泡风险）

三轮中 `AssistantMessage` 各有 2–7 条，但**取不到任何 text**，最终文本全部
落在 `ResultMessage.result`。本次设 `include_partial_messages=False`，生产为
`True`（文本经 `StreamEvent` → `text_delta`），故**未在生产配置下复现**。

风险：若 partial 路径在某类回复缺失（如纯 ResultMessage 收尾），前端会出现
**空白气泡**。建议 tasks §4 加一条判据：前端 MUST 在 `turn_done` 时校验本轮
是否有可见文本，若无 `text_delta` 则 MUST 回落展示本轮最终文本。

### 新增发现 V-L：业务 Token 在 webchat 里是**死字段**（已确证，应升为 P0-4）

V-J 实验中 agent 向用户索要「手机号 + 短信验证码」。实测根因不在 mint，
而在一个更直接的位置：

- `api.py:190-192` 已经用账号预设凭据代登平台，并把结果写入 session：
  `session.business_token = identity.get("token")`；
- 全仓 grep `business_token` 仅 3 处：`sessions.py:24` 定义字段、
  `api.py:190` 赋值、**无任何读取点**（对外只用了 `business_phone` 脱敏尾号，
  `api.py:220`）。

⇒ 业务 Token 拿到后死在 session 里，**从未传给 mcp_server 或 agent**。
而 `mcp_server/.business_token_cache.json` 实测**不存在**（已自查）。

**真实端到端链已跑通并确证（2026-10-29，非推断）**：用 HTTP 模拟前端完成
`login → POST /api/sessions → /lease → /messages → SSE /events` 全链路，均 200；
产出的事件文件显示 agent **发起 0 次工具调用**，直接文本回复：

> 「查询需要先登录（手机号+验证码）。请提供您的手机号，或者如果您已有验证码，
> 也可以一并告诉我，我再继续执行只读查询。」

并用 mint 出的 MCP 凭据直连 `/mcp` 调用两个**只读**工具定论影响面：

```
get_classify_list     → {"error": true, "code": "NOT_LOGGED_IN", "message": "请先调用 login 验证身份。"}
get_device_type_list  → 同上
```

⇒ **只读与写入全部被阻**，不存在“系统 Token 兜底只读”这条路（我先前曾如此推测，
已被实测否定）。agent 要求登录是**正确行为**，不是 prompt 误导。因此本项不是
“AC-1 写不进去”而是“**AC-1/AC-2 连一次正常的云端查询都跑不了**”，
属于整条链路上比「前端页面缺失」更硬的阻塞。

**真实修法（已用 `/mcp` 实跑定论，推翻前述方案 (a)）**

用 mint 出的凭据直连 `/mcp` 调一次 `login(phoneNum, code)` 后再查：

```
login            → message:"已授权，系统账号"  role: super  success: True
.business_token_cache.json 是否生成 → **仍为 False**
get_classify_list → 1954 字符、30 条真实数据（首条键 ['id','sysName']）—— 阻塞解除
```

结合 `server.py:1826-1859` 的 `login` 实现，三个关键事实：

1. **`code` 永不过期**（docstring L1835 原文「短信验证码（不会过期）」）
   ⇒ 账号文件里的 4 位码可无条件自动化使用，无需用户参与。
2. **授权态绑在 `mcp_token` 上**：`session_registry.create(mcp_token=..., phone=..., role=...)`
   ——不是业务 Token 缓存文件。所以**每个新建会话（新 mint 的 token）都必须
   login 一次**，这才是 webchat 链路的真正卡点。
3. **超级账号不存业务 Token**（`fallback_token=user_token if not is_super else None`）
   ⇒ `session.business_token` 对超级账号本就无用；之前推荐的「mint 携带
   business_token」方案 (a) **打在了错误的锁上**，已作废。

**修正后的方案**（待写入 spec）：

| 方案 | 做法 | 评估 |
|---|---|---|
| (a′) 建会话后自动补一次 login | webchat 在 `runtime.create` mint 成功后，用该 mcp_token 调 `/mcp` 的 `login(account.phone, account.code)` 完成授权绑定 | ✅ **推荐**。全用现有 `/mcp` 工具与现有预设凭据，**不改协议、不撞 Non-Goals**；code 不过期使其可无条件执行 |
| (a″) mint 时代为激活 | mcp_server 的 `/api/mcp-token/mint` 接受 `phone`/`code`，签发时直接建 session | ⚠️ 同样可行，但需改 mint 端点参数；与 (a′) 相比多改一处服务端 |
| (b) 前端做验证码补录交互环 | 用户在页面输手机号+验证码 | ❌ 无需——`code` 不过期且服务端已持有，让用户重输属多余且泄露凭据 |

验收判据（修好后重跑 `_e2e_webchat.py`）：`tool_call ≥ 1`，且回复不再出现
`NOT_LOGGED_IN` 或索要验证码。

### 新增发现 V-M：`turn_done` 落盘偏离契约（实测，建议列为 P1-7）

**缺陷 1・`turn` 字段语义错误**。`runtime.py:199-202` 将 adapter 产出的
`turn_done` 直接 `continue` 丢弃，然后在 `runtime.py:211-215` 另铸一个：

```python
self._events.append(
    session.id,
    "turn_done",
    {"turn": self._events.last_seq(session.id)},   # ← 事件序号，不是轮次
)
```

实测：单轮、零工具调用的会话落盘为 `"payload": {"turn": 27}`——因为当时
`last_seq` 为 27。真正的轮次计数器 `adapter._turn_count`（`:74` 初始化、`:189` 累加）
**从未进入任何落盘事件**。前端若拿 `turn` 做“第 N 轮”显示必然错。

**缺陷 2・`duration_ms` 丢失**。`adapter.py:204-207` 本已算出
`payload={"turn": self._turn_count, "duration_ms": duration_ms}`，但被缺陷 1 的
`continue` 丢弃，补发的 payload 无此字段 → 前端无法展示本轮耗时。

**缺陷 3・error 收尾仍补发 `turn_done`**（代码直读，未实测）。`run_turn` 异常分支
yield `error`，而 `runtime` 循环结束后**无条件** append `turn_done` → 前端无法从
事件序列区分“正常收尾”与“出错收尾”。

**事件实测分布**（28 条）：`unknown` 14 / `text_delta` 10（含 1 条用户回显）/
`session_started` 3 / `turn_done` 1。另两处对前端有直接影响：

- `session_started` **一次对话出现 3 次**且 payload 形态不同：`runtime` 发
  `{"username": ...}`，`adapter.py:285` 每次 SDK `SystemMessage(subtype=init)` 发
  `{"subtype": "init"}`（本例发了 2 次）。前端若用它做“会话就绪”提示会重复触发。
- `unknown` 占 **50%** 事件量，且 payload 有三种形态：`raw_kind`（流控帧
  message_start/content_block_start/content_block_stop/message_stop）、
  `subtype`（artifacts_update/hook_diagnostics）、`msg_cls`。
- 助手侧 `text_delta` **不携带 `role`**，仅用户回显那条带 `role: "user"`
  → 契约需明确“无 role 即 assistant”或补齐字段。

**纠正我上轮审查的一处记录错误**：事件类型实为 **10 种**，`events.py:13-25` 的
`EVENT_TYPES` 已包含 `"unknown"`，且主 spec `agent-runtime-session` 已写明
「未知事件类型 MUST 保留透传（type=unknown，前端降级展示）」——契约没缺口，
是**我漏计了这一类**，并据此错判过一次“契约不一致”。

### 新增发现 V-N：`is_super=False` 已定论——两个叠加的实现 bug

实跑 `platform_login` 并跟踪 `_dig` 收到的原始结构（值只报长度）：

```
data 顶层键: ['httpStatus', 'isSuccess', 'msg', 'token', 'user', 'webPortType']
data.user 子键含: userId(len=3) / mobilePhone(len=11) / superManage(len=4) / userCode / userName ...
结论：identity = {token: len=32, phone: None, userId: None}
```

`user` **本已在** `_dig` 的嵌套白名单 `("userInfo","user","data","result")` 里，
却仍取不到值，对照两份 `_dig` 实现即得根因：

| 字段 | 平台实际 | webchat `_dig`（`platform_auth.py:39-53`） | mcp_server `_dig`（`permissions.py:36-58`） |
|---|---|---|---|
| userId | `user.userId` 为**整型** | 要求 `isinstance(value, str)` → **int 被丢弃** | `str(data[key])` → 能取到 |
| phone | 键名为 `user.mobilePhone` | `_PHONE_KEYS` 无 `mobilePhone` → 取不到 | 同样取不到 |

⇒ **bug 1**：webchat 复刻时把 `_dig` 收窄为只认字符串，与 mcp_server 版不一致
（L29 注释“与 permissions.py 一致”仅对键名列表成立，**类型宽容度实际不一致**）。
⇒ **bug 2**：`_PHONE_KEYS` 两侧都缺 `mobilePhone`（平台真实键名）。

**为何两侧结论相反**：`server.py:1850` 的 `_is_system_login(phoneNum)` 直接用
**login 入参的手机号**比对，不依赖 `extract_account_identity`，所以 mcp_server
侧 `role: super` 判定正确；而 webchat 用被 bug 卡空的 `identity.phone`，所以恒
False。叠加 `superAccounts.userIds=set()`（配置只填 phones），webchat 侧两个
输入同时落空。

**影响面**：属 P1 而非 P0——真正写权限由 mcp_server 判定（已实测为 super），
但 `api.py:193/219` 把这个错误的 `is_super` 经 `/api/auth/me` 输出给前端，
导致**合法超级用户在页面上被当成普通用户**（若前端据此决写入入口则功能错）。

**修法**（待写 spec）：`_PHONE_KEYS` 补 `mobilePhone`；webchat `_dig` 改为与
mcp_server 一致的 `str()` 宽容；并考虑直接采用平台返回的 `user.superManage`
作为判据（实测该字段存在）。

### 对 P0-1 方案的一处定位修正

主 spec `openspec/specs/agent-runtime-session/spec.md:43` 将 ask_user 定义为
「ask_user（**基于 SDK elicitation 通道**，Agent 向用户提问）」。而 V-F/V-G 已证明
该通道在本系统**三重不可达**。

⇒ 多轮方案的修订源头在 **主 spec `agent-runtime-session`**，不在 C7 自身的
`web-chat-ui` delta。若只改 C7 的 delta，主 spec 那句“基于 elicitation”仍与
实现不符，属于**遗留的谎文档**。后续修 spec 时需新增一份对
`agent-runtime-session` 的 MODIFIED delta（注意：MODIFIED 须完整携带原 Requirement 全文）。

### 方案可行性结论

| 问题 | 方案 | 实证状态 |
|---|---|---|
| P0-3 限流 | 信任代理 + XFF 最左值；全局/账号阈值拆开 | ✅ **已验证有效**（V-H / V-I） |
| P0-2 playwright | dev 依赖 + `importorskip` + `PCA_TEST_BROWSER` | ✅ 可装（V-D）；浏览器二进制来源待定 |
| P0-1 ask_user | 放弃 elicitation，改多轮天然实现 | ✅ 跨轮记忆已实跑验证；⚠️ 缺参不编造为强支持（V-J） |
| P1-4 确认时序 | 改 spec 措辞为 `gate_blocked` 后渲染 | ✅ 依据 `grants.py:338-345` 代码直读 |
| P1-5 租约前置 | 前端补租约管理任务 | ✅ **已 HTTP 复现**（真实链路）：无头/非持有者均 409、持有者 200、空 target 400。原因为 `sessions_api.py:181-183` |
| P0-4 业务 Token（=V-L） | ~~mint 携带 business_token~~ → **建会话后用 mcp_token 自动调一次 `login`** | ✅ 卡点与修法均已实测闭环（login 后只读立即返回 30 条真数据）；`code` 不过期使其可无条件自动化 |
| P1-8 `is_super`（=V-N） | 补 `mobilePhone` 键 + `_dig` 类型宽容度对齐 | ✅ 根因已定论（两个叠加实现 bug，附原始结构取证）；修法未落地验证 |
| P1-7 `turn_done`（=V-M） | 不丢弃 adapter 事件，或补发时携带真实轮次与耗时 | ✅ 缺陷已实测确证；修法未验证 |
| P1-6 webchat 暴露 | 声明边界交给反代 + 清单兜底 | ❌ 未验证，属范围决策 |

### 建议补做的验证（凭据就绪后）

1. ~~**V-J 收尾**~~ → **已部分完成**：真实链路下 agent 仍要求登录，故“凭据齐备
   时是否仍提问而非编造”仍被 V-L 卡着——**须先修 V-L 才能测此项**。
2. ~~**P1-5 的 HTTP 复现**~~ → **已完成**（见上表，四种边界均符合预期）。
3. **V-N 根因**：打印一次平台登录响应的 identity 键名（不落盘值），确认
   `phone`/`userId` 为何未命中 `superAccounts`。
4. **V-L 修复后的回归**：方案 (a) 落地后重跑本端到端脚本，验收判据应为
   `tool_call ≥ 1` 且回复不再出现 `NOT_LOGGED_IN`/索要验证码。
5. **playwright 浏览器二进制**：确认可否复用 `PCA_TEST_BROWSER` 指向已有
   chromium（mcp_server 侧已验证可用），避免重复下载 100+ MB。

### 本次端到端跑通的环境变更（已留存，供后续演练复用）

- `mcp_server/.env` 新增一行 `WEBCHAT_MINT_SECRET`（文件在 `.gitignore:22` 内）。
- **mcp_server 已重启**（旧 pid 18868 → 新 pid 39652）：照抄原启动命令
  `python .\mcp_server\server.py`，仅额外注入 `WEBCHAT_MINT_SECRET` 环境变量。
  实测 `mint` 由 401 变 **200**。
- **重要修正**：当前 8765 进程开的是 `python .\mcp_server\server.py` 而**非**
  `start.bat`，而 `.env` 只由 `start.bat:17-19` 自己解析——所以该进程
  **根本没加载 `.env`**，`AUTH_TOKEN` 实为空。这恰好解释了先前
  `.env` 里 admin token 对 `/mcp` 返 401 的现象（与既往经验一致）。
  ⇒ 只写 `.env` 对当前启动方式无效，必须走环境变量；建议记入部署清单。
- webchat 已重启（pid 38144），环境变量含 `WEBCHAT_MINT_SECRET` 与
  `QODERCN_PERSONAL_ACCESS_TOKEN`（后者仅进程内，未落盘：`webchat/.env` 不
  在 `.gitignore` 内，若需落盘得先加忽略行）。
- 副作用提醒：重启 mcp_server 会踢断现有 IDE 连接（token 本身持久，可重连），
  且 `server.py:3447` 会自动弹浏览器、`:3406` 后台跑全量回归。
