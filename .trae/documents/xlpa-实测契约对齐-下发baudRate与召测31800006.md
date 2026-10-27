# 对齐实测契约：下发补齐 baudRate 与召测修正 31800006

## Context（背景）

探测报告《非电数据下发与运维召测接口探测报告》（2026-09-28，实测 10.0.17.23≡20.2.96.2）给出两个与现有
MCP 契约不同的**实测**结论，用户已确认「**使用实测报告**」为权威，方向：
1. **下发**：实测 itemBody 含 `baudRate` 字段（14 字段），当前 MCP 缺（13 字段）。
2. **召测**：实测应为 `itemId="31800006"` 且 body 结构为 `{deviceId, dataItem:{itemId, annexInfo}}`，
   当前 MCP 用 `31800008` 且结构为顶层 `{deviceId, annexInfo}`。
3. **全量下发**：实测全量 itemBody 含网关主表行（roadNo=2），用户要求按实测口径纳入（纠正之前误选）。

### 已确认冲突（重要：现有测试锁定旧契约，改动必须同步测试）
- `_DEPLOY_ITEM_FIELDS` 仅 13 字段，测试断言 `baudRate not in _DEPLOY_ITEM_FIELDS`、
  且 itemBody `baudRate not in body`（test_archiving_template.py#1497-1503、1552-1562；test_brand_model_code.py#116）。
- `MONITOR_DEBUG_ITEM_ID = "31800008"`；`_MONITOR_DEBUG_PROTOCOL = "31800008"`；
  `check_item_id_contract` 默认 `31800008`；一批测试锁定 `monitor_debug_protocol == "31800008"`
  及「31800006 不计为 31800008 成功证据」（test_field_contract.py#221；test_archiving_template.py#1673-1679、3059-3063）。
- 门禁：`_communication_contract_error(monitor_debug)` 现返回 BLOCKED；测试锁定门禁保持零发送（#3764）。

### 硬约束
- 禁止影响现有功能 / 禁止引入新问题：改动需**随之同步更新全部锁定契约的测试**，否则测试失败。
- 禁止瞎编：网关主表行字段语义报告未说明，**不臆造**；下方标注为待补实测方可实施。

## 方案 A（可立即实施，证据充分）
### A1. 下发补齐 baudRate
- `mcp_server/archiving/field_contract.py` `_DEPLOY_ITEM_FIELDS`（约 L129）新增：
  `"baudRate": "波特率（string）"`。
- `mcp_server/archiving/profiles/meter_xlba.py` item_body 构建（约 L374）在
  `item_body = {"roadNo": road_no, "commAddr": address}` 之后补 `"baudRate": ""`
  （对齐实测：大多为空串；baudRate 不写档案顶层，与现有 `base_payload["baudRate"]=""` 一致，仅显式发空清除残留）。
- 同步更新锁定测试：
  - test_archiving_template.py#1498-1503、1552-1562：改断言为 `len(_DEPLOY_ITEM_FIELDS) == 14` 且含 `baudRate`。
  - test_brand_model_code.py#116：改为 `assert "baudRate" in body`、值 `""`。
  - 新增断言：`detail 含 baudRate 时 item_body["baudRate"]==""`（不写入下发值，仅占位）。

### A2. 召测改为 31800006 + dataItem 结构（保持门禁）
- `mcp_server/edge_tools.py`
  - `MONITOR_DEBUG_ITEM_ID`（L67）`"31800008"` → `"31800006"`。
  - `edge_call_monitor_debug` payload（L1980-1986）改为实测结构：
    ```python
    payload = {
        "deviceId": device_id,
        "dataItem": {
            "itemId": MONITOR_DEBUG_ITEM_ID,
            "annexInfo": {"roadNo": road_no, "tag": str(tag or "").strip()},
        },
    }
    ```
  - 更新注释与门禁文案：L62、L719（`monitor_debug` 理由改为「31800006 请求结构已按实测，但成功完成回执尚未核实，
    BLOCKED」）、L1764、L1778、L1904 的「31800008」表述改为「31800006/实测结构」。
  - 注意：**保持 `_communication_contract_error("monitor_debug")` 返回 BLOCKED**（报告实测真 itemId 31800006 仍返回
    「不支持」、rtnData=null，成功回执未验证，故不解门禁）。
