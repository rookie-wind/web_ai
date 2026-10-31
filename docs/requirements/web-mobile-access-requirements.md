# Web/移动端接入需求文档（xlpa 协议智能体平台）

> 状态：**已与需求方确认**（2026-10-27），作为后续多个 OpenSpec 变更的需求基线。
> 关联材料：
> - `docs/architecture/web-chat-agent-runtime-solution.md`（上一轮方案底稿，设计结论 D1~D15 的出处）
> - `validation/manual/v1v3/`（既有验证资产：SDK 连通 / Hook 拦截 / schema 成本实测）
> - `.ua/knowledge-graph.json`（知识图谱，2026-10-27 分析，350 节点）

---

## 1. 原始需求

### 1.1 背景

当前客户端使用模式：用户通过接入页获取接入配置，在 IDE 中接入 xlpa 的 MCP，
再由 IDE 调用 MCP 工具完成协议转换、建档等操作。**业务闭环只能在有人值守的
IDE 里完成**。现场与移动端使用者没有 IDE，无法独立走完业务链路。

### 1.2 目标

在 IDE 接入之外，新增 Web/移动端接入路径：

- 用户在浏览器/手机上登录后直接提出需求（文字、文档或图片），
  由平台的 AI Agent 调用 xlpa 的 MCP 工具完成任务。
- **IDE 接入路径保持原样，功能与行为不受任何影响。**
- Web 会话与 IDE 会话使用**同一套 Skills** 承载业务能力。
- **能力对等**：IDE 能完成的业务，Web/移动端同样能完成，
  不应存在"IDE 可做而 Web 不可做"的功能。包括但不限于：
  1. 平台数据查询；
  2. 设备建档全流程；
  3. 协议转换全流程。

### 1.3 交互要求

| # | 要求 |
|---|---|
| 1 | 过程实时可见：Agent 的中间输出、工具调用进展实时展示；页面刷新或断线后可回看完整过程 |
| 2 | 需要补充信息时，Agent 在页面上向用户提问 |
| 3 | 写入/下发类操作必须经用户在页面上明确确认后才执行；确认由服务端验证，不依赖模型自述 |
| 4 | 产物（模板、报告、转换配置等）可在页面查看与下载 |
| 5 | 输入支持文字、文档、图片 |

### 1.4 并发

按正常 Web 服务使用：多用户同时使用、同一用户多任务并行，
用户之间、任务之间相互隔离、互不干扰。

### 1.5 权限

Web/移动端进入对话界面之前，先使用**账号、密码**登录
（账号、密码可配置，不写死）。

---

## 2. 现状与事实基线

### 2.1 现状架构

```
+--------------------------------------------------------------+
| IDE（Host + 运行时 + 交互 三合一）                            |
|   加载 .qoder/skills/（9 个 skill，xlpa 为路由入口）          |
|   配置 MCP 接入（接入页 access.html 签发凭据）                |
+-------------------------- HTTP /mcp (Bearer) -----------------+
| MCP Server (mcp_server/server.py, FastMCP CompositeApp)      |
|   71 个工具（48 平台 + 23 边缘/建档）                         |
|   鉴权: token_manager + session.py + permissions.json        |
|   写门禁: plan_id + confirm（模型自填参数）                   |
|   平台侧: api_client.py → /api/Auth/LoginByCode（手机号+验证码，|
|           验证码不过期，permissions.json: systemAccount +     |
|           superAccounts）                                    |
|   边缘侧: edge_tools.py + 建档引擎 archiving/                |
|           （计划/执行/补偿/报告，owner_id=SHA-256(接入Token)）|
+--------------------------------------------------------------+
```

### 2.2 关键事实（均已在源码/验证证据中核实）

