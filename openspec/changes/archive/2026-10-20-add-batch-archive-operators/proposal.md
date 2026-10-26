## Why

建档/挂载/参数保存三个服务端工具都只接受单个 `node_key`，151 台设备需要约 448+ 次单节点调用；在"只用 server 工具"约束下，客户端被迫写本地 `orchestrate_archive.py` 循环代跑。下发侧的 `edge_set_device_param` 已支持逗号多网关（批量参照物），建档侧却没有等价入口。补齐批量入参即可把每阶段从 O(节点数) 次调用降到 1 次。

## What Changes

- 扩展 `edge_upsert_device` / `edge_mount_device` / `edge_save_device_parameters`：新增可选 `node_keys` 列表入参，服务端按拓扑序（`create_batches`）进程内循环，返回逐节点 verdict + 整体汇总；保留 `node_key` 单节点入参，向后兼容、不新增工具名（契约/计数不变）。
- 批量结果对个别目标失败按"非连坐"处理：字段级/单点失败只标记该节点、其余继续；结构性冲突仍阻断相关目标。
- 批量执行沿用 `plan_id` + `confirm` 守卫、`_tracked_action`/`record_stage` 逐节点审计、持久 `report_id` 与补偿清单——与逐个调用原子工具**结果等价**。
- 放宽既有"不得提供不可审计一键黑盒"约束为：**服务端可提供批量编排，但必须逐节点可审计、守卫与原子路径等价**。

## Capabilities

### New Capabilities
<!-- 无 -->

### Modified Capabilities
- `xlpa-device-archiving-workflow`: (a) 修订"自动建档必须通过原子 MCP 工具编排写入"，允许服务端批量编排但要求逐节点可审计且与原子路径等价；(b) 新增"建档写入工具必须支持 `node_keys` 批量入参并逐节点可审计"。

## Impact

- 代码：`mcp_server/edge_tools.py`（三工具加 `node_keys` 分支，抽出共享"单节点处理"核心函数供批量与 execute 复用）。
- 依赖：`execute_archive_task` 的分批/一键（见 `enhance-execute-batching-resume` change）复用本 change 的批量核心，建议本 change 先行。
- 契约/测试：`server.py` 三工具描述更新（入参新增，名称与 `TOOLS` 计数不变）；`mcp_server/tests/` 新增批量与"批量=逐个=execute"三路径等价用例。
- 版本：`mcp_server/version.json` minor bump；纳入交付则同步 `package-manifest`/相关 skill `manifest`+`SKILL.md` frontmatter。
- 非目标：不改字段契约/码值来源；不改设备名称幂等与结构性冲突/非连坐规则；不改变单节点工具既有语义；不改下发数据源语义。
