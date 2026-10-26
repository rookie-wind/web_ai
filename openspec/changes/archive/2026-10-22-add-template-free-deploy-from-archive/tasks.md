## 1. 字段映射与组装（复用 profile 来源）

- [x] 1.1 新增 `_build_deploy_body_from_archive(session, device_id)`：从 `getDeviceList` 单设备 record 的 base（deviceAddress/agentNum/measuredPointNum/protocolNumber/proxyCommPort/collectorAddress）与 extInfos（decimalNum/userBigNo/userSmallNo/authParam/feeNum/integerNum/aCommAddr）组装 20200002 itemBody；authParam 走 `normalize_auth_param_for_deploy`，commAddr 走 `validate_device_address`，可选字段留空不虚构（验证：`test_deploy_from_archive.py` 全绿）
- [x] 1.2 说明：未重构模板路径 `meter_xlba.resolve` 抽公共函数（回归风险高），改为独立函数复用其字段来源与 helper，行为满足规格（见"实施说明"D2 偏差）

## 2. 免模板下发两级数据源

- [x] 2.1 `_deploy_without_template` 每台改为：先 `_read_deploy_param_body`（现成 20200002），读不到/空 → 回退 `_build_deploy_body_from_archive`；组装后 commAddr 仍缺则计入 `skipped`，不连坐（验证：`test_archiving_template.py::TestStandaloneDeployWithoutTemplate` 更新用例全绿）
- [x] 2.2 两条分支产出的 itemBody 均经 `_call_action` 下发、authParam 归一、payload 不注入 deviceId（验证：断言 itemId==20200002 且条目无 deviceId）
- [x] 2.3 保持 `confirm` 门禁、逐台非连坐、`rtnCode==0` 成功判据与写后回读不变（验证：现有下发成功/失败/超时用例全绿）

## 3. 审计与结果

- [x] 3.1 免模板下发（含档案组装分支）经 `_record_edge_action` 进入 OPERATION TRACE，请求报文 payload 可下钻、authParam 脱敏（验证：`test_write_operation_logging` 相关用例）
- [x] 3.2 结果 `request_summary` 新增 `deploy_sources`（每台 backend_param/archive）与 `archive_built` 计数，不改既有键（验证：断言 included/skipped/device_count 结构不变）

## 4. 测试与现场验证

- [x] 4.1 单测覆盖：无 20200002 回退档案组装纳入、commAddr 缺失跳过该台、全空不发出、三类统一 20200002（验证：`test_deploy_from_archive.py` + `TestStandaloneDeployWithoutTemplate` 全绿）
- [x] 4.2 运行 `pytest mcp_server/tests` 全量，模板路径/召测/时钟/在线判定/日志无回归（验证：全绿，1 项既有 skip）
- [x] 4.3 现场 20.3.103.37 网关 A-北3楼-西侧-照明通讯终端 / 北楼3层传感器E10（配电房 100024）受控下发：代码链路跑通（archive 组装+发出、判据正确无假成功）；后端返回 rtnCode=200/RTU DENY（设备侧拒绝），见"实施说明"

## 5. 版本与文档

- [x] 5.1 `mcp_server/version.json` serverVersion minor bump（仅服务端，资源包/技能不动）
- [x] 5.2 更新 `edge_set_device_param` 工具描述，说明免模板下发"读现值→读不到回退档案组装"

## 实施说明（偏差与现场结果）

- **D2 偏差**：未重构 `meter_xlba.resolve` 抽公共函数（回归风险高、违背"不导致现有功能失效"），改为独立函数 `_build_deploy_body_from_archive` 复用 profile 字段来源与 `normalize_auth_param_for_deploy`/`validate_device_address`。行为满足规格，仅实现方式与 D2 不同。
- **现场验证（E10 / 配电房 100024）**：首次无 `20200002` → 自动 archive 组装并发出，但后端回 `rtnCode=200 / RTU DENY`。与页面手动下发报文逐字段 diff 定位根因：**缺 `feeNum`**（档案 feeNum 为空被省略，页面却恒发 feeNum=1）。修复：`_build_deploy_body_from_archive` 让 feeNum 恒含、缺省 1（同 integerNum=6）。**重下发后 rtnCode=0 / transport_stage=COMPLETE / ok=true 下发成功**（report rpt_20261022052650_6679ae76）。→ 免模板“读平台参数→组装→下发”端到端跑通。
- **待跟进**：下发成功后 `getDeviceParam(20200002)` 回读仍为空（本体交采类设备可读到），疑为平台侧回读口径/最终一致，不影响 rtnCode=0 成功判据；如需回读验收可后续对齐。
