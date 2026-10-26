## Why

免模板直连会话的下发目前只能"实时读后端已存在的 `20200002` 抄表参数并原样回推"。现场
10.0.17.23 实测：网关 `G30_224357002616` 下 8 台监测点（XLBA／照明／配电房）的 `20200002`
全部为空 `[]`——设备有完整档案，但抄表参数项从未写过。于是免模板下发对这些设备逐台跳过、
整批"未发出任何请求"，只能退回模板首写。用户希望"读平台参数→下发"：直接以平台档案现值为
数据源组装下发报文，让免模板链路也能完成首次下发。

## What Changes

- **修改免模板下发的数据源**为两级：
  1. 先读现成 `20200002`（`getDeviceParam`），有值 → 原样回推（保持现状）；
  2. 读不到 / 为空 → 从 `getDeviceList`（单设备）档案现值组装 `20200002` itemBody 后下发。
- **档案→itemBody 字段映射**复用 profile 既有来源（commAddr←deviceAddress、roadNo←agentNum、
  measurNo←measuredPointNum、protocolCode←protocolNumber、comPort←proxyCommPort、
  decimalNum/userBigNo/userSmallNo/authParam/cT/pT… ← extInfos），`authParam` 经
  `normalize_auth_param_for_deploy` 归一为 12 位十六进制。
- **缺字段策略**：必需项 `commAddr`（deviceAddress）缺失时阻断该台并说明原因；其余可选字段
  档案为空则留空下发，遵循既有"不虚构默认、不做兜底拼报文"的约束。
- **不区分监测点类型**：XLBA／照明／配电房统一按 `20200002` 处理（沿用既有"下发不区分类型"）。
- 保留既有安全门禁：`confirm` 二次确认、逐台非连坐、写后回读验证、审计留痕。
- 模板会话下发路径与"读不到仅跳过"的旧语义对**已存在 `20200002`** 的设备行为不变（向后兼容）。

## Capabilities

### New Capabilities
（无）

### Modified Capabilities
- `xlpa-device-archiving-workflow`: 免模板直连下发的数据源规则由"实时读 `20200002`、读不到仅
  跳过"改为"先读现成参数、读不到则从 `getDeviceList` 档案组装"，并新增档案→`20200002`
  字段映射与必需字段缺失处理的需求。

## Impact

- 代码：
  - `mcp_server/edge_tools.py`：`_deploy_without_template` 增加"读不到→档案组装"回退；新增
    "档案 record → 20200002 itemBody" 组装函数（复用 profile 映射与 `normalize_auth_param_for_deploy`）。
  - `mcp_server/archiving/profiles/meter_xlba.py` / `field_contract.py`：抽出可复用的
    itemBody 字段来源映射（避免与模板路径重复实现、保持单一事实源）。
  - 依赖已交付的只读工具 `edge_get_device_parameters` 与 `getDeviceList(单设备)` 读能力。
- 行为：仅增强免模板下发；模板会话、召测、时钟、在线判定、操作日志不受影响。
- 现场：需重启生效；下发为写操作，走 confirm + 回读 + OPERATION TRACE 审计。
- 规格：修改 `xlpa-device-archiving-workflow` 中"批量档案下发必须限定明确目标集合"与
  "下发和联通验证必须显式确认并归一化结果"两条需求的免模板条款。
