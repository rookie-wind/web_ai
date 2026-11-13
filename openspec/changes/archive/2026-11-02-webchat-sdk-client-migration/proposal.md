## Why

Web 端中止当前任务目前是**协作式**的：取消 asyncio 任务后显式 `aclose()`
关闭 `q.query` 的一次性查询生成器。该方式有两个已知缺口：

- `q.query` 本身不支持中断，轮次只能靠外部取消任务收尾，CLI 侧不一定及时退出；
- 关闭生成器后**会话上下文是否保留**没有契约，也无法在同一 CLI 实例上继续下一轮
  而不重启进程。

`QoderSDKClient` 提供有状态会话与 `interrupt()`，可在同一会话中断当前轮并继续。
为避免凭猜测迁移，先用真实运行探针验证其行为，再据此形成迁移规格（本变更只出规格，
不改代码）。

**探针结论（均为真实运行，非推断）**

| 探针 | 验证内容 | 结果 |
|---|---|---|
| `_probe_client_stream.py` | `connect()` 不带 prompt；单 receiver 跨两轮；独立任务发 `query` | 两轮均 `success`，跨轮接收不断流 |
| `_probe_client_multi_receiver.py` | `include_partial_messages=True` 下单 receiver 跨两轮 | 两轮均 `success`；每轮 1 个 delta，且 delta 文本与 `AssistantMessage` 文本**相同** |
| `_probe_client_context.py` | 轮次执行中 `interrupt()` | 立即返回（0.0s）；本轮 `ResultMessage` 为 `error_during_execution`；`session_id` 不变；下一轮 `success` 且正确回答上下文问答（`42`） |
| `_probe_client_idle.py` | 空闲时 `interrupt()` | 返回 ok；随后新一轮 `success` |
| `_probe_tool_interrupt.py` | 慢 MCP 工具执行中 `interrupt()` | 轮次很快以 `error_during_execution` 结束，但服务端工具 **11 秒后仍打印 end**；下一轮仍可继续 |
| `_probe_client_hook.py` | client 模式 PreToolUse Hook | 命中 `mcp__slow__slow_tool` |
| `_probe_client_can_use_tool.py` | client 模式 `can_use_tool` | 回调命中 `Write`，放行后文件真实创建，`result success` |

结论要点：中断可立即终止**轮次**并保留上下文；但**不会停止已进入执行的 MCP 工具**，
因此服务端批次取消契约必须保留，不能由 `interrupt()` 替代。

## What Changes

- **运行时形态**：Web 会话由“每轮 `q.query` 一次性查询”改为“每会话一个持久
  `QoderSDKClient`”；会话创建时 `connect()`，会话结束时 `disconnect()`。
- **接收形态**：每会话只保留**一个**常驻 `receive_messages()` 接收循环，跨轮持续
  接收并把消息归一化为事件契约 v1；禁止每轮新建 receiver。
- **中止语义**：`POST /api/sessions/{id}/abort` 改为调用 `client.interrupt()`；
  被中断轮次的 `error_during_execution` 结果 MUST 映射为 `turn_aborted`，不得
  渲染为普通错误；中止后同一会话 MUST 可继续下一轮。
- **服务端取消保留**：`interrupt()` 不停止已发出的 MCP 工具，中止流程 MUST 继续
  先行调用 `POST /api/archive/tasks/{task_id}/cancel`。
- **流式去重**：`include_partial_messages=True` 下增量与完整文本内容相同，事件层
  MUST 只取其一，避免前端重复展示。
- **工具面不变**：`hooks` 与 `can_use_tool` 已在 client 模式验证可用，写入门禁与
  确认票据机制沿用。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `agent-runtime-session`: 会话运行时改为持久客户端 + 单接收循环；中止改为
  `interrupt()` 且保留上下文的可继续语义；流式增量与完整文本去重。
