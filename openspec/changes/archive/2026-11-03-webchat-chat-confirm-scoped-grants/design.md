## Context

当前确认链路（见 proposal.md - Why）：`WriteGate.decide` 对 write/provision 无票即
deny，`adapter._pre_tool_use` **立即同步返回 deny**（不阻塞等待用户）；被拒后模型仍在
其当前轮内自行反应。前端 `renderGateCard` 按 `confirmable`/`guard` 分流弹卡或弱提示；
确认走 `/confirm`，返回 `turn_running` 快照，前端据此决定是否 `sendMessage` 续跑
（`turn_running` 为真时抑制续跑）。约束：不得改动 `/confirm` 端点契约、不得破坏
"未确认零写入"、不得触碰 IDE 族长期凭据语义。

## Goals / Non-Goals

**Goals:**
- 让一次任务的用户确认次数从"每个不同写工具一次"降到"每个 task 作用域一次"。
- 把无参确认从模态卡迁到会话口令，同时保住后端验票权威（模型不能自授权）。
- 确认落在 `turn_running` 时续跑不丢失。

**Non-Goals:**
- 不改滑动消费/ TTL 回收本身（上一变更已定）。
- 不为无参写入引入新的独立授权端点（复用 `/confirm`）。
- 不放宽绝对禁止类（`login`/读越界）与敏感凭据的卡片收集路径。

## Decisions

### D1：确认粒度用"活动 task 作用域"，改造点收敛在 `resolve_target`
`resolve_target(bare, tool_input)` 现为"带 `plan_id`/`task_id` 用其值，否则回退
`bare`"。改造：会话/运行时维护 `active_task_id`（首次由 `edge_get_token` 成功后写入的
`task_id`，或计划创建事件设置）；`resolve_target` 命中带 `task_id`/`plan_id` 时照旧，
**且写入调用若处于 `active_task_id` 有效期内也归并到该作用域**；否则回退 `tool_name`。
作用域终点：新 `task_id` 覆盖或窗口 TTL 到期。
- 备选：为每次任务预生成一个 scope id 强塞进所有写工具入参——被否，改动面铺到 42 工具
  与上游建档、且工具入参本就可能不带；以运行时 `active_task_id` 归并最小侵入。

### D2：无参确认走会话口令 `/确认`（M2），而非模态卡
- 采用行首 `/确认` 作为授权信号：前端识别用户消息行首 `/确认` → 对会话当前**唯一**
  pending 目标调用 `/confirm` 铸票 → 该用户消息本身即新一轮，模型带票重跑。
- 备选 M1（会话流内嵌小按钮）：更无歧义，但用户明确要"确认来自对话框"，故口令为主干；
  M1 可作为后续可选加固，不纳入本变更。
- 备选 M3（存在 pending 时下一条消息即授权）：被否——会把任意闲聊误当写授权，破坏确认语义。
- pending 目标来源：`decide` deny 无参写入时，把 `(tool_name, target)` 记为会话
  `pending_confirmation`（一次只留最近一个）。

### D3：`decide` 的 deny 结论区分"需补参"与"仅需确认"两类语义
现状 deny 只给 `confirmable`。新增：provision/write 中，登记入参（`GATED_PARAM_REGISTRY`
命中）者结论标注"走参数卡"，其余标注"走会话口令确认"，供系统提示与前端据此分流。
系统提示新增路由：无参写入被拦 → 先播报摘要再请求 `/确认`，不得自授权。

### D4：竞态修复用"待办续跑 + turn_done 补发"
前端 `okBtn`/口令铸票成功后，若 `r.turn_running` 为真：不再丢弃，而是把续跑内容
（带参消息或"请继续"）登记到 `state.pendingContinuations[session]`；`turn_done`
（`finishTurn`）处理时若有待办则自动 `sendMessage` 补发（此时已非 running，不撞 409）。
`turn_aborted` 时清空该会话待办，避免中止后误续跑。

## Risks / Trade-offs

- [确认面 > 已见摘要面] task 作用域一次确认覆盖后续未逐一列出的写 → 靠 D2/D3 要求
  模型在 `/确认` 前播报计划摘要（含影响台数）缓解；无 task 的零星写仍单目标确认兜底。
- [口令误触发] 用户正文里恰好以 `/确认` 开头 → 限定"仅当存在 pending 且行首完全匹配"
  才铸票；无 pending 时按普通文本处理。
- [待办续跑与中止竞态] 中止后补发会造成"已停又跑" → `turn_aborted` 清空待办（D4）。
- [active_task_id 串场] 跨任务未及时覆盖导致旧作用域误放行 → 新 `task_id` 覆盖 +
  TTL 到期回收双保险；会话结束 `clear_session` 清票据。

## Migration Plan

纯行为调整，无数据迁移。灰度：先保证"仅登记入参者弹卡"（其余从卡降级为口令），
观察确认次数与续跑成功率；异常可回退前端分流（保留口令识别、暂不启用作用域归并）。

## Open Questions

- `/确认` 是否需要配套的显式"忽略"口令（如 `/忽略`）：默认"不回即不授权"已够，留待
  实测后决定，不影响规格与任务拆分。