| 事实 | 出处 |
|---|---|
| 平台登录工具 `login(phoneNum, code)`，后端 `/api/Auth/LoginByCode`，验证码不会过期 | `mcp_server/api_client.py:333-380` |
| 写权限事实源 = `permissions.json`（systemAccount / superAccounts.phones）+ 业务登录结果 | `mcp_server/permissions.template.json` |
| Session 以 `mcp_token` 为键覆盖式写入；Token 以来源地址为主键——共享凭据即越权 | `mcp_server/session.py:73`、`server.py:447` |
| 归属 `owner_id = SHA-256(接入 Token)` 被 6 处状态依赖（快照/模板/报告/日志分区/trace/回读） | `mcp_server/archiving/snapshot_store.py:104` |
| 转换测试 skill 已规划 5 个 MCP 执行类工具（注明"在沙箱中执行"） | `agent_assets/skills/test-validation/SKILL.md:185-193` |
| 转换执行脚本已存在：Python 版 `MapperCore`（protocol_converter.py）、`gen_test_report.py`、C 版 `mapper_core.c` | `agent_assets/skills/protocol-conversion/scripts/` |
| 全量工具 schema 35,022 字符；典型建档子集 18 工具 11,753 字符（约省 2/3） | `validation/manual/v1v3/out/tool-schema-cost.json` |
| 部署为 Windows 单机、uvicorn 单进程、无容器 | `mcp_server/start.bat`、`server.py:3139` |

---

## 3. 硬性约束（全程有效）

1. **不得改变** IDE 接入路径、`/mcp` 端点行为与全部既有工具的入参/返回。
2. **既有 pytest 基线全程保持全绿**；每个变更的通过标准 = 既有测试全绿 + 本变更新增测试。
3. **凭据、密码不得写死在代码里，不得提交进仓库**。
4. spec 按项目 OpenSpec 规范编写，提交前 `openspec validate` 通过。

---

## 4. 功能需求（编号供 spec 引用）

| 编号 | 需求 |
|---|---|
| FR-1 | Web/移动端账号密码登录，账号库可配置（独立文件、哈希存储、提供模板、gitignore） |
| FR-2 | 能力对等：平台数据查询 / 设备建档全流程 / 协议转换全流程，Web 与 IDE 一致 |
| FR-3 | 过程实时可见 + 断线/刷新后回看完整过程（事件流持久化 + 重放） |
| FR-4 | Agent 可在页面向用户提问并等待补充（ask_user 交互环） |
| FR-5 | 写入/下发类操作的服务端确认门禁：一次性授权票据、Fail-Closed、消费即作废、不依赖模型自述 |
| FR-6 | 产物页面查看与下载（不通过 URL 明文携带凭据） |
| FR-7 | 输入支持文字、文档、图片（图片经本地 OCR 转文本后进入会话） |
| FR-8 | 多用户并发 + 同用户多任务并行，用户/任务间实例、工作区、凭据隔离，配额与资源上限明确 |
| FR-9 | IDE 路径、`/mcp` 端点、71 个既有工具行为零变化（回归验证） |

---

## 5. 验收标准

| # | 验收项 | 判据 |
|---|---|---|
| AC-1 | 建档闭环 | 内网环境，真实账号浏览器登录、不碰 IDE，端到端走完"上传已填表格 → 计划卡片 → 确认 → 下发执行 → 报告回读 → 产物下载"；**未确认时不发生任何写入** |
| AC-2 | 协议转换闭环 | 端到端完成一次真实转换："上传协议文档/点表 → 字段映射 → 生成转换配置 → 执行转换测试通过 → 配置/产物在页面下载" |
| AC-3 | IDE 回归 | 验收全程中，IDE 侧既有用法行为不变 |
| AC-4 | 通用 | 交互要求 1~5 逐条可演示 |

---

## 6. 技术方案结论（已确认）

### 6.1 总体架构：四层分离

```
+----------------+   HTTP/SSE   +---------------------+  SDK  +----------------+
| Web 前端       | ------------> | 后端（Host 层）      | ----> | CLI 运行时     |
| 交互 / 决策    | <------------ | 会话·凭据·门禁·池   | <---- | 模型循环·技能  |
+----------------+   事件流      +----------+----------+       +-------+--------+
                                            | HTTP 回环 /mcp (Bearer)  | MCP Client
                                            v                          v
                              +------------------------------------------------+
                              | MCP Server（纯工具层，行为不变 + 新增执行类工具）|
                              +------------------------------------------------+
```

层职责：

