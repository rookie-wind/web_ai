## Context

改动落在 webchat 会话的 PreToolUse 门禁（`WriteGate`）与其确认链路上，服务端
`mcp_server/*` 不参与（`edge_get_token` 在服务端为 `edge_util`、本就不拦）。
动机见 proposal.md - Why，需求见 specs/write-gate-isolation/spec.md。

当前门禁把工具面收敛为三类并映射到两种处理路径：

- `classify_tool()` 返回 `login` / `write` / `read`；`read` 直通，`login`
  无条件 deny，`write` 走 grant 票据窗口。
- `edge_get_token` 被塞进 `LOGIN_TOOL_NAMES`，走 `login` 分支——即"无条件
  deny、不查票"。这条禁令被 `test_grants.py`、`test_gate_hook.py` 双重断言
  锁定，属刻意设计而非疏漏。
- 但 `login` 禁令的安防前提（"会话已持凭据"）只对云平台业务登录成立：
  webchat 会话不持有边缘后端账号密码，故该前提对 `edge_get_token` 不成立。
- 确认链路对任意 gate_blocked 一律铸票：`runtime.confirm_grant` 无条件写入
  grant、`tool_name` 硬编码为空串；前端 `renderGateCard` 对任何 gate_blocked
  都渲染"确认写入"。于是对绝对禁止类目标也会铸出一张永不参与校验的孤儿
  票据，用户确认成为空操作。

约束：`grants.py` 有意不 import `mcp_server`（保持平面隔离）；grant 为服务端
内存态、含 TTL 与目标键、不落盘；TTL 沿用 `DEFAULT_GRANT_TTL=300`。

## Goals / Non-Goals

**Goals:**
- 在门禁内恢复"webchat 会话可读边缘档案"的能力，且恢复路径复用既有 grant
  票据窗口，不新造第二套授权机制。
- 把"拒绝"拆成两种语义——需确认（可解除）与绝对禁止（不可解除）——并让
  事件流、前端、后端铸票三处对这两种语义的处理一致化。
- 用测试锁定新语义，防止再次漂移。

**Non-Goals:**
- 不改动服务端鉴权模型、归属键派生（`owner_ref` 与 sha256(token) 双轨漂移
  不在本次处理）。
- 不修复 `adapter` 流式模式下 `tool_call` 入参不回填、`tool_result` 不落盘
  的可观测性缺陷（proposal 已列为范围外）。
- 不引入 agent 可写的路径/命令白名单（C6 路线 A 范畴）。
- 不改变 20.* 门户代理侧约束；安全边界降级仅限 10.* 直连段。

## Decisions

### D1：`edge_get_token` 单列 `provision` 类，而非并入 `write`

新增模块级 `PROVISION_TOOL_NAMES = {"edge_get_token"}`，从
`LOGIN_TOOL_NAMES` 中移除 `edge_get_token`（`LOGIN_TOOL_NAMES` 收缩为
`{"login"}`）。`classify_tool()` 增加 `provision` 分支。

- 为何不并入 `write`：write 类的 grant 目标是从工具入参派生的 plan_id/task_id
  （写的是已存在的边缘会话）。而 `edge_get_token` 恰恰是**产出 task_id** 的
  开辟动作，入参里没有可绑定的既有目标，把两类混进同一集合会让"目标键从哪来"
  在 write 分支里变得含糊。单列 `provision` 让"开辟类工具以工具名自身为 grant
  目标"这一特例有明确归属。
- grant 目标取工具名 `edge_get_token`（与 `add_classify` 等以工具名为目标的
  write 工具同构），窗口语义、TTL、放行不退票逻辑全部复用 `_check_grant`。

替代方案：把 `edge_get_token` 归入 write。否决理由：目标派生路径不一致，
破坏 write 分支"目标来自入参"的不变式。

### D2：`decide()` 里 deny 分叉为两条语义出口

- `login` 分支保持"不查票、无条件 deny"，但其拒绝标注为**绝对禁止
  （forbidden / confirmable=False）**。
- 未知工具 Fail-Closed 分支同标 **forbidden**（不可经确认解除）。
- `provision` 分支：无有效 grant → deny 并标注**需确认（confirm_required /
  confirmable=True）**；有有效 grant → 放行。

