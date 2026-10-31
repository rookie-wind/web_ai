## Context

见 proposal.md（Why）。设计输入均为已核实事实：

- `TokenManager`（server.py:431-620）：`ip_tokens: dict[ip, entry]` 主键为 IP，
  `is_valid` 沿 token→ip→记录→token 相等链校验；备份迁移范式
  （`_backup_registry("v1"/"corrupt")` + schema_version）成熟可复用；
- `AuthMiddleware`（server.py:2623-2684）：验 token → `mcp_token_var.set(token)`
  → `touch_ip_last_seen(ip)`；v3 后验证链不变，仅 touch 语义改按 Token；
- SDK 实测（introspect qoder_agent_sdk）：
  - `include_partial_messages: bool`（流式增量）；`on_elicitation` 回调
    （MCP elicitation 控制请求，ask_user 原生通道）；
  - `resume`/`session_id` + `SessionStore` 协议（append/load/list/delete，
    "Store-backed continue requires list_sessions"）——V1b 载体；
  - `Transport` 抽象（connect/write/read/close/end_input）——中断与回收载体；
  - `skills: list[str] | "all"`，注释明确 **"context filter, not a security
    boundary"**；`setting_sources: [user|project|local]` 可控；
  - `max_turns`、`hooks`（14 事件）、`env: dict[str, str|None]`。
- 事件形态：query 产出 UserMessage/AssistantMessage（content: TextBlock/
  ToolUseBlock/ToolResultBlock/ThinkingBlock）/SystemMessage/ResultMessage/
  StreamEvent；v1v3 实测 3 轮 9.8s。

## Goals / Non-Goals

**Goals:**

- Registry v3 + mint（mcp_server 侧，最小改动面）；
- webchat 会话运行时 MVP：创建会话→发消息→事件流→断线重放→结束回收，
  1:1:1 隔离与配额可自动化验证；
- V1b/V2/冷启动三项补验并留证。

**Non-Goals:**

- 不做写入门禁验票/路径白名单 Hook（C4）；
- 不做产物代理下载/上传通道/OCR（C5）；
- 不做前端页面与公网部署（C7）；
- 不实现"空闲实例回收"（V1b 结论若支持再做，MVP 按会话结束回收）；
- 不做事件持久化的跨进程存储（单进程内 dict + JSONL 落盘即可，量级见
  Risks）。

## Decisions

### D1 Registry v3 结构与迁移

```
v3: {
  "schema_version": 3,
  "entries": {
    "<token>": {
      "ip": "...", "family": "ide|webchat", "accessLevel": "user",
      "owner_ref": "<sha256 或 null(ide)>", "expires_at": null|int,
      "createdAt": int, "lastSeenAt": int,
      "revoked": false, "legacyMigrated": bool, "source": "auto|admin|mint"
    }
  }
}
```

- 内存态 `tokens: dict[token, entry]` + `ip_ide_token: dict[ip, token]`
  （IDE 族复用索引，仅指向该 IP 最新的未撤销 IDE Token）；
- `is_valid(token)`：admin 精确匹配 → entries 直查（O(1)，不再沿 IP 绕）；
  webchat 族校验 `expires_at`；`touch` 按 token 更新 lastSeenAt；
- `get_or_create_token(ip)`：IDE 族语义不变（查 ip_ide_token，命中未撤销
  即复用）；与 webchat 族互不影响；
- 迁移：schema_version != 3 → 备份（tag=v2）→ 逐条转 v3（family=ide，
  owner_ref=null，expires_at=null）→ 保存。损坏回退空表（既有范式）。
- 归档注记：主规格 requirement 标题"v1 到 v2 迁移"在归档时由本 delta
  内容替换，标题不改（OpenSpec MODIFIED 匹配要求）；语义以内容为准。

### D2 mint 端点形态（CompositeApp 新增路由）

- `POST /api/mcp-token/mint`，请求头 `X-Mint-Secret`，JSON 体
  `{username, ttl_seconds?}`；
- 校验顺序：secret（401）→ 来源白名单（403，`WEBCHAT_ALLOWED_IPS`
  逗号分隔，默认 `127.0.0.1,::1`）→ 限流（429，内存滑窗，默认
  60 次/分钟）→ 签发；
- 签发：`metam_pat_` + 32 hex，family=webchat，TTL 取
  `min(ttl_seconds 或默认 7200, WEBCHAT_TOKEN_TTL_CAP=86400)`，
  owner_ref=SHA-256("webchat:"+规范化 username)；规范化规则与账号库
  查询一致：strip 首尾空白、大小写敏感；审计写 operation_log_store
  既有通道（新事件类型 mint）；