| 层 | 负责 | 明确不负责 |
|---|---|---|
| Web 前端 | 输入与附件、流式展示、计划卡片、决策与补充、PC/移动自适应 | 业务判断、凭据存储 |
| 后端（新增，同机独立进程/独立 venv） | 会话生命周期、实例池、身份↔凭据绑定、事件规范化与重放、票据签发与验票、租约、配额、自有存储、本地 OCR | 决定走技能还是调工具 |
| CLI 运行时 | 大模型循环、加载 SKILL.md、读写会话工作区、作为 MCP Client 调工具 | 持有服务端密钥、越出工作区、执行命令 |
| MCP Server | 既有 71 工具（零改动）+ 新增执行类工具、鉴权、plan/confirm、审计 | 持有网页会话状态 |

两条不可妥协的实现纪律（沿用旧方案）：

1. **后端只通过 HTTP 回环 `/mcp` 调工具**——鉴权、审计、plan/confirm 门禁
   全挂在 MCP 请求上下文，禁止直调工具函数、禁止 SDK 进程内 MCP。
2. **门禁配置由后端注入且存放在会话工作区之外**——否则 agent 改写配置
   即可自行放宽权限。

### 6.2 驱动方式选型：Qoder Agent SDK（已定）

**结论：用 Qoder Agent SDK（Python 库驱动 CLI），否决裸 stream-json。**
依据为既有验证资产 `validation/manual/v1v3/` 实测：

| 判据 | 证据 | 结论 |
|---|---|---|
| SDK 能否连自家 `/mcp` 并真实调工具 | `probe_v1.py` 经 SDK `mcp_servers={xlpa: http}` + Bearer，模型真实调起 `mcp__xlpa__list_mcp_tools`（total=71），3 轮 9.8s；错/无凭据 401（`out/mcp-direct.json`、`out/run.json`） | 连通性已排除风险（V1 PASS） |
| 能否拿到含参数的载荷并拦截 | PreToolUse hook 进程内回调注入，拿到 `tool_name` + 结构化 `tool_input`；`deny` 真实阻断（模型复述 "Tool execution blocked"） | 不可绕过拦截点已验证（V3 PASS） |
| stream-json 对照 | 纯 headless `-p` 下需确认动作自动拒绝；hook 无法进程内回调后端验票 | 无法满足 FR-5 硬要求 |
| 事件流丰富度 | SDK 事件含 init / artifacts_update / success（duration_ms / num_turns / result）等子类型 | 足以支撑自有事件契约归一化 |

### 6.3 三大难点正面方案

#### a. 能力对等：转换测试脚本在哪执行、如何受控

把执行能力做成 **MCP Server 的服务端工具**，脚本在服务端受控沙箱执行
（`test-validation/SKILL.md:185-193` 自身规划的路线）：

- 新增 6 个执行类工具：`validate_config_format` / `generate_test_data` /
  `execute_conversion_test` / `get_test_report` / `save_conversion_config` /
  `package_conversion_pack`。
- 沙箱：每任务独立临时目录 + 复制脚本母本（只读）+ 子进程超时 + 输出大小
  上限 + 产物按 owner 分区落盘。
- 受控性来源：**agent 无 shell**（禁 Bash），只能调用参数化工具——脚本内容
  固定、输入为 JSON 配置、无自由命令文本。
- 能力对等方式：**同一套 SKILL.md 改写后同时服务 IDE 与 Web**。
- 一期执行引擎用 **Python 版 MapperCore**（已确认；C 引擎等价性另测）。
- 已确认代价：`list_mcp_tools` 的 total 从 71 增至 71+N（纯增量，
  既有工具入参/返回逐一不变）；资源包升版。

#### b. 登录映射：web 账号密码 ↔ 平台业务登录

```
[Web 账号库]                    [平台业务登录]                [写权限]
webchat_accounts.json  映射     login(phoneNum, code)  决定   permissions.json
username              ---->     /api/Auth/LoginByCode  ---->  (superAccounts +
password_hash(哈希)              业务 Token(缓存)             业务Token)
phone + code(绑定)
```

- **准入 ≠ 授权**（沿用旧方案 D15）：web 账号密码只回答"能不能进门"；
  写权限的唯一判据仍是 `permissions.json` + 业务登录结果，两份名单不合并。
