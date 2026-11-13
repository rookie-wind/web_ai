## Context

当前 [adapter.py](file:///e:/codeGIT/pca-mcp-server/webchat/webchat/sdk_runtime/adapter.py)
每轮调用一次 `q.query(...)`，`abort()` 通过 `agen.aclose()` 关闭生成器。
`q.query` 文档明确不支持中断，会话上下文随生成器关闭而不可保证。

`QoderSDKClient` 的行为已由 7 个真实运行探针确认（见 proposal 表格）。其中两条
对设计有决定性影响：

1. `interrupt()` 能立即结束当前轮（`error_during_execution`），`session_id` 不变，
   下一轮仍能正确引用上一轮上下文；
2. `interrupt()` **不能**停止已进入执行的 MCP 工具（11 秒后服务端仍完成写入）。

因此：迁移解决“轮次可中断 + 上下文可继续”，但服务端取消契约必须原样保留。

## Decisions

### D1 每会话一个持久 `QoderSDKClient`

- 会话创建时 `connect()`（不带 prompt，探针已验证可行）；会话结束/回收时
  `disconnect()`。
- 客户端实例绑定在 `AgentHandle` 上，与现有 1:1:1（会话—CLI—凭据）模型一致。
- 客户端 MUST 在其 `connect()` 所在的同一 asyncio 上下文中使用（SDK 文档约束：
  内部常驻 anyio task group）；Web 端每个会话本就在独立任务/事件循环内运行，满足该约束。

### D2 单接收循环，跨轮复用

- 每会话启动一次 `receive_messages()`，由常驻接收任务消费；轮次只负责“发 query +
  等本轮的 `ResultMessage`”。
- 接收任务 MUST 以 `session_id`/轮次计数而非消息类型切分归属，避免上一轮尾包被计入
  下一轮。
- 禁止在同一客户端上并发启动第二个 receiver（探针只验证了单 receiver，未验证多
  receiver 并发）。

### D3 `interrupt()` 映射为 `turn_aborted`，且保留服务端取消

- 中止顺序：先请求 MCP 批次取消（`POST /api/archive/tasks/{task_id}/cancel`）→
  再 `client.interrupt()` → 复位 `turn_running`、清理本会话旧票据、追加
  `turn_aborted`。
- 若本轮 `ResultMessage.subtype == "error_during_execution"` 且本轮已被标记为中止，
  事件层 MUST 记为 `turn_aborted`；未被标记的中止场景仍按 `error` 处理。
- 空闲时 `interrupt()` 亦安全（探针 `_probe_client_idle.py`），故中止接口无需先
  判断是否正在执行。
- 不在中断后自动 `disconnect()`：上下文必须保留以便继续；仅会话结束才断开。

### D4 流式去重

- `include_partial_messages=True` 时，`StreamEvent` 的 `content_block_delta` 文本与
  随后的 `AssistantMessage` 文本一致（探针两轮均 `duplicate=True`）。
- 事件层选择：**有 delta 时只发 `text_delta`，`AssistantMessage` 文本不重复发**；
  无 delta（例如工具调用轮或短回复未产生增量）时用 `AssistantMessage` 文本兜底。
- 该规则与既有规格“流式增量与完整文本块 MUST NOT 重复产出”一致。

### D5 工具面与门禁不变

- `hooks`（PreToolUse）与 `can_use_tool` 在 client 模式均已验证生效，现有写入
  门禁、grant 票据、确认卡片流程不改。
- `tools`/`allowed_tools`/`skills=None`/`setting_sources=[]` 维持现状。

### D6 兼容与回退

- HTTP 契约不变：`POST /api/sessions/{id}/abort` 请求/响应、`turn_aborted` 事件、
  `turn_running` 字段均不变，前端无需改动。
- 若 `interrupt()` 抛错或 10 秒内未收到本轮 `ResultMessage`，回退到取消接收/轮次
  任务的兜底路径，并记 `error` 事件说明中断失败；MUST NOT 静默挂起。

## Risks / Trade-offs

- **已验证范围有限**：单 receiver 只验证两轮、短文本；长输出、多工具连续轮次、
  接收循环在轮次切换时的事件归属尚未验证，需在实现阶段补测。
- **已发出的 MCP 工具无法中断**：用户点击停止后，服务端可能仍完成当前设备写入；
  只能依赖取消代际在“下一单元前”停止，已完成的写入不回滚。
- **进程生命周期**：持久客户端意味着 CLI 子进程随会话存活，空闲回收策略需与之
  对齐（沿用既有空闲回收规格）。
- **partial 去重规则依赖探针的短文本样本**：若长文本下 delta 与完整文本并非完全
  相同，兜底逻辑可能漏字；实现时需按“delta 累计优先、完整文本仅在无 delta 时使用”
  的单向规则，避免双发。

## Migration

1. 适配层改为 `QoderSDKClient`：`connect()`、常驻 receiver、轮次发送与结果等待。
2. `abort_turn` 改为先 MCP 取消再 `interrupt()`，保留兜底。
3. 事件归一化加入 partial/完整文本去重与 `turn_aborted` 映射。
4. 回归：现有 abort、串行轮次、确认卡片、写入门禁用例必须全绿。
