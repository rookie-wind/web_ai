# 网关与监测点参数端点、证据和执行边界

> 本文区分前端保存契约、接口受理与设备完成回执。175只读核验确认地址及串口
> 保存规则，不代表本批现场已执行保存、下发或召测。历史脚本与端点列表不能替代
> 本任务的有效回执；通信验证须通过实际召测判断设备在线状态。
>
> 边缘后端基址 `http://<IP>:7500`；每个请求携带五头签名
> （appCode=5000 / token / tokenEncrypt=md5(token+loginStr+毫秒) / dateTime / userId），
> `rtnCode == 0` 仅表示接口层结果，不能单独证明设备完成。
> 常量定义见 `mcp_server/edge_tools.py` 顶部 `PATH_*`。

## 1. 按钮 → 端点总表

| UI 按钮 | 网络行为 | 端点 | itemId | 对应工具 | 验证状态 |
| --- | --- | --- | --- | --- | --- |
| 转换通讯地址 | 纯前端计算 | — | — | `convert_comm_address_tool` | 已只读核实表达式 |
| 保存网关通讯地址 | 档案参数写入 | `/devArchManager/doc/set/modifyDeviceParam/v1` | `20100024` | `edge_save_device_parameters` | 已只读核实；写后须回读 |
| 保存XLBA串口及间隔 | 档案写入 | `/devArchManager/doc/set/modifyDevice/v1` | — | `edge_upsert_device`、`edge_save_device_parameters` | 已只读核实；后者验收回读 |
| 通讯状态 | 联通类查询（未开放工具） | `/sysConfigServer/manage/get/getDeviceOnlineStatus/v1` | `43000002` | — | 状态项陈旧不作可达判据；可达以 `edge_call_clock` 回执为准 |
| 旧数据召测 | 兼容入口 | `/sysConfigServer/comm/get/callDeviceData/v1` | — | `edge_call_device_data` | 已阻断，不可替代31800006验收 |
| 参数下发 | 联通类写入 | `/sysConfigServer/comm/set/setDeviceParam/v1` | `20200002` | `edge_set_device_param` | rtnCode=0表示下发成功 |
| 时钟召测 | 联通类召测 | `/devArchManager/clock/action/callClock/v1` | 不附加猜测项 | `edge_call_clock` | 当前请求为devId；本批无现场验收 |
| 监测点召测 | 联通类召测 | 见工具中的候选实现 | `31800006` | `edge_call_monitor_debug` | rtnCode=0表示召测成功 |

## 2. 转换通讯地址（建档一步：条码 → 通讯地址）

- 175 `ParamSetGateway.convertCommAddr` 的准确表达式为
  `identifier[2:6] + "000" + identifier[7:]`，输入必须为12位数字文本。
- 示例：`224356000200` → `435600000200`，禁止另一种补零排列。
- 已由 `convert_comm_address_tool` 实现；`plan_device_archive` 在通讯地址缺失时
  按同规则自动生成，非法地址在 dry-run 报错、不写入。
- XLBA 监测点 `identifier` 通常直接等于 `deviceAddress`，无需转换。

## 3. 保存契约与只读证据

- 基础档案 `deviceAddress` 不等于参数页 `20100024.itemBody.commAddr`。
- 网关参数读取：`POST /devArchManager/doc/get/getDeviceParam/v1`，请求
  `{"deviceId":"目标ID","itemIdS":["20100024"]}`，注意 `itemIdS` 大小写。
- 保存请求含真实 `deviceId`、当前 `parentId` 和 `params` 数组；数组项含
  `deviceId`、`itemId="20100024"`、对象 `itemBody`（`commAddr`、`identifier`）。
  保留原参数其他字段；原值自计划后变化则重新计划。写后比较全部已写字段。
- XLBA用 `modifyDevice` 保存基础字段及 `extInfos`；四串口由
  `feeNum=(baud<<5)|(stop<<4)|(check<<2)|data` 编码，间隔为 `userSmallNo`。
  9600/1位/无校验/8位得到195，是计算结果，不是默认值。端口43/44不适用。
- 证据：175前端 `chunk-c0a0f302.f3e66df8.js` 模块770d中的
  `ParamSetGateway`、`ParamSetMonitorThreeT` 读写handler；
  `app.3d00bece.js` 模块f476中的API封装。该证据不证明保存后的现场结果。

## 4. 参数下发范围与门禁

- 当前签名：`edge_set_device_param(task_id, gateway_node_key, confirm=False,
  meter_node_keys="", plan_id="")`。
- 必须提供当前 `plan_id`、独立确认及逗号分隔的显式非空节点集合。
  空集合、重复、非本任务节点、实际父级不匹配均阻断；不自动扩成全网关。
- 分路号/测量点号来自已解析输入，禁止自增。档案、参数回读及网关时钟先成功。
- 即使前置均通过，20200002下发的成功判断标准为 rtnCode=0。
  模拟测试不能代替现场回执，但工具已解除发布门禁。
- 本批AI_test4两点、AI_test5一点、AI_test6两点；AI_test3无本批叶子点，不发空批次。

## 5. 时钟召测

- 当前签名：`edge_call_clock(task_id, device_id, plan_id="", confirm=False,
  allow_poll=False)`；兼容的 `allow_poll` 不替代当前计划与独立确认。
- 请求只含 `{"devId":"真实网关ID"}`，没有 `item_id` 参数。
  历史用 `deviceId` 得到NPE不能推出“缺少时钟itemId”。
- 档案及参数回读先成功；响应必须HTTP200、接口成功且
  `callTime.clockTime` 为可解析有效时间，才能记录该阶段成功。
- 空时间、结构异常、超时或无有效回执为未验证，不自动重发、轮询或校时。
  本批现场时钟验收尚未执行。

## 6. 报告口径

- 查询 `get_device_archive_task_report(task_id, report_id="")` 获取持久报告。
- 阶段使用 `NOT_RUN/SUCCEEDED/FAILED/UNVERIFIED`，列出原因与证据。
- 在线、接口受理、档案回读和设备通信完成分别报告；旧 `callDeviceData`
  不计入31800006验收。无历史有效回执只能写“无法确认”。