- 账号库形态（已确认）：独立配置文件（gitignore + 模板），每条 =
  `username + password 哈希（PBKDF2/argon2）+ 绑定平台 phone/code + 可选角色标记`。
- 业务凭据获取：登录后由**后端**代为完成 `/api/Auth/LoginByCode` 并缓存业务
  Token，随会话注入——CLI 工作区内不出现任何凭据。
- owner_id：Web 路径 `SHA-256("webchat:" + username)`，稳定不随凭据漂移；
  IDE 路径保持 `SHA-256(接入 Token)` 现状。

#### c. 并发隔离

```
用户A ──登录──> 会话A ──1:1:1──> CLI实例A + 接入凭据A + 工作区A   ┐
用户B ──登录──> 会话B ──1:1:1──> CLI实例B + 接入凭据B + 工作区B   ┘ 互不可见
资源上限: 全局活跃实例 4(默认,可配) / 每用户日轮次 100 / 单轮 max_turns 25
         超限 -> 明确排队或拒绝, 绝不复用他人实例(凭据在进程启动时绑定)
Registry v3: 主键 IP -> Token, 同地址多凭据并存, web 族凭据带 TTL 可撤销
技能目录: 只读母本, 中间产物强制落会话工作区(S0 治理为并发前置条件)
租约: 单写者 45s TTL + 15s 心跳, 后来者只读旁观可接管
```

### 6.4 与旧方案（web-chat-agent-runtime-solution.md）的决策映射

| 旧设计结论 | 本次处置 |
|---|---|
| D1 会话:实例:凭据 = 1:1:1 | **沿用** |
| D2 归属主体与接入凭据解耦 | **沿用**（owner_id 改为 username 派生） |
| D3 Token Registry v2→v3（主键改凭据） | **沿用** |
| D4 mint 端点 + 独立服务凭据 | **重写**：改为账号密码登录后签发（FR-1） |
| D5 自有事件契约 v1 + SSE + seq 重放 | **沿用** |
| D6 单写者租约 + 只读旁观 | **沿用** |
| D7 一期禁 Bash、L3 推后 | **重写**：禁 Bash 保留，L3 转正为本期范围（服务端工具） |
| D8 隔离两层（路径白名单 + 禁命令） | **沿用** |
| D9 产物代理下载 + 一次性 grant | **沿用** |
| D10 数据落点分道 + 本地 OCR | **沿用** |
| D11 双写存储、后端为事实源 | **沿用** |
| D12 工具面按意图收敛子集 | **沿用** |
| D13 技能目录只读治理 | **沿用**，升格为第一个变更（S0） |
| D14 实施基线 | 已完成（`3ff652b`） |
| D15 两份手机号名单不混用 | **沿用**（准入名单改为账号库） |

> 旧 OpenSpec 变更 `add-web-chat-agent-runtime` 已由需求方从工作区删除
> （内容仍在 git 历史可查），不再恢复；新方案按多 change 逐个走流程。

---

## 7. 变更拆分方案（已确认：拆成多个 change 逐个走流程）

### 7.1 依赖图与顺序

```
C1 技能工作区治理 ──> C2 账号准入 ──> C3 会话运行时 ──┬──> C7 端到端验收
                  └──────────────> C6 转换执行工具 ──┤
                        C4 写入门禁(依赖C3) ─────────┤
                        C5 产物与上传(依赖C3) ───────┘
```

### 7.2 各变更四要素

每个变更一个独立 OpenSpec change（一个 capability spec），spec 内以固定
小节写四要素；**每个变更实施前单独提交需求方确认，未确认不得写代码。**

#### C1 `skill-workspace-governance` 技能工作区治理

| 要素 | 内容 |
|---|---|
| 前置条件 | 核对 `output/` 12 处跨技能引用清单；Word 锁文件已释放 |
| 要做的事 | 技能目录完全只读化；最终产物迁出到会话工作区约定；残留清理；资源包升版；`git rm --cached` 停止跟踪凭据文件 |
| 通过标准 | pytest 全绿；完整跑一轮转换+建档后技能目录零新增文件；IDE 人工回归清单通过 |
| 顺序与依赖 | 最先执行；一切并发能力的前提 |

#### C2 `web-account-auth` 账号密码准入