- 凭据撤销：`POST /api/mcp-token/revoke`（同双条件，体含 token）——
  webchat 会话结束时调用；**仅对 family=webchat 生效，IDE 族撤销
  请求 403**（防 mint 通道破坏 IDE 现网凭据）；revoked 后
  is_valid=False。

### D3 SDK adapter 边界与实例生命周期

```
webchat/webchat/sdk_runtime/
├── __init__.py      # 对外只暴露 AgentHandle 与纯数据事件类型
├── adapter.py       # qoder_agent_sdk 唯一 import 点
└── (事件转换在 adapter 内完成，输出自有契约)
```

- 实例启动参数：`cwd=会话工作区`、`mcp_servers={xlpa: http://127.0.0.1:
  8765/mcp, headers: Bearer=会话凭据}`、`strict_mcp_config=True`、
  `allowed_mcp_server_names=["xlpa"]`、`tools=[]`（禁内置 Bash 由
  permission_mode+disallowed_tools 双保险，C4 再加 Hook）、
  `setting_sources=[]`（不加载宿主配置）、`include_partial_messages=True`、
  `max_turns=配额`、`skills=["xlpa"]`（上下文收敛，非安全边界——注释
  原文如此，安全靠 C4）；
- **技能加载来源（V2 探针必验项）**：`setting_sources=[]` 与
  `skills=["xlpa"]` 的组合下技能母本从何处加载尚未实测（候选：用户级
  技能目录 `~/.qoder/skills/`、CLI 内置会话目录）；V2 探针必须同时验证
  （a）xlpa 入口路由可用，（b）能路由到 xlpa 之外的子技能
  （device-archiving、protocol-conversion 至少各一）——仅验 xlpa 入口
  通过 ≠ 能力对等；若 `setting_sources=[]` 导致技能不可加载，回退为
  保留用户级 setting source（决策留证）；
- 多轮对话：首轮 `q.query()` 取得 session_id 存 handle；后续轮
  `resume=session_id`（V1b 实测后定稿；失败回退见 D6）；
- 中断/终止：handle 持 transport 引用，`close()` 终止子进程；
- **PAT 注入**：沿用 V10 已验范式（`QODER_PERSONAL_ACCESS_TOKEN` 环境变量
  + `access_token_from_env()`），env 只在实例启动时传入。

### D4 事件契约 v1 与存储

- 事件结构：`{v:1, seq, session_id, ts, type, payload}`；
  type ∈ session_started|text_delta|tool_call|tool_result|ask_user|
  turn_done|session_closed|error|unknown；
  **ask_user** 由 adapter 桥接 SDK `on_elicitation` 回调产生（交互
  要求 2 的原生通道，payload 含问题内容与选项），前端渲染为提问卡片；
- 归一化规则（adapter 内）：AssistantMessage.content 逐 block 分派——
  TextBlock→text_delta、ToolUseBlock→tool_call、ToolResultBlock→
  tool_result；ResultMessage→turn_done；SystemMessage 未知 subtype→
  unknown；StreamEvent（partial）→text_delta 增量；
  **去重规则**：`include_partial_messages=True` 时，若某段文本已产出过
  partial 增量事件，则该文本的最终完整 TextBlock 不再产出 text_delta
  （adapter 按 block 追踪 partial 覆盖范围；未收到 partial 的 TextBlock
  照常产出，兼做降级兑底）；
- 存储：每会话一个 JSONL 文件（`webchat_data/events/<session_id>.jsonl`，
  追加写）+ 内存索引（seq→文件偏移），重放读文件；写入在事件产生点
  同步完成（先落盘再广播，保证重放一致）；
- SSE：`GET /api/sessions/{id}/events`，响应头 text/event-stream；
  `Last-Event-ID` 解析为 seq，从 seq+1 重放再接实时队列；
  心跳注释行 :ping 每 15s（兼作连接保活）。

### D5 租约与实例池

- 租约：会话对象持 `lease: {holder_id, expires_at}`；写操作（发消息）
  校验租约；`POST /api/sessions/{id}/lease`（获取/续期，45s TTL）、
  前端心跳即续期调用；旁观=只订阅 SSE 不持租约；接管=显式
  `lease?takeover=true`（先中断执行轮）；
- 实例池：全局信号量（asyncio.Semaphore，上限 WEBCHAT_MAX_INSTANCES=4）；
  会话创建时获取，结束/失败时释放；每用户活跃会话计数
  （WEBCHAT_MAX_SESSIONS_PER_USER=**2**，满足需求“同一用户多任务
  并行”；受全局实例上限 4 约束）超限 409/明确错误体；
