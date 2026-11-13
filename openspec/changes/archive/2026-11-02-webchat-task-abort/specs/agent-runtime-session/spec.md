# agent-runtime-session Delta

## ADDED Requirements

### Requirement: 执行中的任务必须可中止

Web 会话 MUST 支持中止当前任务：`POST /api/sessions/{id}/abort`（租约校验）
MUST 取消当前 asyncio 轮次任务并显式关闭 SDK 查询生成器；MUST 复位
`turn_running`、清理本会话旧确认票据，并追加 `turn_aborted` 事件。
同时 MUST 使用会话 MCP Token 请求服务端建档批次中止
（`POST /api/archive/tasks/{task_id}/cancel`），服务端 MUST 在当前工作单元
完成后停止并返回 `cancelled=true`、`cursor`、`remaining` 与 `report_id`。
中止 MUST NOT 自动回滚已完成的写入，补偿清单 MUST 保留可查。

#### Scenario: 中止执行中的轮次

- **WHEN** 轮次正在执行时用户点击「停止」
- **THEN** 轮次被取消，事件流出现 `turn_aborted`，界面不再显示“执行中”

#### Scenario: 中止服务端建档批次

- **WHEN** 客户端超时但 MCP 服务端仍在执行建档批次
- **THEN** 取消请求使服务端在当前单元后停止，返回 `cancelled=true` 与续跑游标，
  已建设备与补偿清单保留

#### Scenario: 中止后旧确认不生效

- **WHEN** 中止完成后再调用此前已确认的写工具
- **THEN** 旧票据已清理，需重新确认后才放行