- 顶层契约/能力描述同步：
  - `field_contract.py` `_MONITOR_DEBUG_PROTOCOL`（L48）→ `"31800006"`；L477 能力树随之。
  - `archiving/time_validator.py` `check_item_id_contract` 默认参数（L163）`"31800008"` → `"31800006"`。
  - `server.py` L262、L271、L1563 描述中的「31800008」改为「31800006/实测结构」。
  - `archiving/stage_orchestrator.py` L4、L249-251 的 `31800008`/`new_evidence_item` → `31800006`。
- 同步更新锁定测试：
  - test_field_contract.py#221：`monitor_debug_protocol == "31800008"` → `"31800006"`。
  - test_archiving_template.py#1673-1679、2819、3099、3147 等断言 itemId=31800008 处改为 31800006；
    #3059-3063 `check_item_id_contract` 语义更新（31800006 现为契约值，31800008 不再为真）；
    #3764 门禁零发送测试保留（仅断言 BLOCKED 依旧成立）。

## 方案 B（需先补实测方可实施 —— 目前是阻塞项）
### B1. 全量下发含网关主表行（roadNo=2）
- 阻塞原因：`gateway_8163.py` `supports_deploy = False`，不产出 `deploy_item_body`；`_build_gateway_item_body`
  （edge_tools.py#2740）显式「排除网关」只收集电表。实测全量 itemBody 的网关行
  `{roadNo:2, commAddr:网关deviceAddress, protocolCode:2, feeNum:4, integerNum:6, decimalNum:2,
   authParam:"EEEEEEEEEEEE", collCommAddr:"000000000000", userBigNo:0, userSmallNo:1}` 仅一条样本，
  **其字段映射/生成规则报告未说明**，无法从模板字段可靠推导，硬编码=瞎编。
- 前置（待补）：
  1. 从 `_probe/*` 证据或补一次探测，拿到网关行各字段（roadNo、protocolCode、feeNum、authParam、collCommAddr、
     userBigNo 等）相对网关模板输入字段的映射规则；或确认网关行的这些值在网关建档详情中可直接取得。
  2. 为 `gateway_8163.py` 增加网关自身 `deploy_item_body`（roadNo=网关 agentNum/2、commAddr=网关 deviceAddress
     等），`supports_deploy = True`。
  3. `_build_gateway_item_body` 在全量下发时把网关自身行置于 itemBody 首位（roadNo=2），再接各电表行。
  4. 新增测试锁定：全量 itemBody 首条为网关行、字段与实测一致。
- 在 B1 前置未满足前，**预期上不实施**；交付时若条件具备再进入。

## 验证方式
1. `python -m pytest mcp_server/tests -q`，全量回归；确认方案 A 改后的测试全绿、无新增失败。
2. 针对 A1/A2 新增示例用例：resolve 电表 detail 产出 itemBody 含 `baudRate==""`；召测 payload 形状为
   `{deviceId, dataItem:{itemId:"31800006", annexInfo}}`；`check_item_id_contract("31800006") is True`。
3. 确认门禁语义：`edge_call_monitor_debug` 在无成功的实测成功回执证据下仍返回 `stage_state=BLOCKED`、
   `contract_unverified=True`（方案 A 不改门禁逻辑，仅改文案与 itemId/结构）。
4. 弹出 MCP `list_mcp_tools` 能力描述与 `interface_capabilities["monitor_debug_protocol"]` 均显示 31800006。
5. B1 仅在补充探测并确认字段规则后进入；未确认前保持「只发电表」现状不回退。

## 涉及文件
- `mcp_server/archiving/field_contract.py`
- `mcp_server/archiving/profiles/meter_xlba.py`
- `mcp_server/edge_tools.py`
- `mcp_server/archiving/time_validator.py`
- `mcp_server/server.py`
- `mcp_server/archiving/stage_orchestrator.py`
- （B1）`mcp_server/archiving/profiles/gateway_8163.py`
- 测试：`mcp_server/tests/test_archiving_template.py`、`test_field_contract.py`、`test_brand_model_code.py` 等