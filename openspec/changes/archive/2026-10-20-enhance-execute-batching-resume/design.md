## Context

动机见 `proposal.md - Why`。约束：`execute_archive_task`（task_id 模式）现已能在服务端跑完整 create→mount→parameter_save→clock→deploy→monitor（本会话刚修复层级读取），但仍是单次同步阻塞到底、无进度/游标，且每次规划都 `getDeviceTree` 重读整棵树（越建越大）。依赖 `add-batch-archive-operators` 提供的 `node_keys` 批量核心供 execute 复用。

## Goals / Non-Goals

**Goals:**
- 单次 execute 调用不触发客户端传输超时；大任务可分批推进、可续跑、不重复已完成。
- 显著削减整树重读，降低约 30 分钟量级耗时。

**Non-Goals:**
- 不引入常驻异步 job store / 轮询作业（同步分批 + 游标即可满足）。
- 不改阶段状态机语义、联通三工具"普通操作+仅 confirm"策略与字段契约。

## Decisions

**D1 同步分批 + 游标，而非真异步 job。**
`execute_archive_task` 处理到 `batch_size`（节点数）或 `budget`（时间）边界即返回 `cursor`+`remaining`。*理由*：无需作业生命周期/存储/并发运维，复用现有 EdgeSession 与阶段状态。*备选*：后台 job+轮询（彻底不阻塞但成本高）。

**D2 阶段状态是续跑唯一权威事实源，cursor 仅提示。**
游标编解码允许（如"下一待处理 node_key"），但**不**以游标正确性决定跳过；跳过依据 `session.stages` 的 SUCCEEDED + 后端实时回查。*理由*：plan_id 每次规划轮换、幂等键含 plan_id，游标天然易失效，兜底必须靠阶段状态。

**D3 execute 复用批量核心，保证与"逐个/批量"三路径等价。**
建档段改为调用 `add-batch-archive-operators` 的单节点核心循环；不复制逻辑。*依赖*：change2 先行。

**D4 调用作用域内缓存设备树 + 按批统一回读。**
单次全量 execute 仅 `getDeviceTree` 读 1 次（`test_execute_full_reads_tree_once` 坐实），取代客户端"每 25 个重规划"式的反复全树读；不引入跨调用树缓存以避免 stale。

**D4b 逐批回读不实现（实测后端契约）。** 后端无全字段批量读端点：`getDeviceListByPId` 仅返回 `{deviceId, deviceName, deviceAddress}`，`getDeviceTree` 不含 `extInfos`；而回读验收须逐字段比对 brand/userBigNo/decimalNum 等 `extInfos` 与 parentId/编号，仅 `getDeviceList`（44 字段+extInfos）具备。故保留逐节点 `getDeviceList` 回读，任务 4.2 的"每批一次回读"撤销——强行合并会以 3 字段冒充全字段、误判 SUCCEEDED，违反既有"逐字段回读验收"MUST。

## Risks / Trade-offs

- [游标被误当成事实源导致重复/漏做] → 明确游标仅提示、阶段状态兜底（D2 + 对应 scenario/测试）。
- [批内树缓存过时] → 仅单调用作用域，写入前回查关键状态，跨调用重规划。
- [依赖 change2 未先合入] → 本 change tasks 注明依赖顺序；缺 change2 时 execute 退化为服务端内部循环（仍可跑，只是未走批量入口）。
- [分批引入更多 plan 轮换/幂等键问题] → 单次 execute 内只规划一次并复用 plan_id；续跑靠阶段状态不靠 completed_actions 命中。

## Migration Plan

1. 待 `add-batch-archive-operators` 落地批量核心后，execute 建档段改调之。
2. 增 `batch_size`/`budget`/`cursor`/`remaining` 参数与返回（缺省=全量向后兼容）；实现阶段状态续跑与调用作用域树缓存。
3. 更新 server.py execute 描述/能力矩阵、版本；补分批/游标兜底/不超时/三路径等价用例。
4. 回滚：不传新参数即回到全量一次执行；阶段状态续跑本就存在，风险局限在 execute 分支。

## Open Questions

- `budget` 计时口径（墙钟 vs 处理节点数近似）与默认值——实现期定，不改规格。
