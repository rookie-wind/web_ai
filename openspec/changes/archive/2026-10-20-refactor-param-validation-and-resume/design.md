## Context

见 proposal.md - Why。当前代码把"下发数据源=实时读后端 20200002"和一批"自设必填阻塞"写进了实现，且与主规格 L77 已有的"不拦截"文字相互矛盾（代码违规遗留）。本设计给出把实现拉回"填啥配啥、报错不阻塞、断点可续跑"的技术落点，精确到函数与判据。相关既有实现坐标：

- 下发集合构造：`edge_tools._build_monitor_point_item_body`（实时读 `_read_deploy_param_body`，任一错误整批失败）。
- 计划可执行性：`archiving/engine.build_plan` L532 `executable = not has_conflict and not template.errors and not topo_errors`；L525-526 `deploy_planned/poll_planned = ... and not link_blocked_gateways`。
- profile 必填中止：`profiles/gateway_8163.py` proxyCommType 缺 → `link_blocked=True`；`profiles/meter_xlba.py` roadNo 缺 → errors + `return`。
- 写入守卫：`edge_tools` L426 `if not executable: _err("禁止执行")`。
- 重规划清进度：`edge_tools.plan_device_archive` L1193-1194 `stages.clear()` / `stage_failures.clear()`。
- 续跑幂等：`completed_actions`/`action_outcomes` 键含 `active_plan_id`，新 plan_id 令旧键失效。
- 在线判定现状：仅有通用 `edge_get_online_status`（`PATH_GET_ONLINE_STATUS`，itemId 43000002）；`getSmartEventData`/感知事件在建档 edge 侧不存在；`DeviceProfile` 基类（base.py L127-156）具备 `device_type/device_type_id/is_gateway` 类属性，适合挂按类型判定声明位。

## Goals / Non-Goals

**Goals:**
- 下发数据源改为 plan 里的 `deploy_item_body`（用户填报值），只做一致性校验。
- 自设必填全部降级为 warnings，不阻塞四操作；可执行性只由结构性冲突决定。
- 断点续跑：重规划保留已完成阶段、已成功阶段不自动重发。

**Non-Goals:**
- 不放松结构性校验（重名/孤立/不支持类型/编号冲突仍阻断）。
- 不放松召测响应结构校验（itemId/finshFlag/roadNo/dataTime/数据非空——属报错提示）。
- 不改变版本门、连接参数必要性、模板迁移工具。
- 不引入跨任务的全局幂等（跨任务仍可重发）。

## Decisions

### D1：下发数据源 = plan 的 deploy_item_body（放弃实时读 20200002）

`_build_monitor_point_item_body` 改为：从 `session.last_plan` 对应 item 取 `deploy_item_body`（profile 已按填报值算好、含 roadNo/commAddr/protocolCode 等），按 itemId=20200002 组装；**不再调用 `_read_deploy_param_body`**。一致性校验 = "待推 itemBody 的键值 ⊆ 且等于用户输入映射"，不符只报该目标。

- 删除/保留 `_read_deploy_param_body`：保留函数但下发路径不再调用（供未来"回读比对"可选诊断），避免误伤其它引用。
- "任一错误整批失败" 改为 **per-target 结果**：某目标 itemBody 缺失/非法 → 该目标标 FAILED 并跳过，其余照发；返回 per-node details（与建档链路一致）。

备选：仍读后端但"读不到回退 plan 值"——被否，违背"数据源唯一=填报值"的清晰语义，且保留了对后端记录的隐式依赖。

### D2：executable 判据收窄为"仅结构性冲突"

`build_plan` L532 改为：`executable = not plan.has_conflict and not topo_structural_errors`。其中"自设必填类" template.errors（如 proxyCommType/roadNo 缺失、连接参数以外）分流到 `plan.warnings`。`has_conflict` 仅承载重名/编号冲突/孤立/不支持类型等结构冲突。

- 连接参数（目标IP/账号）缺失：作为"必要前提"，用**独立标志** `plan.connectivity_ready=False` 表达并提示用户补充；不并入 template.errors 的 executable 判定，但 `_execute_full_workflow` 在 `connectivity_ready=False` 时停在"提示补充"而非静默。

### D3：link_blocked 降级为 warnings

- `gateway_8163`/`meter_xlba`/`registry`：`link_blocked=True` 保留为**信息位**（供 warnings），但 engine L525-526 不再据其置 `deploy_planned/poll_planned=False`——恒为 True（有监测点即规划下发/召测），缺失联通前置仅告警。
- `meter_xlba` roadNo 缺失：去掉 `errors.append(...) + return` 的中止；改为"不产 roadNo 相关下发/召测项 + 一条 warning"，继续解析该设备其余字段。

### D4：断点续跑——重规划保留已完成阶段

`plan_device_archive` 重构清进度逻辑（L1193-1196）：
- **不再无条件 `stages.clear()`**。新 plan 生成后，按"节点键 + 阶段名"把**仍与新计划一致且后端实时状态确认已完成**的 SUCCEEDED 记录合并保留；仅清除"新计划中被判定需重做（action 变化/字段变化/后端不一致）"的节点阶段。
- `plan_id` 变化导致 `completed_actions`/`action_outcomes` 旧键失效的问题：幂等键改为**不含 plan_id** 的稳定键 `f"{action}:{node_key}:{内容指纹}"`，使跨重规划的续跑仍能命中已完成结果。联通三工具的"每次都真实重发"通过 `dedup=False` 保留**跨任务/显式重发**语义，但续跑入口 SHALL 先查 `stages[node].phase==SUCCEEDED` 决定是否跳过（取向 A 的调和：同任务已成功阶段不自动重发）。