- 队列策略：MVP 不排队（明确拒绝 + Retry-After），排队语义留 C7 打磨。

### D8 owner_ref 接入操作日志审计分区

现状：操作日志分区键 = sha256(接入 Token)（快照/模板/报告等 6 处状态
同源）——webchat 凭据每会话一换，审计会被碎到每会话一个分区。
处置：

- **webchat 族**：AuthMiddleware 鉴权命中 v3 entry 后，将 entry 的
  `owner_ref` 注入请求上下文（新 contextvar `owner_ref_var`），操作
  日志分区键优先取 owner_ref（null 时回退 sha256(token)）——同一用户
  多会话的审计归并到同一分区；
- **IDE 族**：owner_ref 为 null，分区键保持 sha256(token) 现状，
  零行为变化；
- 实现落点：AuthMiddleware（读 entry 传值）+ operation_log_store
  调用侧分区键选择；snapshot_store 等其余 5 处状态在 C4/C5 涉及时
  逐一评估是否切 owner_ref（避免本变更扩散面过大），此项记入
  tasks 1.4 与风险清单。

### D6 V1b/V2/冷启动补验与回退

- V2 验证方法（含技能加载来源，见 D3）：adapter 启动 xlpa 技能会话，
  发"列出你能做什么"类提示，断言（a）xlpa 入口路由可用，（b）能路由到
  xlpa 之外的子技能（device-archiving、protocol-conversion 至少各一）；
  同时确认技能母本加载来源在 `setting_sources=[]` 下可用；
- V1b 验证方法：首轮完成后记录 session_id → 销毁实例 → resume 重启 →
  追问"刚才说了什么"断言上下文保持；同时验证 SessionStore 镜像非必需
  （MVP 不接 store，resume 基于 CLI 本地会话目录即可）；
- 冷启动：采样 5 次"实例启动→首事件"耗时；
- 回退预案（写入实施记录）：V2 失败→系统提示词注入 xlpa 路由表（改
  adapter 一个参数）；V1b 失败→每轮全量重传（成本↑功能不损）；
  两者均不回退架构。

### D7 会话 API 面（FastAPI 新增路由，全部经 C2 票据鉴权）

```
POST   /api/sessions                     创建会话（mint+实例+工作区）
GET    /api/sessions                     我的会话列表
GET    /api/sessions/{id}/events         SSE 事件流（Last-Event-ID 重放）
POST   /api/sessions/{id}/messages       发送消息（需租约）
POST   /api/sessions/{id}/lease          获取/续期/接管租约
POST   /api/sessions/{id}/close          结束会话（撤销凭据+终止实例）
GET    /api/sessions/{id}/history        历史事件分页（回看）
```

工作区根：`webchat_data/workspaces/<session_id>/`（含 xlpa-tmp/、
xlpa-output/）。凭据/票据校验中间件统一在路由层。

## Risks / Trade-offs

- [Registry v3 迁移破坏 IDE 现网] → 迁移前自动备份 + 迁移后 IDE Token
  兼容断言纳入主 pytest；测试用例覆盖 v1/v2/损坏三态。
- [SDK resume 行为与文档不符（V1b 失败）] → D6 回退预案（每轮全量重传），
  功能无损、成本上升，记录实测数据供 C7 评估。
- [Windows 单机 4 实例的资源压力（node 进程 + 模型流量）] → 配额默认值
  保守（4/1/25）+ V11 免费档限流表现实测（C7 联调期完成）。
- [事件 JSONL 无限增长] → 会话结束即封存不再增长；保留期清理归 C5 的
  cleanup.py 分类映射（本变更不动 cleanup）。
- [sse-response-buffering] → 本期仅内网直连（uvicorn 原生 SSE 无缓冲）；
  公网反代配置归 C7。

## Migration Plan

1. mcp_server：Registry v3（结构+迁移+测试）→ mint/revoke 端点（+测试）
   → 主 pytest 全绿（含 IDE 兼容断言）；
2. webchat：sdk_runtime adapter（含 V1b/V2/冷启动探针脚本）→ 事件契约与
   存储 → 会话 API + 租约 + 实例池 → webchat pytest 全绿；
3. 端到端演练取证（登录→建会话→消息→事件流→断线重连→结束回收）+ IDE
   回归取证；
4. 证据归档 `validation/c3-agent-runtime-session/`。

回滚：分两段提交（mcp_server 段 / webchat 段），任一段可独立 revert；
registry v3 迁移的回滚 = 恢复备份文件（备份保留在原目录）。

## Open Questions

（无——D6 两项待验项均已带回退预案，不阻塞规划确认；实例默认配额
4/1/25 为保守起步值，需求方可随时在实施前调整。）