| 要素 | 内容 |
|---|---|
| 前置条件 | 账号库形态/哈希算法确认（已确认）；V10 验证：PAT 注入不出现在子进程命令行 |
| 要做的事 | 账号库 + 哈希 + 模板；登录/登出/会话票据；限流；与平台业务凭据绑定（难点 b 落地） |
| 通过标准 | 新增 pytest：哈希校验、错误密码拒绝、票据 TTL/过期；两份名单不混用断言；pytest 全绿 |
| 顺序与依赖 | 依赖 C1 |

#### C3 `agent-runtime-session` 会话与实例运行时

| 要素 | 内容 |
|---|---|
| 前置条件 | V1 已 PASS（复用）；需补验：V1b 会话恢复粒度、V2 无头技能路由、实例冷启动成本 |
| 要做的事 | SDK adapter（SDK 类型只出现在此层）；1:1:1 绑定；工作区布局；Registry v3 + mint；事件契约 v1 + SSE + seq 重放；租约；实例池与配额（难点 c 落地） |
| 通过标准 | 并发 2 会话隔离测试（工作区/凭据/事件流互不串）；断线重连重放补齐；超限明确拒绝；pytest 全绿 |
| 顺序与依赖 | 依赖 C2 |

#### C4 `write-gate-isolation` 写入门禁与隔离

| 要素 | 内容 |
|---|---|
| 前置条件 | V3 已 PASS（复用）；需补验：hook 对写入工具 `plan_id`/`confirm` 参数可见性、hook 验票回环后端通道（V7） |
| 要做的事 | PreToolUse 写入工具验票（一次性 grant、Fail-Closed、消费即作废）；门禁配置在工作区外；路径白名单；拦截事件入流 |
| 通过标准 | 未确认时写入被 deny 的自动化测试；授权一次性消费；agent 无法改写门禁配置；pytest 全绿 |
| 顺序与依赖 | 联调依赖 C3 |

#### C5 `web-artifact-delivery` 产物与上传

| 要素 | 内容 |
|---|---|
| 前置条件 | 本地 OCR 选型与质量基线验证（V8'）；上传大小上限决策 |
| 要做的事 | 文字/文档/图片三通道输入落点分道；本地 OCR provider；产物代理下载 + 一次性 grant；保留期接入 cleanup.py |
| 通过标准 | 上传→产物→下载端到端 pytest；断言凭据不进 URL；pytest 全绿 |
| 顺序与依赖 | 依赖 C3 |

#### C6 `conversion-execution-tools` 转换执行工具

| 要素 | 内容 |
|---|---|
| 前置条件 | C1 完成；工具面 71→71+N 已确认；需验证：Python MapperCore 对 C 引擎的等价性 |
| 要做的事 | MCP Server 新增 6 个执行类工具 + 沙箱（超时/目录/资源上限）；SKILL.md 改写；资源包升版（难点 a 落地） |
| 通过标准 | 新增 pytest：沙箱执行、超时、路径逃逸拒绝、报告结构；AC-2 闭环演练证据；IDE 回归 = 既有工具入参/返回逐一比对一致；pytest 全绿 |
| 顺序与依赖 | 依赖 C1；Web 闭环需 C3+C4+C5 齐备 |

#### C7 `e2e-acceptance-hardening` 端到端验收

| 要素 | 内容 |
|---|---|
| 前置条件 | C1~C6 全部完成 |
| 要做的事 | 建档闭环演练（AC-1）；转换闭环演练（AC-2）；交互要求 1~5 逐条演示（AC-4）；IDE 回归清单（AC-3）；汇报素材归集 |
| 通过标准 | 四条验收标准逐条留证（测试输出/截图存档至 `validation/`） |
| 顺序与依赖 | 最后执行 |

### 7.3 通用规则（每个变更相同）

