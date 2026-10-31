## Context

见 proposal.md（Why）。设计输入均为已核实事实（引用一律用**符号锚**，
不用行号——两仓库副本行号已分叉，行号会烂）：

- **写入工具集合**：`mcp_server/server.py` 的工具注册表以 `"type"` 字段
  分类；`WRITE_TOOLS` 集合与注册表中 `type ∈ {write, edge_write}` 的工具
  一致——`write` 32 个云端写工具 + `edge_write` 10 个边缘写工具
  （`edge_upsert_device`/`edge_mount_device`/`edge_save_device_parameters`/
  `edge_set_device_param`/`edge_call_clock`/`edge_call_monitor_debug`/
  `execute_archive_task`/`edge_call_device_data`/`edge_apply_compensation_plan`/
  `edge_delete_device`）。`edge_util`（`convert_comm_address_tool` 纯计算、
  `edge_get_token` 边缘登录）与 `edge_plan`（`plan_device_archive` dry-run）
  **非写入**，不入集合。
- **登录类工具**：注册表 `type=login` 的 `login`（手机号+验证码换业务
  Token）与 `edge_get_token`（独立登录边缘后端）。webchat 会话已持 C3 mint
  的族凭据，这两个工具在 webchat 内 MUST 禁用（见 D3）。
- **edge 写守卫**：`_validate_plan_guard` / `_validate_plan_guard_qualify`
  校验 `plan_id == session.active_plan_id` 且 `confirm=true`——所有 edge 写
  工具**共享同一 active_plan_id**（本变更据此按 plan_id 铸一张覆盖整条
  序列的 grant，见 D2）；此为第二道防线，原样保留（见 D4）。
- **一键建档入口**：`execute_archive_task`（`edge_write`）单工具服务端编排
  全阶段（`stages="all"` → 建档/挂载/参数保存/时钟/下发/召测），支持
  `batch_size`/`budget`/`cursor` 分批续跑，取代客户端逐工具反复重规划
  （见 D6）。
- **SDK Hook**：`HookMatcher(matcher, hooks, timeout)` +
  `PreToolUseHookInput{hook_event_name, tool_name, tool_input, tool_use_id}`，
  回调返回 `SyncHookJSONOutput(permissionDecision=allow|deny, reason)`——
  V3 已验进程内回调可行且 deny 真实阻断。
- **C3 实例工具面（硬事实，纠正原 Context）**：`AgentHandle._build_options()`
  设 `QoderAgentOptions.tools=[]`，SDK 序列化为 `--tools ""`（**空基础工具
  集**）；`skills=["xlpa"]` → `allowed_tools=["Skill(xlpa)"]`。故 webchat
  会话内模型可用工具**只有 MCP 工具 + `Skill(xlpa)`**，内置
  Write/Edit/Read/Bash/Grep 等**根本不存在**。同处的
  `disallowed_tools=["Bash"]`/`permission_mode="default"` 是冗余保险，
  不改变"内置工具面为空"这一事实。

## Goals / Non-Goals

**Goals:**

- grant 计划域铸造/消费/窗口过期完整语义 + confirm 端点；
- PreToolUse 写入门禁（写入验票 + 登录类工具 deny）Fail-Closed；
- 建档统一走 `execute_archive_task` 一键入口（一次确认覆盖全阶段）；
- gate_blocked 事件入流 + 独立门禁审计台账；全套单测 + V7 探针留证。

**Non-Goals:**

- 不动 mcp_server 任何代码（第二道防线原样保留）；
- **不重建路径/命令白名单**：`tools=[]` 下无内置文件/命令工具面，白名单
  属死代码；若 C6 选路线 A（放开内置客户端工具）再由 C6 按真实工具面设计
  （见 Open Questions）；
- 不做前端确认卡片 UI（C7）；
- 不做 grant 参数级校验（MVP 粒度 = plan_id/task_id 或 tool_name，见 Risks）；
- 不做写入工具集合的动态配置（锁定代码内常量，变更走升版）。

