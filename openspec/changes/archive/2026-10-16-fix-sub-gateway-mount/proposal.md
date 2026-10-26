## Why

子网关设备同时作为挂载点时，拓扑解析会创建重复节点，导致父关系丢失、计划与执行视图不一致。例如 AI_test3 既是 AI_test5 的子网关，又是监测点206的挂载点，解析后出现两个同名节点，执行阶段取到无父关系的版本，导致挂载失败。此外，回读验证未区分"模板根节点"与"父ID尚未解析"，可能将未挂载误判为合法根节点。

## What Changes

- 修复 `excel_reader._parse_topology` 使用统一名称索引去重，保留先出现的父关系，检测跨块多父冲突
- 在 `engine.topological_order` 排序前增加节点唯一性断言，防止重复节点进入计划
- 修改 `edge_tools._readback_verify_device` 区分"模板根节点"与"父ID尚未解析"，当节点有父键但父ID未解析时拒绝验证，防止误判
- 新增测试覆盖：本例正/反序、合并续行、多父冲突、环检测、CREATE父ID晚绑定、回读错根拒绝
- 不修改模板列序、端口下拉、品牌型号转换、UPDATE/SKIP不迁移等现有行为

## Capabilities

### New Capabilities

（无新增能力）

### Modified Capabilities

（本次变更为纯实现修复，不改变规约层面的行为要求。现有规约已隐含设备名称全局唯一、父关系一致性的要求，本次修复确保实现符合规约。需在 `.openspec.yaml` 中设置 `skip_specs: true`。）

## Impact

- **代码文件**：
  - `mcp_server/archiving/excel_reader.py`：修改 `_parse_topology` 函数
  - `mcp_server/archiving/engine.py`：在 `topological_order` 前增加唯一性检查
  - `mcp_server/edge_tools.py`：修改 `_readback_verify_device` 的父ID验证逻辑
- **测试文件**：
  - `mcp_server/tests/test_archiving_template.py`：新增子网关去重、多父冲突、行序变化测试
  - 可能需要新增 `test_sub_gateway_mount.py` 或扩展现有测试类
- **依赖**：无新增依赖
- **系统**：不影响模板生成、字段契约、端口下拉、品牌型号转换等现有功能；不影响 UPDATE/SKIP 判定逻辑；不改变已建设备的处理方式
