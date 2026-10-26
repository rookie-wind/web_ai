## MODIFIED Requirements

### Requirement: 下发和联通验证必须显式确认并归一化结果
系统 SHALL 以用户确认（confirm=true）控制下发与召测的执行；计划阶段默认纳入全部非网关节点的下发规划，Excel 任务允许标志与类型能力旗均已移除，联通类链路对监测点类型无感知。任何联通类写入执行前 MUST 取得本次目标范围的确认；阶段与计划状态以结果中的 warnings 呈现，不阻断。下发内容按会话类型取源：模板会话 SHALL 为 profile 依据工程人员在模板中实际填报值算出的 `deploy_item_body`（itemId `20200002`），服务端 MUST NOT 改为读取后端已存在的 `20200002` 当前参数记录，也 MUST NOT 因后端缺少该记录而使下发失败，下发前只做“待推送参数与用户输入参数一致”的一致性校验；免模板直连会话 SHALL 逐台先读后端当前 `20200002` 参数并原样回推，读不到或为空时 SHALL 回退到以 `getDeviceList` 档案现值组装 `20200002` itemBody 后下发，仅当组装后必需字段仍缺失才跳过该台。下发 SHALL 提示设备参数改变及审计记录副作用并二次确认。结果 SHALL 保留HTTP状态、业务码、数据项完成标志、目标标识及阶段结论；超时、未配置或未执行 MUST NOT 计作通信成功。

#### Scenario: 执行前必须逐项确认
- **WHEN** 计划包含下发或召测但用户尚未对相应阶段确认
- **THEN** 系统不调用参数设置或召测接口，并报告该阶段未执行
- **THEN** 缺少 confirm 的写入请求被服务端守卫拒绝；plan_id 仅记录不校验

#### Scenario: 下发前二次确认
- **WHEN** 用户准备执行包含合法目标的下发
- **THEN** 系统展示网关、目标监测点清单、数量与数据项 `20200002`（内容为按用户填报值算出的 itemBody）及审计副作用
- **THEN** 仅在用户确认该集合后执行；每次调用都需携带本次 confirm，下发不缓存、不复用上次确认结果

#### Scenario: 后端无 20200002 记录仍可下发
- **WHEN** 目标监测点在后端不存在 `20200002` 当前参数记录
- **THEN** 系统仍以模板填报值算出的 itemBody 组装并下发，不因"记录缺失"拒绝或整批失败

#### Scenario: 未配置或超时
- **WHEN** 后端报告代理通信方式未配置，或请求／响应等待超时
- **THEN** 系统分别报告NOT_CONFIGURED或OFFLINE_TIMEOUT，并保留失败阶段及原因
- **THEN** 超时只代表本次结果未确认，不据此断言设备永久离线，也不自动重复下发

#### Scenario: 网关可达性以时钟召测成功判定
- **WHEN** 需要判断网关是否可达，或下发开启可达门禁（`check_online`）
- **THEN** 系统以本会话该网关是否存在成功的 `edge_call_clock` 记录（回传有效 `clockTime`）为判据，命中即视为其下监测点可达并放行
- **THEN** 系统 MUST NOT 依赖通讯状态项 `43000002`（`getDeviceOnlineStatus`）判定可达；该状态项陈旧或缺失不等于设备不可达
- **THEN** 命中记录随网关级档案变更失效（分粒度大扫除），失效后需重新召测

#### Scenario: HTTP成功但业务或数据无效
- **WHEN** HTTP为200但业务码非0、完成标志非成功、返回目标不符或所需数据缺失
- **THEN** 系统不将设备通信判为成功，返回具体失败或未验证原因
- **THEN** 仅 `rtnCode == 0` 计作业务成功；HTTP 200 或 `rtnCode=200`（受理码）MUST NOT 计作成功

### Requirement: 批量档案下发必须限定明确目标集合
系统 SHALL 按会话类型确定下发数据源：模板会话使用 plan 中按工程填报值算出的 `deploy_item_body`，免模板直连会话逐台先读后端当前参数（itemId `20200002`）、读不到或为空时以 `getDeviceList` 档案现值组装 `20200002` itemBody；两者均不使用计划时快照、不区分监测点类型，且互不读取对方信息。建档SKIP、UPDATE与CREATE均可独立参与。目标集合为本次确认的显式清单，留空表示网关子树全量监测点；MUST NOT 隐式补入目标拓扑之外的设备或静默缩小集合后发送。

