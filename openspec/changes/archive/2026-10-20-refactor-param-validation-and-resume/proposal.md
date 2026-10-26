## Why

现场建档暴露四个问题：①下发把"读取后端已存在的 `20200002` 当前参数记录"当成硬前置，可电表链路从头到尾没有任何步骤创建该记录，导致下发必然整批失败；②多处"服务端自设必填/前置条件"（proxyCommType 缺失 `link_blocked`、分路号缺失即中止电表解析、任一参数缺失整批失败、任一 template.error 令 `executable=False`）会阻塞建档/时钟/下发/召测，与"sheet 是参数全集、填啥配啥、报错只提示"的原则相悖（主规格 L77 其实已要求 proxyCommType 不拦截，代码属违规遗留）。③任务中途失败后，重新规划会 `stages.clear()` 抹掉进度、一键流程每次整链重跑，无法"从断点续跑"。④监测点在线判定无按类型分派能力（照明/配电房应按感知事件、XLBA 按运维召测），`getSmartEventData` 建档侧尚未接入。

## What Changes

- **下发内容来源改为"用户填报值"**：下发直接推送 profile 依据 sheet 填写内容算出的 `deploy_item_body`，只做"配置参数与输入参数一致"的校验；不再实时读后端 `20200002`、不再因某台后端无该记录而整批失败。
- **废除自设必填阻塞**：业务参数列留空 → 跳过该项，不补默认、不中止该设备、不阻断整批；已填值的格式/映射错误 → 报错提示该字段/该目标，其它继续。`link_blocked` 不再作为下发/召测/时钟的拦截条件（降级为 warnings）。
- **可执行性闸门收窄**：`plan.executable=False` 只保留"结构性冲突"（工作簿重名、孤立监测点、不支持类型、编号冲突）；自设必填类错误一律降为 warnings 不拦截。
- **连接参数为必要前提**：目标系统 IP／账号缺失仍作为无法连后端的前提，但表现为"提示用户补充"，不是静默阻塞。
- **断点续跑**：重新规划不得抹除本任务已 SUCCEEDED 的阶段记录；一键/续跑仅推进未完成部分，同一任务内已成功的时钟/召测不自动重发（跨任务或用户显式要求仍可重发）。
- **按类型判监测点在线（不阻塞）**：新增统一在线判定工具，`照明`/`配电房` 走感知事件（`getSmartEventData`，时间窗内该 deviceId 有任意上报即在线），`XLBA` 走运维召测；判定方法由 profile 声明（`online_check_method`），新类型未声明则默认召测或询问用户；结果仅诊断报告，绝不阻塞四操作。

## Capabilities

### New Capabilities
<!-- 无新增能力，均落在既有建档工作流能力内 -->

### Modified Capabilities
- `xlpa-device-archiving-workflow`: 修改"下发和联通验证"（下发内容来源改为填报值、去 `20200002` 实时读前置）、"建档跳过必须与参数下发解耦"（去"20200002 缺失整批不下发"）、"自动建档必须先生成幂等 dry-run 计划"（重新规划保留进度）、"网关必须配置代理通信方式"（明确 link_blocked 不拦截，与既有文字对齐）；新增"业务参数缺失不得阻塞四操作"、"任务中断必须从断点续跑"与"监测点在线状态按设备类型判定且不阻塞"三条需求。

## Impact

- **代码**：`archiving/profiles/*`（去 link_blocked 必填中止、roadNo 缺失不中止；新增 `online_check_method` 声明位，照明/配电房置 `smart_event`）、`archiving/engine.py`（executable 判据收窄、link_blocked 不再置 deploy/poll_planned=False）、`edge_tools.py`（`_build_monitor_point_item_body` 改推 plan 的 deploy_item_body、去 20200002 整批失败；`plan_device_archive` 续跑不清空已完成阶段；`_read_deploy_param_body` 移除或降级；新增 `edge_check_monitor_online` 工具与 `PATH_SMART_EVENT`）。
- **规格**：`xlpa-device-archiving-workflow` 上述需求条目。
- **测试**：下发不再依赖后端 20200002、参数缺失不阻塞、断点续跑保留进度等新用例；受影响的既有守卫用例需按新语义重写。
- **不改**：结构性冲突校验（重名/孤立/不支持类型/编号冲突）、版本门、连接参数必要性、召测响应结构校验（属"报错提示"）。
