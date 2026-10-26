## Why

服务端目前的可观测性局限于两点：控制台只在启动阶段 `print` 一次性信息，运行时不记录
任何写操作；面向客户端的留痕只有边缘建档流的 `get_device_archive_task_report`，覆盖不
到协议管理层写操作与登录。用户执行建档/下发/召测/登录等有副作用的操作后，无法直观看
到"我这次到底做了什么、成没成"。需要一套统一的写操作留痕机制，并让客户端在自己的接入
页直观回看本次操作的日志。

## What Changes

- 新增**写操作留痕**：对协议管理层写工具（`WRITE_TOOLS`）、边缘写工具
  （`edge_write` 类型：建档/挂载/参数保存/下发/召测/删除/补偿/一键执行）与 `login`
  记录一条操作日志（操作名、入参脱敏摘要、结果状态、错误码、耗时、来源、时间）。
  只读/探测类工具不记录。
- 新增 **trace 会话窗**：以 `login` 建立的 Session 为锚点，服务端自动分配并绑定
  `trace_id`，把同一登录会话内的写操作归为"本次操作"；客户端无需手动传 `trace_id`。
- 新增**操作日志存储** `OperationLogStore`：内存环形缓冲 + 落盘（按 `owner_id` 分区，
  沿用 `TaskReportStore` 的原子写 + TTL 范式），跨进程重启可回看。
- 新增**结果内联字段**：写工具返回值追加一个 `operation_log` 子字段（通道②），让
  Agent 当次调用即时拿到本次操作痕迹。该字段为**附加式**，不改动既有返回键。
- 新增**接入页日志视图**：`/api/logs` 端点 + 一键接入页展示区，客户端凭页面已有的
  接入 Token 解析出 `owner_id` 与当前 `trace_id`，只看到自己的本次操作日志。
- **非破坏约束**：日志采集与落盘失败不得阻断业务写操作（fail-open）；不采集/存储原始
  Token 与口令（复用 `sanitize_report`）；不改变 `AuthMiddleware` 对合法请求的行为。

## Capabilities

### New Capabilities
- `write-operation-trace-log`: 写操作的记录范围、数据模型、trace 会话窗归属、内存+落盘
  存储、结果内联字段与 `/api/logs` 回读的对外行为契约（含按身份隔离与脱敏）。

### Modified Capabilities
- `showcase-access-experience`: 一键接入页新增"本次操作日志"展示区的需求（凭页面
  Token 定向回显当前客户端自己本次会话的写操作日志）。

## Impact

- 代码：
  - `mcp_server/server.py`：写工具统一采集入口（注册后包裹 handler 或共享记录函数）、
    `login` 生成/绑定 `trace_id`、`CompositeApp` 路由新增 `/api/logs`、`TOOL_DEFINITIONS`
    或 `WRITE_TOOLS` 旁路不改语义。
  - `mcp_server/edge_tools.py`：`_tracked_action` 已产出的动作结果对接到新存储与内联字段。
  - 新增 `mcp_server/operation_log_store.py`（或置于 `archiving/` 同层，实现期定）。
  - `mcp_server/session.py`：`Session` 增加 `trace_id` 字段。
  - `mcp_server/static/access.html`：新增日志展示区，调用 `/api/logs`。
- 复用：`archiving/snapshot_store.derive_owner_id`、`session.mcp_token_var`、
  `archiving/log_sanitizer.sanitize_report`、`archiving/task_report_store` 存储范式。
- 依赖：无新增第三方库（不引入 `logging` 框架，沿用现有标准库能力）。
- 环境：新增可选环境变量 `PCA_OPERATION_LOGS_DIR` 用于测试与部署目录隔离。
- 数据：`~/.pca/operation_logs/` 下按身份落盘，带 TTL 与目录上限。
- 兼容性：全部为附加式改动，不删除/重命名既有工具与返回字段，现有功能不受影响。
