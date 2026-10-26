## MODIFIED Requirements

### Requirement: 任务中断必须支持从断点续跑
系统 SHALL 支持"失败→与用户交互→用户补充信息→从断点继续"的编排：已成功且已落库的步骤 MUST NOT 在续跑时被重复执行；重新规划不得清空本任务已 SUCCEEDED 的阶段记录。同一建档任务内已 SUCCEEDED 的时钟／下发／召测阶段 SHALL NOT 被自动重发；跨任务或用户显式要求重发时仍可重新执行。一键与批量流程 SHALL 能仅推进未完成/失败的部分、支持分批续跑，而非每次从头重跑整条链或一次性阻塞到全部完成。续跑判定 SHALL 以服务端阶段状态与后端实时回查为权威事实源；游标仅作推进提示，游标缺失或失效时 MUST 回退到阶段状态决定跳过/推进，不得据失效游标重复已成功步骤或漏做未完成步骤。

#### Scenario: 失败后补充信息继续
- **WHEN** 某阶段失败，用户修复输入或补充信息后请求继续
- **THEN** 系统仅重跑失败的目标/阶段，已 SUCCEEDED 的设备与阶段不重复执行

#### Scenario: 同任务内已成功联通阶段不自动重发
- **WHEN** 续跑覆盖一个时钟已 SUCCEEDED 的网关
- **THEN** 系统不自动再次下发时钟召测，除非用户显式要求重发

#### Scenario: 重规划不抹除已完成阶段
- **WHEN** 续跑过程中再次调用 `plan_device_archive`
- **THEN** 已 SUCCEEDED 的阶段记录被保留并据后端实时状态合并，不导致已成功步骤重做

#### Scenario: 分批续跑不重复整链
- **WHEN** 一次大批量任务被分成多次调用推进
- **THEN** 每次调用只处理尚未完成的目标，已落库节点被跳过
- **THEN** 系统不因分批而对同一节点产生重复新建或重复审计行

#### Scenario: 游标失效仍以阶段状态兜底
- **WHEN** 调用方以过期或无效的续跑游标重新发起执行
- **THEN** 系统按保留的阶段状态与后端实时状态跳过已 SUCCEEDED 的目标，仅推进未完成/失败部分
- **THEN** 不因游标问题重复新建或对已落库设备重复写入

## ADDED Requirements

### Requirement: execute_archive_task 必须支持分批执行与进度游标
系统 SHALL 让 `execute_archive_task`（task_id 模式）支持可选 `batch_size` 与时间预算 `budget`：到达节点数或时间边界即返回，MUST NOT 因整批串行执行而被外部传输超时中断。返回体 SHALL 含进度汇总（已完成/失败/跳过计数）、续跑游标 `cursor` 与剩余量 `remaining`，供调用方分批推进；调用方不带这些参数时 SHALL 保持默认全量行为以向后兼容。分批推进 SHALL 复用服务端阶段状态作为"是否已完成"的判据，游标仅作提示。

#### Scenario: 到批次边界即返回并给出游标
- **WHEN** 调用 `execute_archive_task` 处理超过 `batch_size`/`budget` 的大批节点
- **THEN** 系统处理到边界即返回当前进度汇总、`cursor` 与 `remaining`，不继续阻塞到全部完成
- **THEN** 单次调用不因整批串行而触发客户端传输超时

#### Scenario: 携游标续跑只推进剩余
- **WHEN** 调用方以上一次返回的 `cursor` 再次调用 `execute_archive_task`
- **THEN** 系统从剩余未完成/失败目标继续，跳过已 SUCCEEDED 的节点
- **THEN** 最终全部分批完成后进度汇总为全部完成，无重复写入

#### Scenario: 缺省参数保持全量向后兼容
- **WHEN** 调用方不传 `batch_size`/`budget`/`cursor`
- **THEN** 系统按原有全量语义一次执行整条链，返回结构与既有行为兼容
