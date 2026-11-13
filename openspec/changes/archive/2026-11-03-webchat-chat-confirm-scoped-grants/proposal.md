## Why

建档等长任务里，一次任务会串起多个不同的写入工具；当前每个不带 `plan_id`/`task_id` 的写入都回退到 `tool_name` 粒度独立拦一次、弹一张确认卡，用户被迫"确认风暴"式点很多次卡。同时确认卡存在一个可复现的竞态：卡片弹出后立刻点"确认"，落进 `turn_running=true` 分支被抑制续跑、只指望模型自纠重试，而模型重试并不保证发生——用户看到"点了没反应、任务不继续"。

## What Changes

- **收窄确认卡触发面**：仅对 `GATED_PARAM_REGISTRY` 登记了入参的工具（如 `edge_get_token` 需现场收凭据）渲染**参数表单卡**；其余需要确认的写入**不再弹模态确认卡**。
- **纯确认改走对话框**（**BREAKING** 相对当前 UI 交互形态）：无参写入被门禁拒绝后，模型先在会话流播报计划摘要并请求用户回复口令 `/确认`；收到口令即对目标铸票并发起新一轮，模型带票重跑。人工确认仍在环，**"未确认零写入"不变**。
- **引入活动 task 作用域铸票**：以活动 `task_id` 作为票据目标（起点=首次产生 `task_id`；终点=新 `task_id` 覆盖或 TTL 到期回收）。带同一 `task_id` 的写入在一次 `/确认` 后于滑动窗口内全部放行；不带 `task_id` 的零星写入回退 `tool_name` 粒度、各确认一次（不扩大免确认面）。
- **修复参数卡确认竞态**：参数表单卡确认成功但 `turn_running=true` 时，把"带参续跑"排入 `turn_done` 自动补发的待办，而非丢弃并指望模型自纠。
- 会话一次只挂一个待确认目标；`/确认` 仅认行首；拒绝方式=不回 `/确认`（隐式不授权）。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `web-chat-ui`：改「写入确认卡片必须呈现参数摘要且未确认零写入」Requirement——确认卡触发面由"`confirmable` 非 false 即弹卡"收窄为"仅 `GATED_PARAM_REGISTRY` 登记入参的工具弹参数卡"；无参写入的确认改由对话框口令 `/确认` 承载（新增场景，保留"未确认零写入"相关场景）。
- `write-gate-isolation`：改「写入类操作必须持有计划域授权票据才可执行」Requirement——授权目标引入"活动 task 作用域"（带 `task_id` 的写归并到该 task、一次确认滑窗全覆盖），并明确"确认信号来自会话口令 `/确认`"；既有"无票据被拒/窗口内多次放行/失败不退票/只读不受影响"场景保留。
- `agent-runtime-session`：改「确认与凭据收集必须由前端卡片先行」及相关中止/续跑语义——门禁对无参写入 deny 后 MUST 回喂模型"在会话内请求用户 `/确认`"，并新增"待办续跑：确认落在 `turn_running` 时于 `turn_done` 补发"要求。

## Impact

- 代码：`webchat/webchat/static/js/app.js`（卡片分流、口令识别、待办续跑）、`webchat/webchat/grants.py`（`resolve_target` 作用域化、deny 结论携带"请会话内确认"信号）、`webchat/webchat/sdk_runtime/adapter.py` 与 `runtime.py`（deny 回喂、`turn_done` 补发待办、pending 登记）、`webchat/webchat/sessions_api.py`（口令铸票入口/复用 `/confirm`）。
- 规格：`web-chat-ui` / `write-gate-isolation` / `agent-runtime-session` 三份主规格随归档同步。
- 系统提示：需新增"写入被拦→会话内请求 `/确认`、不得自授权"的路由指令。
- 兼容性：不改 confirm 端点契约与"未确认零写入"不变量；参数卡仍走卡内提交；不触碰 IDE 族长期凭据语义。