#### Scenario: 只下发已确认批次
- **WHEN** 用户确认某网关下的指定监测点集合
- **THEN** 实际 itemBody 与确认清单逐项一致（模板会话取填报值算出的 body，免模板会话取逐台读回的当前参数或按档案组装的 body）
- **THEN** 显式条目不属于该网关子树、节点无效或网关不在设备树中时阻止该批次并说明原因，不静默缩小集合后发送

#### Scenario: 单台参数缺失仅跳过该台
- **WHEN** 目标集合中某监测点后端无有效 `20200002` 记录（缺失、为空或读取失败）
- **THEN** 系统先回退到读取该设备 `getDeviceList` 档案现值组装 `20200002` itemBody 后下发
- **THEN** 仅当组装后必需字段（通讯地址 commAddr）仍缺失时，才跳过该台并报告设备与原因，其余目标照常下发，不连坐整批
- **THEN** 工程可选字段档案为空则留空下发，MUST NOT 以历史默认报文替代或虚构兜底值；但协议必发字段（integerNum、feeNum）SHALL 恒含并对齐页面默认（6、1）

#### Scenario: 免模板直连会话下发
- **WHEN** 会话由 `edge_get_token` 建立且未绑定任何建档模板
- **THEN** 系统按网关标识（name／identifier／deviceId）在设备树中定位网关与监测点，逐台读当前参数、读不到则按档案组装后回推
- **THEN** 该路径 MUST NOT 读取模板或计划信息，亦不因缺少模板而拒绝下发
- **THEN** 准入仍仅 `confirm`；结果含 `included`／`skipped`／`device_count` 与派发意图、持久报告

## ADDED Requirements

### Requirement: 免模板下发必须支持从平台档案组装抄表参数项
系统 SHALL 在免模板直连下发时，对无现成 `20200002` 参数的设备，读取其 `getDeviceList`（单设备）档案现值并按与模板路径一致的字段来源映射组装 `20200002` itemBody；映射 MUST 复用 profile 的字段来源单一事实源，`authParam` MUST 经下发侧归一为 12 位十六进制。对**工程可选字段**，组装 MUST NOT 虚构默认值或对缺失字段兜底；但对**协议必发字段**（`integerNum`、`feeNum`）SHALL 恒含并对齐页面默认（6、1），以免网关回 RTU DENY。

#### Scenario: 从档案映射到下发项字段
- **WHEN** 系统以档案现值组装 `20200002` itemBody
- **THEN** commAddr 取档案 deviceAddress、roadNo 取 agentNum、measurNo 取 measuredPointNum、protocolCode 取 protocolNumber、comPort 取 proxyCommPort，decimalNum／userBigNo／userSmallNo／cT／pT 等取对应 extInfos 项
- **THEN** authParam 由档案 extInfos 的 IP+端口五段串编码为 12 位十六进制，无来源时按下发侧占位规则处理

#### Scenario: 对齐页面默认字段避免 RTU DENY
- **WHEN** 组装下发项而档案 `integerNum`／`feeNum` 等页面必发字段为空
- **THEN** 系统 SHALL 恒含这些键并对齐页面默认（integerNum=6、feeNum=1），MUST NOT 因档案留空而省略该键
- **THEN** 现场实测：缺 feeNum 会被网关回 rtnCode=200/RTU DENY；补齐 feeNum=1 后 rtnCode=0/COMPLETE 下发成功

#### Scenario: 必需通讯地址缺失时阻断该台
- **WHEN** 设备档案的 deviceAddress 为空或非法，无法得出 commAddr
- **THEN** 系统跳过该台并报告"缺通讯地址、无法组装下发项"，不发送残缺报文，不影响其余目标

#### Scenario: 三类监测点统一下发
- **WHEN** 目标包含 XLBA、照明或配电房监测点
- **THEN** 系统统一按 itemId `20200002` 组装与下发，不因监测点类型走不同分支或过滤目标

#### Scenario: 组装下发后回读验证
- **WHEN** 免模板下发执行完成
- **THEN** 系统读回该设备 `20200002` 参数项确认写入结果，仅 `rtnCode == 0` 计作成功，并把该动作计入写操作审计（OPERATION TRACE）