## Decisions

### D1 写入工具集合的来源与形态

webchat 侧定义 `WRITE_TOOL_NAMES` 常量（云端 `write` 32 + 边缘
`edge_write` 10 = 42），**注释标明来源与锁定日期**（来源：server.py 注册表
`type ∈ {write, edge_write}`），不 import mcp_server（沿用 C2 包边界纪律）。
单测**按 `type` 字段正则解析 server.py 注册表**抽取 `{write, edge_write}`
全集与常量比对（同时覆盖云端与边缘、防漂移的廉价手段）；漂移由 CI 测试
暴露。同理定义 `LOGIN_TOOL_NAMES = {login, edge_get_token}`（D3 用）。

### D2 grant 存储与验票回调（计划域窗口语义）

```
webchat/webchat/grants.py
  GrantStore:
    mint(session_id, target) -> grant_id     # target = plan_id/task_id 或 tool_name
    check(session_id, target) -> bool        # 窗口内有效即放行（不销毁）
    （内存 dict[(session_id, target)] = expires_at；惰性过期清理）
```

- **窗口语义（修正原"一次性消费"）**：grant 按目标铸造，在 TTL 窗口内
  **可被同一目标的多次工具调用复用**——覆盖 (i) `execute_archive_task`
  的 batch/cursor 分批续跑、(ii) 逐台 edge 写序列（共享 active_plan_id）。
  一次确认 = 覆盖整个已确认计划，100 台设备 = 1 次确认（修硬伤一）。
- **消费时机（明文，防实施被"优化"）**：Hook 放行时即视为已消费/记账；
  工具**执行失败不退票**（不延长/不重铸），防重放窗口；窗口到期自然失效，
  同目标再写需重新确认。
- Hook 验票回调（adapter 内）：`tool_name ∈ WRITE_TOOL_NAMES` →
  `target = tool_input.get("plan_id") or tool_input.get("task_id") or tool_name`
  （edge 优先 plan_id/task_id，云端写用 tool_name）→ `grants.check(...)`；
- True → allow；False → deny + reason（"需用户确认后重试"）+ runtime 经
  writer 回调追加 gate_blocked 事件 + 审计台账记 deny；
- 回调内 try/except 全包：任何异常 → deny（Fail-Closed）；
- TTL 默认 300s（`WEBCHAT_GRANT_TTL` 可配）。

### D3 运行时工具面收敛与登录类工具禁用（替代原路径白名单）

`tools=[]` 已结构性关闭内置文件/命令工具（见 Context 硬事实），故本变更
**不实现路径白名单**（无对应工具面，实现即死代码）。PreToolUse Hook 的
非写入分支：

- `tool_name ∈ LOGIN_TOOL_NAMES`（`login`/`edge_get_token`）→ **deny**
  （webchat 会话已持族凭据，禁对话内业务登录改角色）；
- 其余 MCP 只读/探测/规划工具与 `Skill(xlpa)` → allow；
- **防御性兜底**：若出现任何不在已知 MCP 工具集内的工具名（即内置工具因
  配置漂移意外出现）→ deny（Fail-Closed），不放行未知面。

路线 A 的路径/命令白名单延至 C6 按真实工具面设计（见 Open Questions）。

### D4 与 MCP Server 既有守卫的双保险关系

webchat 门禁（第一道，进程内）与 mcp_server 的 `_require_super`/
`_validate_plan_guard`（plan_id+confirm，第二道，服务端）串联：即使第一道
被绕过（理论不可能），第二道仍要求 confirm=true 与 super 角色才放行写入。
模型自填 confirm=true 的幻觉场景被第一道拦截（无 grant），两道独立生效。

### D5 confirm 端点、gate_blocked 事件与审计台账

