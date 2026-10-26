## Why

`execute_archive_task`（task_id 一键）即便修好层级读取，仍会一次性同步阻塞跑完整批：151 设备 × 每节点多次后端往返 + 每次规划重读整棵 `getDeviceTree`（实测 5527 行 / 162.6KB 且越建越大），单批可达上千次往返、约 30 分钟，客户端调用易被传输超时中断、且无法"从断点继续"。需要让一键可分批推进、返回进度与游标、按阶段状态跳过已完成。

## What Changes

- `execute_archive_task` 复用批量建档核心（依赖 `add-batch-archive-operators`），新增可选 `batch_size` / `budget`：到节点数或时间预算边界即返回，不阻塞到全部完成；单次调用不被整批串行拖到客户端传输超时。
- 返回体新增 `cursor`（续跑游标）、`remaining`（未完成计数）与 `summary`（已完成/失败/跳过），供调用方分批推进。
- 续跑以服务端阶段状态（`session.stages` + 后端实时回查）为**权威事实源**判定跳过已 SUCCEEDED 项，`cursor` 仅作提示；游标缺失/过期时 MUST 回退到阶段状态，不得据失效游标重复已成功步骤或漏做未完成步骤。
- 在一次 execute/批量调用作用域内缓存 `getDeviceTree`、按批统一回读，削减整树重读（缓存仅单调用作用域内使用，跨调用/跨阶段仍重新规划）。

## Capabilities

### New Capabilities
<!-- 无 -->

### Modified Capabilities
- `xlpa-device-archiving-workflow`: (a) 修订"任务中断必须支持从断点续跑"，加入一键/批量分批推进、游标、以阶段状态为准的兜底；(b) 新增"`execute_archive_task` 必须支持分批执行与进度游标"。

## Impact

- 依赖：建议 `add-batch-archive-operators` 先行（本 change 的 execute 复用其批量核心，否则退化为服务端内部循环）。
- 代码：`mcp_server/edge_tools.py`（`execute_archive_task`/`_execute_full_workflow` 加 `batch_size`/`budget`/`cursor`、阶段状态续跑、调用作用域内树缓存）、`session.py`/EdgeSession（游标与阶段状态读写）。
- 契约/测试：`server.py` execute 描述与能力矩阵更新（新增参数与返回字段）；`mcp_server/tests/` 新增分批返回/游标兜底/不重复已完成/不整批超时用例。
- 版本：`mcp_server/version.json` minor bump；纳入交付则同步资源包与 skill 版本。
- 非目标：不引入常驻异步 job store/轮询作业；不改联通三工具"普通操作+仅 confirm"策略与阶段状态语义；不改字段契约。
