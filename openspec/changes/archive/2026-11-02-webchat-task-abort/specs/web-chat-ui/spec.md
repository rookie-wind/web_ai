# web-chat-ui Delta

## ADDED Requirements

### Requirement: 执行中必须提供停止入口

前端 MUST 在轮次执行期间提供「停止」入口；点击后 MUST 经二次确认再调用
`POST /api/sessions/{id}/abort`。`turn_done`、`turn_aborted` 或
`session_closed` 事件到达后 MUST 收起该入口；页面重新载入时 MUST 依据
会话列表的 `turn_running` 恢复入口。中止后 MUST 展示“已完成的写入不会回滚”。

#### Scenario: 停止按钮可见

- **WHEN** 消息发送成功且轮次正在执行
- **THEN** 页面显示「停止」，直到本轮结束或中止

#### Scenario: 重载后恢复

- **WHEN** 用户刷新页面且服务端仍有执行中的轮次
- **THEN** 「停止」入口按 `turn_running` 恢复显示

#### Scenario: 中止后的提示

- **WHEN** 收到 `turn_aborted`
- **THEN** 页面显示“任务已中止；已完成的写入不会回滚”，并允许继续输入
