# 设备建档实测手册与新设备接入流程（经验固化）

> 本文描述当前8163网关、XLBA监测点工具链及新类型接入要求。
> 历史独立脚本、只读前端契约、离线模拟与本批现场回执是不同证据。
> 不凭历史PASS宣布本批全流程成功；通信验证须通过实际召测判断设备在线状态。

## 一、当前建档编排（8163网关 + XLBA监测点）

### 0. 前置：登录与签名

- `getRSAKey` 取公钥 → RSA(PKCS1v15) 加密 `loginName`/`password`/`symmetricKey`
  → `login` 返回 `token` 与 `sysUser.id`；此后每请求带五头签名。
- 由 `EdgeDeviceClient` 封装，Skill 不直接拼签名。

### 1. 生成模板（阶段零，填表前）

- 调用 `generate_device_archive_template` 获取当前 `v15-engineer` 八表模板（每种监测点
  类型各自一张 `监测点·X` 明细 sheet），文件名、file_id和下载信息采用工具返回值，见 `platform-dict-template-generation.md`。
- 工程人员按监测点类型填「系统连接 / 挂载关系 / 网关·8163 / 监测点·XLBA / 监测点·照明 /
  监测点·配电房」中其用到的表（缺表可解析，监测点类型由所在表决定）；
  「字典 / 映射」保存该次快照，品牌型号按工作簿映射解析。

### 2. 读模板 + dry-run 计划

- `read_device_archive_template` 校验模板版本与必填 sheet/列。
- `file_id` 与服务器 `excel_path` 共用解析、计划、执行和报告，不用独立脚本替代。
- `plan_device_archive` 按名称匹配：未命中CREATE，已有监测点UPDATE，
  已有网关基本字段一致SKIP、不一致UPDATE；同名多候选或类型冲突CONFLICT。
- 绑定真实deviceId；不自动跨父迁移、不删除重建。网关20100024参数差异
  单独进入计划，基础档案SKIP不代表参数无需修正。
- 网关地址表达式为 `identifier[2:6] + "000" + identifier[7:]`，
  例如224356000200→435600000200。XLBA直接保留12位条码前导零。

### 3. 建档网关（8163，deviceTypeId=100009）

- `edge_upsert_device(task_id, node_key, plan_id, confirm=True)` 按确认计划
  CREATE/UPDATE；UPDATE必须匹配计划ID及当前父级。新建优先取返回ID，
  缺失时唯一回查，不能从位置、行号或名称猜ID。
- 网关 `proxyCommType` 缺失或未知时dry-run报错，不补任务默认值。
- `deviceAddress` 是基础档案；参数页读取20100024项，必须另行保存并回读。

### 4. 建档监测点（XLBA，deviceTypeId=100019）

- profile一次规范化，档案顶层、`extInfos`及候选20200002复用结果。
  仅保存已填写或可追溯派生字段；`cT/pT`为变比数值，不补历史密码、型号、周期。
- 更新先读原档案，显式合并已填字段与扩展项，保留未指定值；
  不依赖后端是否自动合并extInfos的假设。写后逐项回读。
- 普通串口位域保存到 `extInfos.feeNum`，抄表间隔保存到 `userSmallNo`。
  195来自6/0/0/3计算；5分钟为2，不抄表为0，零值不能丢失。
- 未知枚举、品牌型号不匹配、部分串口填写、未核实XLBA代理/IP字段均阻断。

### 5. 挂载（父先于子）+ 挂载后修正分路号（关键实测坑）

- `edge_mount_device` → `updateDeviceParent{deviceId, parentId}`
  （参数名是 **`parentId`**，传 `pid` 会被静默忽略）。
- 历史挂载行为会重置 `agentNum/measuredPointNum` 为1。
  `edge_mount_device` 仅处理本次CREATE，挂载后恢复模板明确填写的编号，
  再回读全部已写字段与父级；回读不一致不得报告已验证成功。
- **顺序铁律**：新建 → 挂载 →（工具内部）挂载后修正；**勿在挂载前单独修正分路号**。
- 历史 `_verify_live_engine.py` 的单样本结果只说明当时行为，
  本批应使用真实注册MCP工具链的模拟测试及获授权后的现场回执分别验收。

### 6. 参数验收与通信阶段