1. spec 按 OpenSpec 规范编写，`openspec validate` 通过后才提交。
2. 实施前将 spec 提交需求方确认，确认后逐项实施。
3. 每个变更完成：跑回归 → 记录通过证据（测试输出/截图）→ 存档为汇报素材。
4. 写代码时调用 `/karpathy-guidelines` 技能。
5. **CN-SDK 部署契约（C5–C7 横切约束）**：自 `cn-sdk-migration`（2026-10-29 归档）起
   生产 webchat 运行时由国内版 SDK（`qodercn-agent-sdk` / `qodercn_agent_sdk`）驱动。
   C5–C7 的运行、验收与部署环节 MUST 满足：① PAT 经 `QODERCN_PERSONAL_ACCESS_TOKEN`
   注入（**BREAKING**：全球版用 `QODER_PERSONAL_ACCESS_TOKEN`，名称错误会导致 initialize
   超时）；② MCP 鉴权用本地 token registry 的 ide/user 级 token（`.env` 的 admin
   `MCP_AUTH_TOKEN` 被运行实例 401 拒绝）；③ 国内版 SDK 自带 `qoderclicn`，无需 PATH
   上的 `qodercli`；④ 回滚：恢复 requirements pin 为 `qoder-agent-sdk==1.0.16` 且 PAT
   环境名改回 `QODER_`。完整交接清单见 `validation/cn-sdk-migration/evidence-index.md` §6。

---

## 8. 验证资产复用清单

### 8.1 已 PASS，直接复用

| ID | 内容 | 证据位置 |
|---|---|---|
| V1 | SDK 驱动 CLI 连自家 `/mcp` 并真实调只读工具（3 轮 9.8s） | `validation/manual/v1v3/out/run.json`、`out/mcp-direct.json` |
| V3 | PreToolUse hook 拿到 tool_name + 结构化参数；deny 真实阻断 | `validation/manual/v1v3/out/hooks.jsonl`、`out/run.json` |
| V4 | 全量 schema 35,022 字符；子集收敛省 2/3 | `validation/manual/v1v3/out/tool-schema-cost.json` |
| V9 | `edge_sessions` 仅内存 + 24h TTL；file_id 快照 30 天可重建 | 旧方案文档第 9 节 |

### 8.2 待补验（列入对应变更的前置条件）

| ID | 内容 | 归属变更 |
|---|---|---|
| V1b | 会话销毁后恢复粒度（上下文与产物是否齐） | C3 |
| V2 | `/xlpa` 路由在无头/SDK 会话中是否展开 | C3 |
| V7 | hook 验票回环后端通道（进程内回调可行性已见曙光，需真实往返验证） | C4 |
| V8' | 本地 OCR 质量基线（三张样图 + 一份电子表格对照） | C5 |
| V10 | PAT 注入不出现在子进程命令行 | C2 |
| V11 | 免费档位账号并发 > 1 与连续写入下的限流表现 | C3/C7 |

---

## 9. 过程纪律与汇报

1. **禁止臆造**：任何未经验证的结论不得写入实现；需要需求方补充或配合的，
   随时沟通。
2. **每个变更完成**：跑回归 → 记录通过证据（测试输出/截图）→
   存档为汇报素材（`validation/` 目录）。
3. **全部变更完成后**：更新 `.ua` 下的知识图谱。
4. **需求完成后做一次汇报**（调用 html-ppt 技能），保留全程素材。
   汇报大纲：**原始需求 → 需求文档 → 生成 spec → 实施 spec → 回归测试 →
   更新 .ua 知识图谱**。
5. 写代码时调用 `/karpathy-guidelines` 技能。

---

## 10. 决策记录

| ID | 决策 | 时间 |
|---|---|---|
| DR-01 | 复用旧方案验证结果（V1/V3/V4/V9），新方案按最优方式编写（登录与 L3 重写，其余 D 结论沿用） | 2026-10-27 |
| DR-02 | 登录映射形态：账号库条目 = username + password 哈希 + 绑定平台 phone/code；后端代为业务登录并缓存业务 Token | 2026-10-27 |
| DR-03 | 工具面 71 → 71+N（纯新增执行类工具，既有工具零改动）可接受 | 2026-10-27 |
| DR-04 | 一期转换执行引擎用 Python 版 MapperCore | 2026-10-27 |
| DR-05 | 拆分为 7 个独立 change（C1~C7）逐个走 OpenSpec 流程，每个变更实施前单独确认 | 2026-10-27 |
| DR-06 | 旧变更 `add-web-chat-agent-runtime` 不恢复；其文档保留为设计参考底稿 | 2026-10-27 |
