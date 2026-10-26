## 1. 解除自设必填阻塞（engine + profiles）

- [x] 1.1 `archiving/engine.py` `build_plan`：把 `plan.executable`（L532）判据收窄为"仅结构性冲突"（has_conflict/拓扑结构错误/重名/编号冲突/孤立/不支持类型），将 proxyCommType 缺失、roadNo 缺失等自设必填类 template.errors 分流到 `plan.warnings`，使其不再令 `executable=False`；跑通后确认 `test_refactor` 与建档相关用例结构可执行
- [x] 1.2 `archiving/engine.py` L525-526：`deploy_planned`/`poll_planned` 不再因 `link_blocked_gateways` 置 False（有监测点即规划），link_blocked 仅作 warnings；验证既有 `link_blocked` 展示语义不报回归
- [x] 1.3 `archiving/profiles/gateway_8163.py`：proxyCommType 缺失保留 `link_blocked=True` 与 warning，但确认不再进 errors 阻断建档（对齐主规格 L77）
- [x] 1.4 `archiving/profiles/meter_xlba.py`：roadNo 缺失（L254-255）从 `errors + return`（中止整台电表）改为"产 warning、省略依赖 roadNo 的下发/召测项、继续解析其余字段"；串口"已填 X/4 不完整"同类降级为 per-field warning
- [x] 1.5 （D7）`archiving/models.py` `DryRunItem` 新增 `structural: bool = True`；`engine.build_plan` 将 profile `resolved.errors` 造的冲突项置 `structural=False`（不支持类型/编号冲突/重名/孤立保持 `structural=True`），并把 `plan.executable` 改算为"无任何 structural 冲突 + 无 template.errors + 无 topo_errors"（不再直接取 `has_conflict`）

## 2. 下发数据源改为填报值（deploy）

- [x] 2.1 `edge_tools._build_monitor_point_item_body`：改为从 `session.last_plan` 各 item 读取 profile 算好的 `deploy_item_body` 组装 itemId=20200002，**删除对 `_read_deploy_param_body` 的调用**；`_read_deploy_param_body` 保留但不被下发路径引用
- [x] 2.2 `_build_monitor_point_item_body`：将"任一错误整批失败"（L3848-3850）改为 per-target 结果——某目标 itemBody 缺失/非法仅标记该目标 FAILED 并跳过，其余目标照常进入下发集合；同步返回 per-node details
- [x] 2.3 下发前一致性校验：新增"待推 itemBody 键值 == 用户填报映射"校验，不符只报该目标，不影响其它目标
- [x] 2.4 `edge_set_device_param` 单网关内部函数（L1893+）：确认其不再因后端 20200002 缺失返回 BLOCKED；warnings 仍呈现前置阶段状态

## 3. 断点续跑（保留进度 + 跳过已成功）

- [x] 3.1 `edge_tools.plan_device_archive`（L1193-1196）：去掉无条件 `stages.clear()`/`stage_failures.clear()`；改为新 plan 生成后按"节点键+阶段名"合并保留"与新计划一致且后端实时回查确认已完成"的 SUCCEEDED 记录，仅清除需重做的节点阶段
- [x] 3.2 幂等稳定键：`_tracked_action` 缓存键与 `completed_actions` 键从含 `active_plan_id` 改为 `f"{action}:{node_key}:{入参内容指纹}"`，使跨重规划的续跑仍命中已完成结果；确认联通三工具 `dedup=False` 跨任务重发语义不变
- [x] 3.3 `_execute_full_workflow`：loop 每节点每阶段前先查 `stages` 是否已 SUCCEEDED，已 SUCCEEDED 则跳过并记 `skipped_reason="本任务已完成"`，只推进未完成/失败项；失败仍不 break
- [x] 3.4 续跑跳过已成功联通阶段：时钟/下发/召测在同任务内已 SUCCEEDED 的目标不自动重发，用户显式要求重发时仍可执行