- 先完成全部档案/挂载，再逐节点调用 `edge_save_device_parameters`。
  网关保存20100024并回读，监测点验收upsert写入的基础及扩展字段。
- 然后独立确认时钟召测，当前请求只含 `devId`，必须获得合法clockTime。
  不自动轮询、重发或校时。再次变更档案/参数使旧通信证据失效。
- 下发应显式列出本次目标监测点集合（留空表示网关下模板内全量，需先展示
  清单并确认），不自动编号；内容为执行时实时读取的后端当前参数（20200002）。
  本批AI_test4两点、AI_test5一点、AI_test6两点；AI_test3不发空批次。
- 20200002下发：rtnCode=0表示下发成功。
  31800006召测：rtnCode=0表示召测成功。
  详细端点和证据见 `gateway-button-endpoints.md`。

### 7. 报告与补偿

- 副作用前持久化意图，后保存脱敏结果；报告写入失败不得报告已验证成功。
- `get_device_archive_task_report` 按所属身份查询报告，任务会话过期仍可读取
  有效持久报告；阶段显示NOT_RUN/SUCCEEDED/FAILED/UNVERIFIED及原因。
- 主流程失败不自动回滚；只有额外确认当前 `plan_id` 后才调用
  `edge_apply_compensation_plan(task_id, confirm=True, plan_id=...)`。
  只删本次新建清单，清单外后代阻断；叶子先删、失败停止、回读后才报清理结果。

## 二、新设备类型接入流程（先总结经验 → 再动文档 → 最后改代码）

> 铁律：**拓展任何新设备，先探测/总结经验并实测验证，再更新文档，最后才改代码**；
> 未实测的字段/码值一律标 `TBD`，禁止臆造。

1. **探测建档契约**（实测）：在真实/仿真环境用页面 + 抓包确认新设备类型的
   `deviceTypeId`、必填字段、`extInfos` 键集、参数设置页字段、`deviceAddress` 形态。
2. **探测按钮端点**（实测）：确认该类型的下发/召测/时钟等按钮端点与 itemId，
   登记到 `gateway-button-endpoints.md`，未命中标 `TBD`。
3. **总结为经验**：把实测结论写入本手册与端点映射文档（文档先于代码）。
4. **加 profile**：在 `mcp_server/archiving/profiles/` 新增设备 profile
   （参考 `meter_xlba.py`/`gateway_8163.py`），实现 `resolve()` 产出档案/extInfos；
   在 `registry.py` 注册；下发/召测为通用链路（执行时实时读当前参数），无类型能力位。
5. **扩模板生成器**：在 `templates/generator.py` 增该类型sheet/列/下拉，
   `excel_reader.py`、字段契约及名称关联同步扩展；只注册profile不足以接入新类型。
   虚拟网关当前为不可执行占位，不宣传为已支持；模板结构变更时递增版本。
6. **接工具编排**：如需新原子工具，在 `edge_tools.py` 定义 `PATH_*` 常量 + `@mcp.tool()`，
   并同步登记 `globals().update` 与 `EDGE_TOOL_NAMES`（保持一致性测试通过）。
7. **验证**：运行语法检查及 `pytest mcp_server/tests/`，记录实际结果，
   以真实FastMCP注册入口的模拟后端覆盖两个文件入口、门禁、回读和持久报告。
   获额外授权后才进行现场写入及页面重开验收，不能用独立脚本PASS代替。
8. **回填文档**：验证通过后，把 `TBD` 更新为实测值，标注验证出处与日期。

## 三、验证状态一览

| 结论 | 状态 | 出处 |
| --- | --- | --- |
| 地址转换及20100024保存/查询 | 已只读核实 | 175 ParamSetGateway及API封装 |
| XLBA feeNum/userSmallNo参数落点 | 已只读核实 | 175 ParamSetMonitorThreeT读写handler |
| CREATE/UPDATE、回读、阶段与报告 | 由离线回归验证 | 真实FastMCP注册工具 + 内存后端，不是现场回执 |
| 20200002下发 | rtnCode=0表示成功 | 175 setDeviceParam API |
| 31800006召测 | rtnCode=0表示成功 | 175 monitorDebug API |
| 本批保存后页面重开、时钟与通信验收 | 尚未执行 | 需要额外现场授权 |
| 本批历史时钟/下发/监测点完成情况 | 无法确认 | 缺少有效历史回执 |
