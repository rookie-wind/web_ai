# fix-sub-gateway-mount

修复子网关兼挂载点时同名节点重复创建导致父关系丢失的问题。

## 问题

当子网关设备同时出现在两种角色中（既作为某网关的子设备，又作为其他监测点的挂载点）时，
`excel_reader._parse_topology` 使用 `gw_seen` / `mon_seen` 双集合分别跟踪，
导致同名设备被创建为两个不同的节点对象。`node_map()` 后写覆盖使计划和执行阶段取到
不同对象，父关系丢失。

此外，`_readback_verify_device` 未区分"模板根节点"与"父ID尚未解析"，
可能将未挂载误判为合法根节点。

## 修复范围

| 文件 | 改动 |
|------|------|
| `mcp_server/archiving/excel_reader.py` | `_parse_topology` 使用 `name_to_node` 统一字典去重，保留首次父关系，检测多父冲突 |
| `mcp_server/archiving/engine.py` | `build_plan` 排序前增加节点唯一性防御检查 |
| `mcp_server/edge_tools.py` | `_readback_verify_device` 区分模板根节点与父ID未解析 |
| `mcp_server/tests/test_archiving_template.py` | 新增 `TestSubGatewayMount` 测试类（6 个用例） |

## 不包含

- 存量子网关的自动迁移（如已错误挂载的 AI_test3 需独立处理）
- 模板列序、端口下拉、品牌型号转换等现有功能的修改
- UPDATE/SKIP 判定逻辑的变更
- 挂载后参数保存触发条件的变更

## 验证

- 新增 6 个测试：子网关去重、行序反转、多父冲突、环检测、父ID未解析拒绝、错根拒绝
- 全量回归：486 passed, 1 skipped, 0 failed
- 不影响模板生成、字段契约、端口下拉、品牌型号转换、UPDATE/SKIP 等现有功能
