## Why

长批次建档在客户端 300 秒超时后仍会在 MCP 服务端继续执行（实测设备树
342→442→493），而 Web 端没有中止入口：

- `send_message` 启动 `asyncio.create_task` 后不保留句柄；
- SDK 当前使用 `q.query`，其文档明确不支持中断；
- `execute_archive_task` 没有取消机制，客户端断开后服务端继续跑；
- 前端“任务进行中”指示只能等轮次结束，用户无法停止。

结果是会话长时间显示“执行中”，只能等待，或在服务端继续写入时反复确认。

## What Changes

- **Web 轮次中止**：`WebSession` 保存 `run_task`；新增
  `POST /api/sessions/{id}/abort`；取消任务、显式关闭 SDK 查询生成器，发
  `turn_aborted` 事件并复位 `turn_running`。
- **MCP 批次中止**：`EdgeSession` 增加取消代际；`execute_archive_task` 在每个
  工作单元前检查，代际变化即停止并返回 `cancelled=true`；新增
  `POST /api/archive/tasks/{task_id}/cancel`（Bearer + 归属校验）。
- **前端停止入口**：轮次执行期间显示「停止」按钮，确认后调用 abort；中止后
  收起“任务进行中”状态并提示“已完成的写入不会回滚”。
- **票据清理**：中止时清理本会话旧确认票据，避免后续误放行；不自动回滚已
  完成的建档，补偿清单保留。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `agent-runtime-session`: 任务必须可中止（Web 轮次 + 服务端批次）。
- `web-chat-ui`: 执行中必须提供「停止」入口。
