## Context

动机见 `proposal.md - Why`。约束：建档三工具现为单 `node_key`，各自动作与守卫（[edge_upsert_device](file:///e:/codeGIT/pca-mcp-server/mcp_server/edge_tools.py#L1301) / [edge_mount_device](file:///e:/codeGIT/pca-mcp-server/mcp_server/edge_tools.py#L1473) / [edge_save_device_parameters](file:///e:/codeGIT/pca-mcp-server/mcp_server/edge_tools.py#L1584)）都经 `_validate_plan_guard` + `@_tracked_action` 逐节点记录；`edge_set_device_param` 已支持逗号多目标，是批量入参的现成参照。既有主 spec 曾禁止"不可审计一键黑盒"，本 change 收敛为"批量必须逐节点可审计且等价"。

## Goals / Non-Goals

**Goals:**
- 每阶段一次批量调用替代 N 次单节点调用，且结果与逐个调用等价。
- 批量在服务端按拓扑序编排（父先子后），Skill/客户端不再写循环脚本。

**Non-Goals:**
- 不引入异步/分批游标（属 `enhance-execute-batching-resume`）。
- 不改单节点工具对外语义、字段契约、幂等键与冲突/非连坐规则。

## Decisions

**D1 扩展现有三工具加 `node_keys` 可选入参，不新增批量工具名。**
*理由*：`TOOLS` 计数与 `list_mcp_tools` 契约改动最小、客户端迁移成本低（既定偏好）。*备选*：`edge_upsert_devices` 等新工具（语义更清晰但工具面膨胀）。缺省仍走单 `node_key`；`node_keys` 给定则进入批量分支。

**D2 抽出"单节点处理核心函数"，批量分支 = 拓扑序循环调用该核心 + 汇总。**
批量绝不复制业务逻辑，只负责顺序与聚合，从根上保证"批量=逐个"。execute 一键后续复用同一核心（本 change 提供，change3 消费）。

**D3 批量返回体：默认逐节点 verdict + 汇总计数；可选 `include_details=false` 只回汇总与失败明细。**
大集合时全量逐节点回包较大，但可审计要求默认给全；按参数收敛体积。

**D4 拓扑与挂载顺序。**
按 `session.last_plan` 的 `create_batches`/items 顺序（父先子后）；挂载只对 CREATE 子节点、父 device_id 取自循环内已回写的 `key_to_device_id`；与单节点链路一致，避免"先子后父"导致挂载取不到父 id。

## Risks / Trade-offs

- [批量与逐个行为漂移] → 共享 D2 核心函数 + 三路径（批量/逐个/execute）等价性参数化测试。
- [单次批量仍可能长时间阻塞到客户端超时] → 本 change 不解决，交由 change3 分批+游标；批量集合过大时由调用方分片传入。
- [幂等键仍含 plan_id 导致重规划后不命中] → 续跑以阶段状态为准（change3 落实），批量循环内单次规划不自换 plan_id。
- [一个工具两态（单/批）语义复杂] → `node_key` 与 `node_keys` 互斥校验，二者同现或都缺省报错。

## Migration Plan

1. 抽单节点核心函数（不改对外行为，跑既有 `TestRegisteredArchiveWorkflow` 全绿）。
2. 三工具加 `node_keys` 分支 + 拓扑循环 + 汇总；补等价/非连坐/向后兼容用例。
3. 更新 server.py 三工具描述、版本 minor bump、同步契约测试。
4. 回滚：`node_keys` 为可选，不传即回到纯单节点行为。

## Open Questions

- 批量单次入参是否有硬上限（如 500）以配合 change3 的 budget——实现期与 change3 统一，不影响本规格。
