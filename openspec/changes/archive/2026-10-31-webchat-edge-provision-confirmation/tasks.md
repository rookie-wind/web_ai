## 1. 门禁分类与拒绝语义（grants.py）

- [x] 1.1 从 `LOGIN_TOOL_NAMES` 移除 `edge_get_token`（收缩为 `{"login"}`），
      新增模块级 `PROVISION_TOOL_NAMES = {"edge_get_token"}` 并纳入 `__all__`；
      验证：导入后 `classify_tool("edge_get_token")` 不再返回 `login`。
- [x] 1.2 在 `classify_tool()` 增加 `provision` 分支（位于 write 判断之后、
      read 兜底之前）；验证：单测对 `edge_get_token` 断言返回 `provision`。
- [x] 1.3 在 `WriteGate.decide()` 将 `provision` 接入 grant 票据窗口：无有效
      grant 时 deny 并标注需确认，有有效 grant 时放行（复用 `_check_grant`，
      目标键取工具名）；验证：无票 deny、有票放行两条路径各有断言。
- [x] 1.4 给 `_deny()` 增加"是否可经确认解除"标记（如 `confirmable: bool`），
      写进 `gate_blocked` 事件 payload 与审计行；`login` 分支与未知工具
      Fail-Closed 分支标注 `confirmable=False`，`provision`/write 标注
      `confirmable=True`；验证：事件 payload 含该字段且值随类别正确。
- [x] 1.5 改写 `grants.py` 顶部"登录类工具禁用"注释为"绝对禁止 vs 需确认"
      二分语义；验证：注释与 `decide()` 实际分叉一致。

## 2. 后端铸票闸门（runtime.py / sessions_api.py）

- [x] 2.1 `runtime.confirm_grant` 铸票前用 `classify_tool()` 判类，对
      绝对禁止类目标（`login`、不在已知集内的工具）拒绝铸票、不写 grant；
      验证：对 `login` 调 confirm 后 `_check_grant` 仍查无票据。
- [x] 2.2 纠正铸票写入的 grant 目标键：与 `decide()` 校验时派生的目标同源
      （`edge_get_token` 用工具名），消除 `tool_name` 硬编码空串导致的目标
      错配；验证：确认后同一目标在 TTL 窗口内能命中票据并放行。
- [x] 2.3 `sessions_api` confirm 端点对绝对禁止类目标返回 4xx（拒绝请求），
      需会话票据鉴权且持写租约的前提不变；验证：非租约仍 409、禁止目标 4xx、
      需确认目标正常铸票三条分支各有断言。

## 3. 前端渲染（static/js/app.js）

- [x] 3.1 `renderGateCard` 读取 gate_blocked 事件 payload 的 `confirmable`
      标记：`true` 渲染"等待用户确认"入口，`false` 隐藏确认按钮并明示"该操作
      被策略禁止，无法通过确认解除"；验证：两类事件分别渲染出/不出确认按钮。

## 4. 测试与防漂移（webchat/tests）

- [x] 4.1 更新 `test_grants.py` 防漂移断言，反映 `edge_get_token` 归
      `PROVISION_TOOL_NAMES`、`LOGIN_TOOL_NAMES` 仅剩 `login`；验证：该断言
      在未改代码时失败、改后通过。
- [x] 4.2 将"edge_get_token 必须被 deny"旧断言改为"无票 deny 且
      `confirmable=True`"；`login` 断言补 `confirmable=False`；验证：两条断言
      反映新语义。
- [x] 4.3 同步 `test_gate_hook.py`：edge_get_token 相关断言改为需确认语义，
      `login` 保持绝对禁止；验证：钩子级 deny 事件带正确 `confirmable`。
- [x] 4.4 新增 provision 端到端用例：确认→窗口内放行→返回可用 task_id；
      窗口过期（> `DEFAULT_GRANT_TTL`）→同目标再次调用需重新确认；验证：
      两条时间线用例通过。

## 5. 基线与集成验证

- [x] 5.1 改动前跑 webchat `.venv` 下 `test_grants.py` + `test_gate_hook.py`
      记录基线全绿；全部改动完成后重跑，确认更新断言后回归全绿；验证：退出码
      0、无失败用例。
- [ ] 5.2 人工在 webchat 会话内复现"读 10.0.17.23 边缘档案"：确认
      `edge_get_token` 弹确认→确认后工具返回 task_id→后续读取类 `edge_*`
      可用；同时对 `login` 验证仍为不可确认的绝对禁止；验证：端到端能读到
      档案、绝对禁止类无确认入口。
