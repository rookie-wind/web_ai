## Context

- 本次交互中，`execute_archive_task` 客户端 300 秒超时后服务端继续执行，
  设备树从 342 增至 442、493；前端仍显示“执行中”。
- SDK `q.query` 不支持中断；`QoderSDKClient.interrupt()` 存在，但当前 adapter
  使用一次性查询。为避免大改，采用“取消 asyncio 任务 + 显式 `agen.aclose()`
  关闭查询生成器”的协作式中止，后续可平滑迁移到 client 模式。
- MCP 工作流是同步循环，没有取消信号；采用“取消代际”而非布尔 Event，避免
  上一次取消影响下一次执行。

## Decisions

### D1 Web：保留任务句柄 + 生成器关闭

- `WebSession.run_task` 保存 `asyncio.Task`；`_run` finally 清空。
- `POST /api/sessions/{id}/abort` 校验租约后调用 `runtime.abort_turn`：
  - 先请求 MCP 取消建档批次；
  - 再取消 run_task（最多等待 10 秒）；
  - 调用 `AgentHandle.abort()` 显式 `aclose()` SDK 查询生成器；
  - 复位 `turn_running`、清理旧 grant、追加 `turn_aborted` 事件。
- 已完成的写入不回滚；中止后旧确认票据作废，防止误放行。

### D2 MCP：取消代际 + 单元边界检查

- `EdgeSession.cancel_generation` 初始为 0；取消端点递增。
- `_execute_full_workflow` 在开始时记录代际，在每个工作单元前比较；变化则停止，
  返回 `cancelled=true`、`cursor`、`remaining`、`report_id`。
- 取消只在“当前单元完成后”生效，不打断正在进行的单台设备写入，保证回执可查。
- `POST /api/archive/tasks/{task_id}/cancel` 使用 Bearer 接入 Token 与
  `derive_owner_id` 归属校验；不提供强制 kill，避免半条写入无回执。

### D3 前端：停止按钮与状态

- 轮次发送成功后显示「停止」；`turn_done` / `turn_aborted` / `session_closed`
  收起；页面重载时用 `/api/sessions` 的 `turn_running` 恢复。
- 点击后二次确认，调用 abort；`turn_aborted` 事件渲染为系统提示。

## Risks / Trade-offs

- `agen.aclose()` 是协作式关闭，极端情况下 CLI 子进程可能延迟退出；随后续
  迁移到 `QoderSDKClient.interrupt()` 可改善。
- 取消不自动回滚，用户需用补偿清单确认式清理。
- 旧 grant 在中止时清空；若用户希望继续，需要重新确认。
