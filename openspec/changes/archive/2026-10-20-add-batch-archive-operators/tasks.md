## 1. 抽取单节点核心（不改对外行为）

- [x] 1.1 从 `edge_upsert_device`/`edge_mount_device`/`edge_save_device_parameters` 各抽出"单节点处理"内部函数（守卫、写入、回读、`_tracked_action`/`record_stage` 语义原样保留），工具改为薄封装调用它；跑既有 `TestRegisteredArchiveWorkflow` 全绿证明行为不变

## 2. node_keys 批量入参

- [x] 2.1 `edge_upsert_device` 增加可选 `node_keys` 列表入参与互斥校验（`node_key` 与 `node_keys` 二选一）；批量分支按 `create_batches`/拓扑序循环调用 1.1 核心，返回逐节点 verdict + 汇总；单节点入参行为不变（补用例断言单/批两态与向后兼容）
- [x] 2.2 `edge_mount_device` 同样支持 `node_keys`，挂载只对 CREATE 子节点、父 `device_id` 取循环内已回写的 `key_to_device_id`；补逐节点聚合用例
- [x] 2.3 `edge_save_device_parameters` 支持 `node_keys`，按各节点 `parameter_action` 分流（save/verify），与单节点语义一致；补用例

## 3. 非连坐与可审计等价

- [x] 3.1 批量非连坐：批内字段级/单点失败仅标记该节点并给出定位原因，其余继续；结构性冲突仍阻断相关目标；参数化用例覆盖混合结果
- [x] 3.2 批量沿用 `plan_id`+`confirm` 守卫、逐节点审计、持久 `report_id` 与补偿清单；断言批量产物字段与逐个调用一致
- [x] 3.3 批量返回体支持 `include_details`（默认逐节点全量，false 时只回汇总+失败明细）；补两种形态用例

## 4. 等价性与集成测试

- [x] 4.1 参数化"三路径等价"：同一计划下"批量入参""逐个单节点""execute 一键"三者逐节点 verdict、回读结论与补偿清单一致
- [x] 4.2 规模冒烟：模拟数百 CREATE 节点，确认每阶段一次批量调用即可完成、无本地循环脚本

## 5. 契约与版本

- [x] 5.1 更新 `server.py` 三工具描述与能力矩阵（新增 `node_keys` 入参；工具名与 `TOOLS` 计数不变）；同步 `test_archive_distribution_contract` 等清单/计数
- [x] 5.2 版本按 minor bump `mcp_server/version.json`；纳入交付则同步 `package-manifest` 与相关 skill `manifest`+`SKILL.md` frontmatter 一致升版
- [x] 5.3 跑 `python -m pytest mcp_server/tests`（不含浏览器用例）全绿
