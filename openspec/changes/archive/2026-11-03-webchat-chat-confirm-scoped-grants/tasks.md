## 1. task 作用域归并（grants 侧）

- [x] 1.1 前置：`webchat/.venv` 可跑 `pytest`；需先验证 `resolve_target` 现仅按入参 `plan_id`/`task_id` 归并。要做：写失败测试——构造会话 `active_task_id=T`，两次调用不带 `task_id` 的写工具，断言其验票目标均归并为 `T`（当前应红：回退成 `tool_name` 而目标不一致）。通过标准：`pytest -k task_scope` 先红后绿。依赖：无。
- [x] 1.2 前置：1.1 已红。要做：`resolve_target`/`WriteGate` 接入"活动 task 作用域优先"——写入处于 `active_task_id` 有效期内即归并到该作用域，否则回退 `tool_name`；新 `task_id` 覆盖旧作用域。通过标准：1.1 测试转绿，且"不带 task 的零星写回退单目标"用例（1.3）通过。依赖：1.1。
- [x] 1.3 前置：1.2 完成。要做：加失败测试锁定"无 `task_id` 且无活动作用域"的写回退 `tool_name` 粒度、一次确认不覆盖另一 `tool_name`；再验证"带同一 `task_id` 的不同写工具一次确认全覆盖 + 停止超 TTL 后需重确认"。通过标准：`pytest -k scope_fallback or scope_batch` 全绿。依赖：1.2。

## 2. deny 语义分流与系统提示路由

- [x] 2.1 前置：`GATED_PARAM_REGISTRY` 成员判定可用。要做：写失败测试——`decide` 对"登记入参的 write/provision"与"无参 write"返回可区分的拒绝语义（如 payload/结论标记 `needs_params` vs `chat_confirm`）。通过标准：`pytest -k deny_kind` 先红后绿。依赖：1.2。
- [x] 2.2 前置：2.1 完成。要做：在 `decide`/`adapter` 落地 2.1 结论；`edge_get_token` 走"参数卡"、其余无参写走"会话口令"；绝对禁止类维持 `confirmable=false`。通过标准：2.1 测试绿 + `pytest -k login_forbidden` 既有绝对禁止用例仍绿（不回归）。依赖：2.1。
- [x] 2.3 前置：2.2 完成。要做：系统提示新增路由段——无参写入被拦须先在会话播报计划摘要（含影响台数）再请求 `/确认`，不得自授权、不得用口令索要密码/验证码。通过标准：以 headless 会话探针驱动一次无参写被拦，断言模型回复含摘要与 `/确认` 请求且未自称已授权（探针留证）。依赖：2.2。

## 3. 前端：确认卡触发面收窄 + 口令确认

- [x] 3.1 前置：`node --check` 可用；后端 2.x 结论已定义。要做：改 `renderGateCard` 分流——仅 `GATED_PARAM_REGISTRY` 命中的工具弹参数表单卡；无参写 `confirmable=true` 不再弹模态卡（其确认经会话口令），绝对禁止/护栏仍弱提示。通过标准：`node --check app.js` 通过 + 事件回放：`edge_get_token` 渲染表单卡、无参写不产生模态卡（`_ac1`/drill 观察留证）。依赖：2.2。（代码已完成：`renderGateCard` 按 `p.confirm_kind` 分流，`chat_confirm` 走 `renderChatConfirmPrompt` 弱提示；`node --check` + 静态断言 `test_gate_card_confirm_kind_dispatch` 转绿；live 事件回放用户验收通过。）
- [x] 3.2 前置：3.1 完成；存在 `pending_confirmation`。要做：前端识别用户消息**行首** `/确认`（且会话有唯一 pending）→ 复用 `/confirm` 对该 pending 目标铸票并发起该轮；无 pending 或正文非行首匹配时按普通文本处理。通过标准：drill——发 `/确认` 后目标写入放行；发"我先问下 /确认 怎么用"（非行首）不触发授权；无 pending 时 `/确认` 不铸票（留证）。依赖：3.1, 1.2。（代码已完成：`isChatConfirmCommand` 仅锚定行首 `^/确认`，`handleChatConfirm` 对唯一 pending 铸票后转新一轮；静态断言 `test_chat_confirm_command_mints_unique_pending` 转绿；live drill 用户验收通过。）

## 4. 竞态修复：待办续跑

- [x] 4.1 前置：`turn_running`/`turn_done`/`turn_aborted` 事件路径明确。要做：写可运行验证（webchat 侧最小前端状态单测或 e2e 脚本）——确认返回 `turn_running=true` 时，续跑被登记为待办，`turn_done` 后自动补发；`turn_aborted` 时清空待办。通过标准：该用例先红（现直接丢弃续跑）后绿。依赖：3.1。（静态守护 `test_pending_continuation_captured_and_flushed` 先红后绿；行为级 live 演练并入 4.2。）
- [x] 4.2 前置：4.1 已红。要做：`okBtn`/口令铸票成功且 `r.turn_running` 为真时登记 `state.pendingContinuations[session]`；`finishTurn`（`turn_done`）补发；`turn_aborted` 清空。通过标准：4.1 用例转绿 + 参数卡"填凭据后立刻点确认"能续跑到完成（drill 留证）。依赖：4.1, 3.2。（代码已完成：okBtn/`handleChatConfirm` 在 `turn_running` 登记 `state.pendingContinuations`，`finishTurn` 经 `flushPendingContinuation` 补发，`turn_aborted` 清空；静态断言转绿；"填凭据后立刻点确认"live drill 用户验收通过。）

## 5. 回归与收口

- [x] 5.1 前置：1–4 完成。要做：跑 `webchat` 全量 `pytest`（`webchat/.venv`）与 `mcp_server/tests` 全量（根 `.venv`），确认门禁/滑动/凭据既有测试无回归。通过标准：两套全量退出码 0、无 F/E。依赖：4.2。（webchat 202 passed、mcp_server 全量无 F/E，均已绿。）
- [x] 5.2 前置：5.1 完成。要做：真实建档长任务演练——观察一次任务确认次数显著下降（task 作用域生效）、无参写经 `/确认` 授权、"立刻点确认"不再卡死。通过标准：演练记录显示确认次数按任务聚合、续跑成功、零未确认写入。依赖：5.1。
- [x] 5.3 前置：全部实现完成。要做：`openspec validate webchat-chat-confirm-scoped-grants --strict` 通过后交人工评审/归档。通过标准：validate 退出码 0、结构有效。依赖：5.2。