### D5：`_execute_full_workflow` 续跑语义

一键流程在既有 `auto_confirm` 之外，遵循 D4：loop 每个节点/阶段前先查该节点该阶段是否已 SUCCEEDED（来自保留的 stages），已 SUCCEEDED 则跳过并标 `skipped_reason="本任务已完成"`，只推进未完成/失败项。失败仍不 break（保留现行为），但**下次调用天然从断点继续**。

### D6：按类型分派的监测点在线判定（新工具 + profile 声明）

- **新接口常量**：`PATH_SMART_EVENT = "/dataCenter/data/get/getSmartEventData/v1"`，请求体 `{dataStTime, dataEndTime, deviceIds:[...]}`，响应 `rtnData.responseData[]`（每项含 deviceId / dataLabel / dataArray[]）。属建档侧新的 `/dataCenter` 命名空间，复用现有 `client.call`（非 comm/link 通道）。
- **profile 声明位**：`DeviceProfile` 基类加类属性 `online_check_method: str = "monitor_debug"`（值域 `"monitor_debug" | "smart_event"`）。`meter_lighting`/`meter_pdb` 覆写为 `"smart_event"`；`meter_xlba` 与基类保持 `"monitor_debug"`；未来新类型在自身 profile 声明用哪个消息，未声明即走默认。
- **新工具** `edge_check_monitor_online(task_id, node_key 或 device_id, st_time="", end_time="")`：解析节点类型 → 取 `profile.online_check_method` 分派：
  - `smart_event`：调 `getSmartEventData`，时间窗默认今天 `00:00:00`–`23:59:59`；`responseData` 中该 deviceId 存在任意 `dataArray` 记录 → `online=True`，否则 `False`（不看 dataVal 的 0/1，只看是否有上报）。
  - `monitor_debug`：复用 `edge_call_monitor_debug` 成功判据（itemId 31800006 / rtnCode=0）作为在线依据。
  - 返回 `{ok, online: bool|None, method, detail}`；profile 未声明或类型未知 → method 默认 `monitor_debug`，必要时置 `needs_user_input` 提示询问用户；**任何情况下都不 BLOCK 四操作**。
- **与 `edge_get_online_status` 的关系**：本工具承载"按类型判监测点在线"，43000002 对监测点不再是判定路径（网关在线仍可另走时钟/43000002，不在本条范围）。

### D7：冲突分“结构 / 字段”两桶，解耦 executable

现模型里 `has_conflict`/`executable` 共用单一 `conflicts` 列表，任何 profile `resolved.errors` 都进 conflicts → `executable=False` → 连坐整批，违背“已填非法值只失该目标、其余继续”。改为：

- `DryRunItem` 新增标志位 `structural: bool = True`（默认 True，保证未显式置位的历史冲突仍阻断）。
- engine 造冲突项时分类：不支持类型（L288）/网关内编号冲突（L355）/工作簿重名/孤立监测点 → `structural=True`；因 profile `resolved.errors`（字段级：已填值格式/码值映射错/feeNum 不一致）造的冲突项 → `structural=False`。
- `plan.executable` 改为：`not 任何 structural 冲突 and not template.errors and not topo_errors`（不再直接用 `has_conflict`）。字段级冲突仍进 conflicts 供展示与计数，但不拉低 executable。
- 效果：某台填错 → `executable` 仍为 True → 其它目标照写；该目标自己的 upsert/deploy 工具在写入时再次 `profile.resolve` 仍报错 → 仅该节点 FAILED。满足 5.4。
- `has_conflict` 保留原义（展示用）；需确认无其它逻辑靠 `has_conflict` 直接拦截写入（除 executable 外）。

## Risks / Trade-offs

- **[幂等键去 plan_id] 可能让"用户改模板后旧结果被复用"** → 缓解：稳定键含"内容指纹（该节点该动作的入参摘要）"，输入变化即指纹变、不命中。
- **[D3 roadNo 可空] 无分路号时召测 annexInfo 缺 roadNo** → 缓解：该目标召测项省略并告警，不阻断其它目标；用户补填后续跑补做。
- **[重规划保留 stages 复杂度] 合并逻辑易错** → 缓解：以"后端实时回查"为唯一真相源判定是否已完成，内存 stages 仅作加速，回查覆盖内存。
- **[行为翻转的既有测试] 多个测试编码了"20200002 缺失整批失败 / 必填阻塞"** → 需在 tasks 中逐条改写为新语义（参考本会话既往"联通降格"测试重写模式）。

## Migration Plan

纯代码 + 规格变更，无数据迁移。部署即生效（服务端热更新）。回滚 = revert 本 change 提交。实施顺序：先改 engine/profile 判据（阻塞解除）→ 再改下发数据源（D1）→ 再改续跑（D4/D5）→ 全量测试与规格同步。

## Open Questions

- `_read_deploy_param_body` 是否彻底删除还是保留为诊断工具（倾向保留但下发不调用）——实施时按引用情况定，不影响规格。