`_deny()` 增加一个入参（如 `confirmable: bool` 或 `block_kind` 枚举），写进
`gate_blocked` 事件 payload 与审计行。事件仍"每次 deny 必入流"（不复用
gate-error 那条不落盘路径），保证断线回看与审计一致。

### D3：后端铸票端按目标类别拒绝绝对禁止类

`confirm_grant`（`runtime.py`）与 confirm 端点（`sessions_api.py`）在铸票前
把请求目标经 `classify_tool()` 判类：
- 目标为 `forbidden` 类（`login`、不在已知集内的工具）→ 拒绝铸票（返回
  4xx），不产生 grant。
- 目标为 `write`/`provision` 类 → 照常铸票。

同时纠正 `tool_name` 硬编码空串问题：铸票写入的 grant 目标键应与 decide()
校验时派生的目标一致，否则窗口内放行对不上票。

替代方案：前端拦一下即可，后端不改。否决理由：孤儿票据是后端状态，前端拦截
不消除后端垃圾票，且无法防止直接打 confirm 端点的绕过。

### D4：前端 `renderGateCard` 依 `confirmable` 分渲染

- `confirmable=True` → 渲染"等待用户确认"入口（沿用现有确认按钮）。
- `confirmable=False` → 不渲染确认按钮，改为明示"该操作被策略禁止，无法通过
  确认解除"。

这样绝对禁止类不再出现空操作确认；需确认类（含 `edge_get_token`）确认后可
真正解除。

### D5：测试与注释同步

- `test_grants.py` 防漂移断言 `LOGIN_TOOL_NAMES == registry_logins | {"edge_get_token"}`
  须改为反映新分类（`edge_get_token` 归 `PROVISION_TOOL_NAMES`）。
- 原"edge_get_token 必须被 deny"断言改为"无票 deny、且标注 confirmable"。
- `test_gate_hook.py` 同类断言同步。
- 新增用例：provision 经确认→票据窗口内放行、返回可用 task_id；过期→再确认；
  `login` deny 且 confirmable=False、confirm 端点拒绝对其铸票。
- grants.py 顶部"登录类工具禁用"注释改写为二分语义。

## Risks / Trade-offs

- **[降低一条被测试锁定的安全边界]** → 这是本次刻意接受的降级（用户已确认）。
  缓解：`edge_get_token` 仍需人工确认+TTL 窗口，非无条件放行；`login` 维持
  绝对禁止；改动仅及 10.* 直连段，20.* 门户代理不变。
- **[grant 目标键与校验派生不一致导致放行对不上票]** → 缓解：D3 明确铸票目标
  与 decide 校验目标同源（工具名），并在测试中覆盖"确认后再调用能命中票据"。
- **[未知工具 Fail-Closed 被误标为需确认，反向开口子]** → 缓解：D2 把未知工具
  与 `login` 同列 forbidden，confirm 端点对不在已知集的目标一律拒铸。
- **[前端只改渲染、后端仍铸孤儿票]** → 缓解：D3 后端铸票校验为权威闸门，前端
  渲染只是体验层，二者独立且都改。
- **[provision 特例增加认知负担]** → 缓解：用命名（PROVISION_TOOL_NAMES）与
  注释把"开辟类以工具名为目标"的特例显式化，不做隐式约定。

## Migration Plan

1. 改 `grants.py`：收缩 `LOGIN_TOOL_NAMES`、新增 `PROVISION_TOOL_NAMES`、
   `classify_tool` 加分支、`decide` 分叉 deny、`_deny` 带 confirmable 标记。
2. 改 `runtime.py` / `sessions_api.py`：铸票前判类拒绝对绝对禁止目标铸票、
   纠正 grant 目标键。
3. 改 `app.js` `renderGateCard`：按事件 payload 的 confirmable 分渲染。
4. 改 `test_grants.py` / `test_gate_hook.py`：更新防漂移与断言、补 provision
   放行/过期/绝对禁止拒铸用例。
5. 基线：改动前后各跑一次 webchat `.venv` 下的门禁相关测试，确认由绿→（更新
   断言后）绿；人工验证 webchat 内确认 `edge_get_token` 后能读到档案 task_id。

回滚：本变更集中于上述 5 个文件，revert 即恢复"绝对禁止 + 空操作确认"旧行为，
无数据迁移、无落盘态变更（grant 本为内存态）。