- `POST /api/sessions/{id}/confirm`：body `{target}`（plan_id/task_id 或
  tool_name，前端从 gate_blocked 事件 payload 取得）；校验会话票据 + 写
  租约持有者；铸造 grant 返回 `{ok, expires_at}`；
- 事件契约：`events.EVENT_TYPES` 增加 `gate_blocked`；adapter 在 deny 时经
  runtime 提供的 writer 回调写入（adapter 不直接依赖 EventStore，保持只认
  SDK 与纯函数）；
- **审计台账（新增，独立于会话生命周期）**：webchat 侧追加门禁审计 JSONL
  （confirm-mint / allow / deny 各一条，含 ts、session_id、target、
  tool_name、decision、reason），不随会话结束清理，供验收举证与汇报。

### D6 建档执行统一走一键编排入口

webchat 建档执行 MUST 走 `execute_archive_task`（单工具、`stages="all"`、
服务端编排全阶段）：一次调用 = 一张 plan/task 域 grant = 一次用户确认覆盖
整条建档闭环。batch/cursor 续跑复用同一 grant 窗口（D2）。逐台 edge 写工具
仍被门禁覆盖（各自需 grant），但因共享 active_plan_id，一次计划确认即覆盖，
不产生确认风暴。

## Risks / Trade-offs

- [grant 粒度不校验参数] 用户确认"加品牌 X"，模型可传品牌 Y
  （`_require_super` 只查角色不查参数）。MVP 接受此粒度（plan_id/tool_name
  级）；**C7 确认卡片 MUST 带参数摘要兜底**（用户确认实际值），此为 C7 硬
  依赖，非 C4 代码项。
- [窗口语义放宽了"二次写入需重确认"] 窗口内同目标可多次写——这是修硬伤一
  的必要取舍；风险由 (i) 目标绑定 plan_id/task_id（仅限已确认计划）、
  (ii) TTL 窗口上限、(iii) 第二道防线服务端校验 共同约束。
- [deny 误伤只读/规划] 写入集合锁定注册表 `{write, edge_write}`，登录集合
  锁定 `{login, edge_get_token}`，单测按 type 解析比对；漏判由第二道防线兜底。
- [Hook 超时] HookMatcher timeout 默认 60s 足够；内存直查 <1ms（V7 留证）。
- [事件循环被模型轮占用致 gate_blocked 延迟] 与 C3 已知问题同源，C7 打磨。

## Migration Plan

1. grants.py（窗口语义 + 消费时机）+ 单测 → WRITE_TOOL_NAMES/
   LOGIN_TOOL_NAMES 常量 + 按 type 解析的防漂移单测 → adapter PreToolUse
   hook（验票 + 登录 deny + 防御兜底 + gate_blocked writer + 审计回调 +
   try/except 全包）+ 单测 → runtime/sessions_api 接线（confirm 端点 +
   gate_blocked 事件 + 审计 JSONL）→ webchat pytest 全绿；
2. V7 探针（真实 SDK 会话 + 测试 MCP Server）：无确认调写入被 deny 且产生
   gate_blocked → confirm 铸票 → `execute_archive_task stages=all` 单次放行
   跑完全阶段 → batch/cursor 续跑复用同 grant → 登录类工具被 deny →
   窗口过期后再写被 deny；全程事件流 + 审计台账 dump 留证，记录验票时延；
3. 主 pytest 全绿（mcp_server 零改动证明）+ IDE 回归（IDE 会话无 Hook，
   行为不变）。

回滚：webchat 单侧改动，revert 即回 C3 状态；无数据迁移。

## Open Questions

- **C6 路线 A/B（issue 9）**：C4 按当前 `tools=[]`（路线 B 形态：仅服务端
  工具）对齐，不预建路径/命令白名单。若 C6 最终选路线 A（放开内置客户端
  工具），D3 的白名单与 Bash 边界由 C6 按真实工具面设计——本变更不阻塞、
  不预支。此拍板项归属 C6 开工前。
