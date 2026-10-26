## Context

动机见 `proposal.md - Why`。相关既有事实（代码核对，非臆测）：

- 免模板下发入口 `_deploy_without_template`（edge_tools.py）现逐台调 `_read_deploy_param_body`
  读 `getDeviceParam(itemIdS=["20200002"])`；读不到/空 → 跳过该台，全空 → 整批不发出。
- `20200002` itemBody 的字段来源在 profile `meter_xlba.resolve`（L423-440）里定义：
  commAddr←address、roadNo←road_no(agentNum)、protocolCode←base.protocolNumber、
  measurNo←base.measuredPointNum、comPort←base.proxyCommPort、decimalNum/userBigNo/
  userSmallNo←ext_infos、authParam←normalize_auth_param_for_deploy 等。
- `getDeviceList`（单设备）实测返回 base + `extInfos[{propertyCode,propertyValue}]`，
  覆盖上述全部来源字段（现场 1#照明 已验证）。
- 已有只读工具 `edge_get_device_parameters` 与 `_read_device_record`（走 getDeviceList）。
- 约束：`authParam` 下发侧恒 12 位十六进制；"不虚构默认、不做档案字段兜底"是既有硬约束；
  下发不区分监测点类型；写操作已接入 OPERATION TRACE 审计。

## Goals / Non-Goals

**Goals:**
- 免模板下发在 `20200002` 为空时，用档案现值组装 itemBody 完成首写。
- 字段映射与模板路径**共用同一事实源**，避免两套实现漂移。
- 保持安全：confirm 门禁、逐台非连坐、写后回读、必需字段缺失阻断、不虚构。

**Non-Goals:**
- 不改模板会话下发路径与其数据源。
- 不新增下发工具名（在 `edge_set_device_param` 免模板分支内增强）。
- 不引入对 `43000002` 通讯状态的依赖；不改动召测/时钟/在线判定。
- 不做档案字段的默认值兜底或历史报文替代。

## Decisions

### D1 数据源两级：现成参数优先，读不到回退档案组装
`_deploy_without_template` 每台：先 `_read_deploy_param_body`（现成 20200002）；捕获"缺失/空/
异常"→ 调 `_build_deploy_body_from_archive(session, meter_id)` 用档案组装。理由：对已有参数的
设备行为完全不变（向后兼容），只对现场实测的"空参数"设备补上首写能力。
- 备选：总是从档案组装。否决——会改变"原样回推现值"的既有语义，风险更大。

### D2 字段映射抽为共享纯函数，模板与免模板同源
在 profile/field_contract 层新增 `build_deploy_item_body(source: Mapping) -> dict`，输入是
"字段名→值"的扁平来源；模板路径传 detail 派生的来源、免模板路径传档案 record 派生的来源。
两处都经它产出 itemBody 并统一 `normalize_auth_param_for_deploy`。理由：满足"单一事实源"，
避免档案组装另写一套映射导致漂移。
- 备选：在 edge_tools 里独立实现一套映射。否决——重复且易与 profile 不一致。

### D3 档案 record → 来源映射的取数
`_build_deploy_item_body_from_archive`：`getDeviceList` 单设备 record，base 取 deviceAddress/
agentNum/measuredPointNum/protocolNumber/proxyCommPort/baudRate/collectorAddress；extInfos 按
propertyCode 建字典取 decimalNum/userBigNo/userSmallNo/authParam/cT/pT… 组装成 D2 的输入。
commAddr 用 `validate_device_address` 校验，非法/空 → 该台跳过并报告（不虚构）。

### D4 缺字段策略：必需阻断、可选留空
必需项仅 commAddr（无地址无法寻址）→ 缺则跳过该台并计入 skipped，不连坐。其余字段档案为空
→ 按 profile 既有"未填即省略/留空"处理，绝不补默认。理由：与"工程参数仅提交实际填写值"一致。

### D5 类型无差别
XLBA/照明/配电房都继承 `deploy_item_id=20200002`，统一走同一组装；不按类型分支、不过滤
（沿用"下发不区分类型"）。

### D6 安全与可观测
沿用 `confirm=true` 门禁与逐台 `_call_action` 意图留痕；下发后 `_read_deploy_param_body` 回读
确认；`rtnCode==0` 才算成功；动作经 `_record_edge_action` 进入 OPERATION TRACE（请求/响应报文
已可下钻）。

## Risks / Trade-offs

- [档案字段不足以还原完整下发项] → 仅保证 commAddr 必需；其余留空即"重推当前档案状态"，
  与设备现有配置一致，不引入虚构值。若现场要求某些字段必填再单独收紧。
- [照明/配电房是否真按 20200002 下发未 100% 确证（实测其 20200002 为空）] → 组装仍按 20200002
  itemId 下发（后端按 itemId 接收）；实现期对至少一台照明/配电房做现场下发+回读验证再放行。
- [两套数据源语义混淆] → D2 同源纯函数 + 明确"先现值后档案"顺序，单测覆盖两条分支。
- [误下发风险] → confirm 门禁不变、逐台非连坐、写后回读、OPERATION TRACE 审计。

## Migration Plan

1. 先实现 D2 共享映射纯函数并让**模板路径**改调它（行为不变的纯重构，回归现有下发测试）。
2. 实现 D3 档案→来源映射 + `_build_deploy_body_from_archive`，单测覆盖字段映射与 commAddr 缺失。
3. 在 `_deploy_without_template` 接 D1 两级回退，补"空参数设备→档案组装→下发"用例。
4. 现场（10.0.17.23 G30_224357002616）对至少一台 XLBA + 一台照明/配电房做 confirm 下发+回读验证。
5. 回滚：两级回退可关回"仅读现值、读不到跳过"（保留旧行为开关或移除回退分支），模板路径不受影响。
