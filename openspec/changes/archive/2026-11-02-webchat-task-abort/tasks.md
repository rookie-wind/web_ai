## 1. Web 轮次中止

- [x] 1.1 `WebSession.run_task` + `send_message` 保存句柄，`_run` finally 清空。
- [x] 1.2 `POST /api/sessions/{id}/abort`（租约校验）；`runtime.abort_turn`
  取消任务、关闭查询生成器、清理旧 grant、发 `turn_aborted`。
- [x] 1.3 `AgentHandle.abort()` 显式 `aclose()` SDK 查询生成器；`close()` 复用。
- [x] 1.4 `EVENT_TYPES` 增加 `turn_aborted`。

## 2. MCP 批次中止

- [x] 2.1 `EdgeSession.cancel_generation`；`_execute_full_workflow` 单元边界检查，
  返回 `cancelled/cursor/remaining`。
- [x] 2.2 `POST /api/archive/tasks/{task_id}/cancel`（Bearer + 归属校验）。
  验证：`test_archive_cancel.py` 覆盖成功与跨归属 404。

## 3. 前端停止入口

- [x] 3.1 执行中显示「停止」；`turn_done/turn_aborted/session_closed` 收起；
  重载时用 `/api/sessions` 的 `turn_running` 恢复。
- [x] 3.2 `turn_aborted` 渲染系统提示；中止后不自动回滚。
  验证：`test_static_frontend.py` 标记 + `test_sessions_api.py` 端点用例。

## 4. 回归

- [x] 4.1 webchat 全量：**185 passed, 0 failed**。
- [x] 4.2 主项目基线：**773 tests / 0 failures / 1 skipped**（含新增 cancel 用例）。
- [x] 4.3 README 补充中止行为与端点。
- [x] 4.4 `openspec validate --all --strict` 通过后归档。