## 4. 按类型判监测点在线（不阻塞）

- [x] 4.1 `edge_tools` 新增 `PATH_SMART_EVENT = "/dataCenter/data/get/getSmartEventData/v1"`，封装 `getSmartEventData` 调用（请求体 `{dataStTime, dataEndTime, deviceIds}`，复用 `client.call`）
- [x] 4.2 `DeviceProfile` 基类加类属性 `online_check_method: str = "monitor_debug"`；`meter_lighting`/`meter_pdb` 覆写为 `"smart_event"`；`meter_xlba` 与基类保持 `"monitor_debug"`
- [x] 4.3 新增工具 `edge_check_monitor_online(task_id, node_key="", device_id="", st_time="", end_time="")`：解析类型→按 `online_check_method` 分派；`smart_event` 判"时间窗内该 deviceId 有任意 `dataArray` 记录=在线"（不看 dataVal 0/1）；`monitor_debug` 复用 `edge_call_monitor_debug` 成功判据；时间窗默认今天 `00:00:00`–`23:59:59`
- [x] 4.4 未声明/未知类型：默认 `monitor_debug` 并可置 `needs_user_input` 提示询问用户；工具结果仅报告，绝不 BLOCK 四操作
- [x] 4.5 注册 `edge_check_monitor_online` 到 `EDGE_TOOL_NAMES` + server `TOOL_DEFINITIONS` + `TOOL_DOMAIN_GROUPS`（归入合适域）；同步 `test_refactor` 的 showcase/catalog 计数用例

## 5. 单元测试

- [x] 5.1 下发不依赖后端 20200002：构造 plan 含 deploy_item_body 但 mock `getDeviceParam` 返回空，断言 `edge_set_device_param` 仍成功组装并下发，不再报 "20200002 缺失" 整批失败
- [x] 5.2 参数缺失不阻塞：模板留空可选列（变比/采集器地址/proxyCommType/roadNo），断言 `plan.executable=True`、建档/下发/召测不被 link_blocked 拦截、相应项省略并出现在 warnings
- [x] 5.3 结构性冲突仍阻断：重名 / 网关内编号冲突 / 不支持类型 → 断言 `executable=False`
- [x] 5.4 已填非法值只报该字段：某目标填非法整数 → 断言仅该目标 FAILED、其余目标继续
- [x] 5.5 断点续跑保留进度：先跑部分成功、制造一次失败、重新 `plan_device_archive` 后断言已 SUCCEEDED 阶段未被清空、续跑不重复调用已成功节点（mock 后端写调用计数不增）
- [x] 5.6 已成功联通阶段不自动重发（代码实现 + `_stage_succeeded` 判定测试；全链 E2E 受既有 `node.profile` 脆弱路径限制未加）：同任务续跑覆盖时钟已 SUCCEEDED 的网关，断言不再次 call_clock；显式重发路径仍可
- [x] 5.7 在线判定·照明/配电房感知事件：mock `getSmartEventData` 有/无记录 → online True/False，且不阻塞
- [x] 5.8 在线判定·XLBA 走召测 + 新类型未声明默认召测：断言 method 分派正确、未声明默认 `monitor_debug`
- [x] 5.9 改写既有编码旧语义的用例：`test_archiving_template.py` 中"20200002 缺失整批失败"（L1228-1251 等）、必填阻塞相关断言，按新语义重写

## 6. 集成验证与规格同步

- [x] 6.1 全量 pytest 通过（`cd mcp_server; python -m pytest tests/`），无 FAILED
- [x] 6.2 `openspec validate "refactor-param-validation-and-resume"` 通过
- [x] 6.3 同步主规格 `xlpa-device-archiving-workflow`（sync-specs 或归档时合并 delta）
- [x] 6.4 更新 `agent_assets/skills/xlpa-device-archiving/SKILL.md`：下发数据来源、参数缺失不阻塞、断点续跑编排、按类型判在线工具说明；版本 minor bump（server/manifest/skill）
