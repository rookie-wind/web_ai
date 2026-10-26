## 1. 前置与依赖

- [x] 1.1 确认 `add-batch-archive-operators` 已落地批量核心（单节点处理函数）；本 change 在其之上实施，否则 execute 建档段暂以内部循环占位并标注
- [x] 1.2 复用本会话 `execute_archive_task` 层级读取修复，跑 `TestExecuteArchiveTaskWorkflow` 全绿确认一键主链路基线

## 2. 分批执行与进度游标

- [x] 2.1 `execute_archive_task`/`_execute_full_workflow` 增加可选 `batch_size`/`budget`：到边界即停止并返回，单次不被整批串行拖到客户端超时；用例以小 `batch_size` 验证到边界即返回
- [x] 2.2 返回体新增 `summary`（done/failed/skipped）、`cursor`、`remaining`、`report_id`、`stages_requested`；缺省不传参数时保持全量一次执行且返回结构向后兼容（补缺省兼容用例）
- [x] 2.3 `cursor` 编解码（如下一待处理 node_key/阶段位置），仅作续跑提示

## 3. 以阶段状态为权威的续跑

- [x] 3.1 分批/续跑跳过判据统一走 `session.stages` + 后端实时回查（`_stage_succeeded` 按 `node_key`），时钟段修正为 node_key 键；补"游标过期/无效仍不重复新建、不漏做未完成"用例
- [x] 3.2 单次 execute 内只规划一次并复用同一 `plan_id`；跑 `test_param_validation_and_resume.py` 全绿

## 4. 削减整树重读

- [x] 4.1 在一次 execute/批量调用作用域内缓存 `getDeviceTree`，按批写入前对目标关键状态回查、跨调用/跨阶段仍重新规划；断言单任务内 `getDeviceTree` 调用次数显著下降且结果正确
- [x] 4.2 评估逐批回读：实测后端 `getDeviceListByPId` 仅 `{deviceId,deviceName,deviceAddress}`、`getDeviceTree` 无 `extInfos`，无全字段批量读端点 → 撤销批回读、保留逐节点 `getDeviceList` 回读（正确性优先，详见 design D4b）

## 5. 契约、文档与版本

- [x] 5.1 更新 `server.py` execute 描述与能力矩阵（新增 `batch_size`/`budget`/`cursor` 与返回字段）；同步工具清单/计数断言
- [x] 5.2 版本按 minor bump `mcp_server/version.json`；纳入交付则同步 `package-manifest` 与相关 skill `manifest`+`SKILL.md` frontmatter
- [x] 5.3 端到端：151 设备模板以"分块上传→read→execute 分批（多次携 cursor）→report"全程零本地脚本跑通；回归 `python -m pytest mcp_server/tests`（不含浏览器用例）全绿
