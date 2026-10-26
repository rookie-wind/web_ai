## 1. 存储与数据模型（OperationLogStore�?

- [x] 1.1 新建 `mcp_server/operation_log_store.py`，实�?`OperationLogEntry`（字段：entry_id、owner_id、trace_id、tool、source、access_level、status、code、args_summary、result_summary、started_at、duration_ms）与 `to_dict/from_dict`，并通过 `openspec` �?specs「操作日志内容必须脱敏且不含机密」的字段核对
- [x] 1.2 实现 `OperationLogStore`：按 `owner_id` 的内存环形缓冲（上限常量�? `~/.pca/operation_logs/<owner_id>.jsonl` 追加落盘，目录支�?`PCA_OPERATION_LOGS_DIR` 覆盖，落盘复�?`TaskReportStore._atomic_write_json` 的权限与 Windows 占用重试写法（验证：单测写入后从磁盘读回条数一致）
- [x] 1.3 实现 `current_trace[owner_id]` 映射、`set_current_trace`、`append`、`list_current(owner_id, cursor)`、TTL 惰性清理（默认 7 天）（验证：单测覆盖过期行被剔除、游标增量返回）
- [x] 1.4 接入 `sanitize_report` �?`args_summary`/`result_summary` 脱敏并截断（验证：单测断言含口�?Token 入参落库后无明文�?
- [x] 1.5 新增测试文件 `mcp_server/tests/test_operation_log_store.py`，用 autouse fixture 指向 tmp 目录，覆盖按身份隔离、越权读取返回空、重启后按文件回看（验证：`pytest mcp_server/tests/test_operation_log_store.py` 全绿�?

## 2. trace 会话窗绑�?

- [x] 2.1 `mcp_server/session.py` �?`Session` 增加 `trace_id: str = ""` 字段（验证：dataclass 可实例化且默认空�?
- [x] 2.2 `server.py` �?`login` 成功与失败分支均生成 `trace_id="trc_<UTC>_<hex>"`，写�?Session 并调�?`store.set_current_trace(owner_id, trace_id)`（验证：登录�?`current_trace` 命中�?owner�?
- [x] 2.3 `edge_tools.py` �?`edge_get_token` 独立登录同样刷新 `current_trace[owner_id]`（验证：边缘独立会话的写操作能取�?trace_id�?

## 3. 采集点（wrapper 与边缘挂钩）

- [x] 3.1 �?`server.py` 实现写操作白名单判定：`TOOL_DEFINITIONS[].type �?{"write","edge_write"}` �?`{"login"}`，暴露为单一函数（验证：断言覆盖 `add_classify`、`edge_set_device_param`、`login` 为真，`get_classify_list` 为假�?
- [x] 3.2 实现注册后统一包裹 handler �?`logged_tool` wrap（`functools.wraps` 保留原签名，区分 async/sync，计时后调用 `OperationLogStore.append`），仅对白名单工具生效（验证：真实调用一个协议层写工具后日志条数 +1�?
- [x] 3.3 �?`login` 接入采集（其返回结构特殊，单独在函数尾部�?wrap 记录成功/失败态）（验证：登录成功与失败各产生一条日志）
- [x] 3.4 �?`edge_tools.py` �?`_tracked_action` 结果态产出处新增挂钩，把既有 `action`（state/耗时/operation_id）落�?`OperationLogStore` 并打当前 trace_id（验证：一次建�?下发后新存储出现对应记录�?
- [x] 3.5 fail-open：wrap、挂钩、落盘任一步异常仅 `print("[WARNING] ...")`，不改变业务返回（验证：单测注入落盘异常，写操作返回值与无日志时一致）

## 4. 结果内联字段（通道②）

- [x] 4.1 在采集完成后�?dict 结果执行 `result.setdefault("operation_log", {entry_id,trace_id,status,code,duration_ms})`，非 dict 或键已存在则跳过（验证：断言既有返回键不变，新增键存在）
- [x] 4.2 冒烟验证：调用一个边缘写工具，确认返回体新增 `operation_log` 且原有字段（�?`stage_state`、`ok`）取值不受影响（验证：一次真�?内存后端 `tools/call` 对比改造前后字段集�?

## 5. 回读接口 /api/logs

- [x] 5.1 �?`CompositeApp.__call__` 路由中、MCP 兜底分支之前新增 `/api/logs` 分支，解�?`Authorization` 头或 query 中的接入 Token �?`derive_owner_id`（验证：非法/缺失 Token 返回空集合而非他人数据�?
- [x] 5.2 实现 `_handle_operation_logs`：返回该 owner 当前 trace 内脱敏日志列表与 `next_cursor`（验证：单测按两身份写入后各自只读到自己�?
- [x] 5.3 确认新增分支不影�?`/access`、`/api/access-info`、`/api/showcase/data`、`/api/docs/*`、`/mcp` 既有路由（验证：现有路由测试 + `test_portal_proxy`/`test_session_permission` 等相关用例全绿）

## 6. 接入页日志展示区

- [x] 6.1 `access.html` 新增"本次操作日志"区块，复用页面已持有的接�?Token 轮询 `/api/logs`（验证：本地打开页面可见区块并按时间列出操作�?状�?时间�?
- [x] 6.2 空态与增量：无日志显示空态提示；�?`next_cursor` 做增量刷新（验证：执行一次写操作后区块自动出现该条）
- [x] 6.3 视觉与既有接入页深色霓虹体系一致，不展示任�?Token/口令明文（验证：对照 `showcase-access-experience` 既有风格，检�?DOM 无机密）

## 7. 回归与集成验�?

- [x] 7.1 运行 `pytest mcp_server/tests`，确认新增能力未破坏现有工具/鉴权/页面相关用例（验证：全量测试通过，失败项与本次改动无关者需单列说明�?
- [x] 7.2 `openspec validate add-write-operation-trace-log --strict`（若仓库支持）通过，能�?delta �?proposal 一致（验证：校验无 error�?
- [x] 7.3 端到端冒烟：启动服务，登录→执行一次协议层写与一次边缘写→接入页看到本次两条日志→重启服务后仍能回看（验证：手工核对四个观测点）
