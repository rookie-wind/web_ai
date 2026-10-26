## Context

动机见 `proposal.md - Why`。当前相关事实（均来自代码核对）：

- 写操作分散在两类实现：协议管理层写工具是 `server.py` 中 `@mcp.tool()` 的异步函数，
  由 `TOOL_DEFINITIONS[].type == "write"` 标注（并有一份 `WRITE_TOOLS` 子集）；边缘写工具
  是 `edge_tools.py` 中 `type == "edge_write"` 的函数，且已统一经 `_tracked_action`
  装饰，产出了 `operation_id / started_at / finished_at / state / request_sent` 等动作记录。
- 归属与上下文已就绪：`AuthMiddleware` 注入 `mcp_token_var`；`derive_owner_id(mcp_token)`
  给出不可逆归属；`login` 通过 `session_registry.create()` 建立按 `mcp_token` 键的 Session。
- 存储范式可复用：`TaskReportStore` 提供原子写、TTL、`list_by_owner`、目录可由环境变量
  （`PCA_TASK_REPORTS_DIR`）重定向；`sanitize_report` 统一脱敏。
- 约束：单进程 asyncio；不引入 `logging` 框架；改造必须附加式、不破坏既有工具与页面。

## Goals / Non-Goals

**Goals:**
- 单一事实源判定"写操作"，采集点集中，尽量不改每个工具函数体。
- 内存 + 落盘双存，按身份隔离、按 trace 会话窗聚合，跨重启在 TTL 内可回看。
- 内联 `operation_log` 与 `/api/logs` 两条回读通道，全程 fail-open 且脱敏。

**Non-Goals:**
- 不做只读/探测工具的调用审计。
- 不改 `AuthMiddleware` 对合法请求的鉴权语义，不新增鉴权模型。
- 不替代边缘建档已有的 `get_device_archive_task_report`（详细阶段报告保持原样）。
- 不做集中式日志采集/告警平台对接。

## Decisions

### D1 写操作判定：以 `TOOL_DEFINITIONS[].type ∈ {"write","edge_write"}` ∪ `{"login"}` 为白名单
- 单一事实源即工具清单元数据，避免再维护第二份清单导致漂移。
- 备选：复用 `WRITE_TOOLS` 常量。否决原因——它不含 `edge_write` 与 `login`，覆盖不全。

### D2 采集点：注册后统一包裹 handler，不逐个改函数体
- 在 `server.py` 所有工具注册完成后，对命中 D1 白名单的工具 handler 用 `functools.wraps`
  包一层：计时 → 调原实现 → 记录日志 → 附加内联字段。异步/同步两种签名都适配。
- 边缘写工具已在 `_tracked_action` 内产出结果态：新增一个"落新存储 + 内联"的挂钩，读取其
  既有 `action` 记录，不重复实现计时/状态判定。
- 备选：给每个 `@mcp.tool()` 换自定义装饰器。否决——改动面大、易漏工具、风险高于收益。

### D3 trace 会话窗：`OperationLogStore` 维护 `current_trace[owner_id]`
- `login` 成功时生成 `trace_id = "trc_<UTC时间>_<hex>"`，写入 `Session.trace_id` 并更新
  `current_trace[owner_id]`；`edge_get_token` 独立登录同样刷新该映射，保证边缘写操作也归窗。
- 每条写日志按当前 `owner_id` 的 `current_trace` 打标；重新登录即换窗，旧窗仍在同身份下可查。
- 客户端全程无需传 `trace_id`（满足"自动传/不需手动传"）。
- 备选：以 `task_id` 为窗。否决——`task_id` 仅边缘会话有，协议管理层写操作无 `task_id`。

### D4 存储：按身份分区的内存环形缓冲 + `<owner_id>.jsonl` 追加落盘
- 内存：每 `owner_id` 保留最近 N 条（默认上限，实现期定为常量），供即时回读。
- 落盘：每身份一个 append-only `.jsonl`（追加行），复用 `_atomic_write_json` 的权限与
  Windows 重试经验；TTL 默认短于报告（如 7 天），过期行在读取时按时间戳惰性剔除。
- 目录：`~/.pca/operation_logs/`，可由 `PCA_OPERATION_LOGS_DIR` 覆盖（测试用 autouse fixture 隔离）。
- 备选：一操作一文件（照搬 `TaskReportStore`）。否决——写操作频次高，文件数会爆炸。

### D5 内联字段：`setdefault("operation_log", {...})` 纯附加
- 仅当返回为 dict 且无同名键时写入，含 `entry_id / trace_id / status / code / duration_ms`；
  不改任何既有键，非 dict 返回则跳过内联，保证契约向后兼容。

### D6 回读接口：`CompositeApp` 新增 `/api/logs`
- 解析请求携带的接入 Token（`Authorization` 头或 query）→ `derive_owner_id` →
  返回该身份 `current_trace` 内日志（脱敏）与 `next_cursor`；放在 MCP 兜底分支之前，
  不影响 `/access`、`/api/access-info` 等既有路由。
- 接入页 `access.html` 用其已持有的 Token（`/api/access-info` 返回）轮询渲染日志展示区。

### D7 安全与 fail-open
- 所有入参/结果摘要先过 `sanitize_report` 并截断；绝不落原始 Token/口令/验证码。
- 采集、落盘、内联、接口任一步异常一律吞为 `[WARNING]` 打印，业务写操作结果不受影响。

## Risks / Trade-offs

- [包裹 handler 可能干扰 FastMCP 对工具签名的解析] → 用 `functools.wraps` 保留原 `__name__`
  与签名，且只替换执行 handler、不改注册时的 schema；实现期以一次真实 `tools/call` 冒烟验证。
- [异步/同步工具混用导致计时或异常处理不一致] → wrapper 内区分 coroutine 与同步返回，
  统一在"拿到最终结果后"记录。
- [写操作高频导致磁盘/内存增长] → 环形缓冲上限 + 摘要截断 + 单身份文件大小与 TTL 三重约束。
- [按 query 传 Token 可能进入浏览器历史] → 优先用 `Authorization` 头；query 仅作兜底并在页面
  文档中沿用既有"勿将 Token 写入日志/历史"的安全提示口径。
- [trace 归属映射为进程内状态，重启后 `current_trace` 丢失] → 落盘行仍带历史 `trace_id`，
  重启后回读以"该身份最近落盘 trace"或按 `trace_id` 显式过滤兜底；不阻断"本次新会话"记录。

## Migration Plan

1. 先落地 `OperationLogStore` + 脱敏 + `PCA_OPERATION_LOGS_DIR`，独立单测覆盖按身份隔离与 TTL。
2. 接入 wrapper 与 `login`/`edge_get_token` 的 `trace_id` 绑定，灰度验证只记录 D1 白名单工具。
3. 加 `/api/logs` 路由，验证不影响既有路由与鉴权。
4. 最后改 `access.html` 增加展示区并接 `/api/logs`。
5. 回滚：任一阶段出问题可单独移除 wrapper 调用 / 路由分支 / 页面区块；数据目录缺失时读接口返回空，
   不影响主流程（无 schema 迁移，纯附加）。
