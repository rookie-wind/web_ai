## 1. 适配层迁移

- [x] 1.1 `AgentHandle` 持有持久 `QoderSDKClient`；会话创建 `connect()`、结束
  `disconnect()`；同一 asyncio 上下文内使用。
- [x] 1.2 每会话启动一个常驻 `receive_messages()` 接收循环，跨轮消费并按本轮
  归属归类；接收异常产 `error` 事件并使会话不可继续。
- [x] 1.3 轮次改为“发送 query + 等待本轮 `ResultMessage`”，不新建客户端、不新建
  receiver。
- [x] 1.4 保留 `hooks`、`can_use_tool`、`tools`、`skills=None`、
  `setting_sources=[]` 现状。

## 2. 中止语义

- [x] 2.1 `abort_turn` 顺序为：MCP 批次取消 → `client.interrupt()` → 复位
  `turn_running` → 清理旧票据 → 追加 `turn_aborted`。
- [x] 2.2 被标记中止的轮次映射为 `TurnAborted`，运行时不产 `turn_done`；
  非中止场景仍按 `error`。
- [x] 2.3 `interrupt()` 失败或宽限期（5s）内无本轮结果时回退取消任务兜底；
  MUST NOT 自动 `disconnect()`。
- [x] 2.4 空闲中止安全；HTTP 契约与 `turn_running` 字段不变（前端无需改动）。

## 3. 流式去重

- [x] 3.1 有 `content_block_delta` 时只由增量产 `text_delta`；完整文本不重复产出
  （uuid 命中或增量累积文本与完整文本相同均跳过）。
- [x] 3.2 无增量时以完整文本兜底一条 `text_delta`。
- [ ] 3.3 长文本、多工具连续轮次下补测去重与轮次归属（当前仅短文本两轮验证）。

## 4. 验证

- [x] 4.1 探针复跑：client 模式 hook / can_use_tool / interrupt / 单 receiver
  跨两轮均通过；另以真实 SDK 跑通适配层三件套（3 轮同会话、中止抛
  `TurnAborted`、中止后继续成功）。
- [x] 4.2 webchat 全量 pytest 通过（**190 passed**）。
- [x] 4.3 主项目 pytest 基线全绿（**773 passed / 1 skipped**）。
- [ ] 4.4 真实 Web 演练：创建会话 → 执行长轮次 → 点击停止 → 收到
  `turn_aborted` → 同会话继续提问并正确引用上文（适配层已验，页面级待验）。
- [x] 4.5 `openspec validate --strict` 通过。
