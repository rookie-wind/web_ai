## 1. 核心修复：拓扑解析节点去重

- [x] 1.1 修改 `mcp_server/archiving/excel_reader.py` 中的 `_parse_topology` 函数，使用 `name_to_node: dict[str, TopologyNode]` 替代 `gw_seen` 和 `mon_seen` 集合，确保每个设备名称只创建一个节点对象。验证：运行现有测试 `test_archiving_template.py::TestReaderContract` 确保基本解析仍通过。

- [x] 1.2 在 `_parse_topology` 中实现父关系保留逻辑：节点首次创建时设置 `parent_key`，后续出现时复用已有节点且不修改 `parent_key`。验证：编写测试用例，子网关先作为挂载点出现（有父），后作为挂载点管理下级设备，确认父关系未丢失。

- [x] 1.3 在 `_parse_topology` 中添加多父冲突检测：当同一设备名称在不同挂载点块下作为监测点出现且父键不同时，报告错误到 `template.errors`。验证：编写测试用例，同一监测点出现在两个不同网关下，确认报错且包含设备名称。

- [x] 1.4 确保合并单元格续行不触发多父冲突：当监测点名称已存在且当前块的挂载点与已有父键相同时，不报错。验证：编写测试用例，子网关作为挂载点出现在其父网关块下，确认不报错。

## 2. 防御性检查：排序前唯一性断言

- [x] 2.1 在 `mcp_server/archiving/engine.py` 的 `build_plan` 函数中，调用 `topological_order` 前检查 `template.nodes` 是否有重复的 `node_key`，如有则添加到 `plan.warnings`。验证：手工构造含重复节点的场景，确认计划包含警告信息。

## 3. 回读验证修复：区分根节点与未解析父ID

- [x] 3.1 修改 `mcp_server/edge_tools.py` 中的 `_readback_verify_device` 函数，当 `item.get("action") == "create"` 且 `node.parent_key` 非空但 `session.key_to_device_id.get(node.parent_key, "")` 为空时，添加 mismatch "parentId: 父设备ID尚未解析" 并返回 `(False, mismatches)`。验证：编写测试用例，CREATE动作且有父键但父ID未解析，确认验证失败而非通过。

- [x] 3.2 确保模板根节点（`node.parent_key` 为空）仍允许与后端 `-1` 等价比较。验证：运行现有测试，确认根网关的CREATE和回读验证仍通过。

## 4. 测试覆盖

- [x] 4.1 在 `mcp_server/tests/test_archiving_template.py` 中新增测试类或扩展现有类，覆盖子网关兼挂载点场景：从真实生成的Excel工作簿解析，包含子网关（如AI_test3）既作为挂载点又作为监测点挂载点的拓扑。验证：解析后节点数为10（非11），子网关的 `parent_key` 正确指向其父网关。

- [x] 4.2 添加行序变化测试：将挂载关系表的行顺序反转，确认解析结果与正序一致，节点数和父关系不变。验证：使用相同数据正序和反序解析，比较 `node_map()` 结果。

- [x] 4.3 添加多父冲突测试：构造同一监测点出现在两个不同网关下的Excel，确认解析报错且错误信息包含设备名称。验证：检查 `template.errors` 包含"多父"或"冲突"关键词。

- [x] 4.4 添加环检测测试：构造A→B→C→A的循环父关系，确认拓扑排序报错。验证：检查 `topological_order` 返回的 errors 列表非空。

- [x] 4.5 添加CREATE父ID晚绑定测试：模拟父网关和子网关均为CREATE动作，子网关验证时父ID尚未解析的场景，确认回读验证失败。验证：调用 `_readback_verify_device` 传入未解析父ID的节点，确认返回 `(False, [...])`。

- [x] 4.6 添加回读错根拒绝测试：模拟子网关CREATE后实际挂在根节点（父ID不匹配），确认回读验证失败。验证：构造后端返回 `parentId="-1"` 但模板期望非根父级的场景，确认 mismatch 列表包含 "parentId"。

## 5. 回归验证

- [x] 5.1 运行全量测试套件 `python -m pytest mcp_server/tests -v`，确认所有现有测试通过，无回归。验证：测试输出显示 "passed" 数量与修复前一致或增加，无 "failed" 或 "error"。

- [x] 5.2 验证模板生成、字段契约、端口下拉、品牌型号转换等功能未受影响：运行 `test_generator_v14.py`、`test_field_contract.py`、`test_brand_model_code.py`，确认全部通过。验证：这些测试文件的用例全部 "passed"。

- [x] 5.3 验证UPDATE/SKIP逻辑未改变：运行包含已建设备的测试场景，确认UPDATE保持现有父级、SKIP不触发挂载。验证：相关测试用例如 `test_existing_device_update`、`test_skip_device` 通过。

## 6. 文档更新

- [x] 6.1 更新 `agent_assets/skills/xlpa-device-archiving/references/excel-template-schema.md`，说明子网关兼挂载点的处理规则：设备名称全局唯一，首次出现的父关系被保留，多父冲突会报错。验证：文档中包含相关说明段落。

- [x] 6.2 在变更目录创建 `README.md`，说明本次修复的范围、不包含的内容（如存量迁移），以及验证方法。验证：README文件存在且内容清晰。
