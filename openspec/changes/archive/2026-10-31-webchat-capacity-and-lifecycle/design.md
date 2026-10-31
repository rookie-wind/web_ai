## Decisions

### D1 SSE 增量读取（字节偏移 + 文件大小缓存）

- `EventStore.replay_with_offset(after_seq)`：建连时一次历史回放，并在**同一
  把锁内**返回当前文件末尾字节偏移，避免"重放结束到记录偏移之间"新增事件丢失。
- `EventStore.read_after_offset(offset)`：只读偏移后新增字节，只解析末尾换行符
  之前的完整行；同时维护 `_sizes` 缓存，`size <= offset` 时**不打开文件**直接返回。
- 实测：2.97 MB / 19,927 条事件的会话，全量 replay 105 ms；增量空轮询 0.002 ms。
- SSE 心跳改为真正按 15 秒重置（修复原先 15 秒后每 0.5 秒重复 ping 的问题）。

### D2 空闲回收采用 close 而非 delete

- `WebSession.last_activity` + `turn_running`；消息、租约、确认、SSE 轮询、
  上传/下载均调用 `runtime.touch`。
- `sweep_idle(idle_ttl)`：跳过 closed 与执行中的会话；超过阈值调用
  `close(reason="idle")`，撤销凭据、释放槽位、产事件；工作区与产物按既有保留期。
- 后台循环 `idle_sweep_loop` 在 `api.lifespan` 与保留期任务并列启动。
- `close()` 先置 `closed=True` 再异步回收，避免回收期间新消息进入。

### D3 并发轮次护栏在发送消息入口裁决

- `SessionRuntime.try_begin_turn()/end_turn()` 使用事件循环内的整数计数（无需
  异步锁）；超限时 `POST /messages` 直接 409，不写用户事件、不起后台任务。
- 后台任务 `finally` 释放名额；异常记日志但不拖垮服务。

### D4 账号库按 mtime 热加载

- `AccountsStore` 记录 `st_mtime_ns`；`find` 与 `config_error` 读取前比较 mtime，
  变化即 `_load()`。新增账号、禁用、损坏文件都即时生效（损坏仍走既有 503 语义）。

### D5 默认值调整

- `WEBCHAT_MAX_INSTANCES` 4→100；`WEBCHAT_MAX_SESSIONS_PER_USER` 2→5；
  新增 `WEBCHAT_SESSION_IDLE_TTL=1800`、`WEBCHAT_IDLE_SWEEP_INTERVAL=60`、
  `WEBCHAT_MAX_CONCURRENT_TURNS=16`。既有测试显式传参，不受默认值变化影响。

## Risks

- 100 槽位不代表 100 并发轮次；模型服务侧并发配额与单 CLI 进程内存仍是上限，
  需部署后压测（脚本已提供）。
- 空闲回收会结束长时间未操作的会话；只要页面 SSE 连接存在即持续刷新活动时间，
  正常使用不会被误杀；执行中的轮次显式跳过。
- 增量读取依赖事件文件 append-only；删除会话时 SSE 通过 `runtime.get` 为 None
  终止，避免读到已删除文件。
