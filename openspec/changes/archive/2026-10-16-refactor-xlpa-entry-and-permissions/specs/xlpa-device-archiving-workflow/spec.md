## Purpose

定义 XLPA 自动建档工作流的用户可见行为，使 Excel 任务模板、边缘建档后端、设备类型 profile、幂等计划、补偿清理、下发和联通验证形成可扩展、可审计、可复跑的建档能力。

## ADDED Requirements

### Requirement: 自动建档必须使用任务级 Excel 模板
系统 SHALL 使用一个自包含 Excel 工作簿描述一次边缘建档任务，工作簿至少包含任务配置、拓扑总览、网关明细、XLBA 电表明细和字典说明。

#### Scenario: 读取任务配置
- **WHEN** 用户提供自动建档 Excel 工作簿
- **THEN** 系统必须从任务配置 sheet 读取边缘后端地址、loginName、password、请求超时、联通超时、是否允许下发和是否允许召测验证
- **THEN** password 可以明文存在于 Excel 输入中
- **THEN** 系统在日志、报告、工具返回和错误摘要中不得主动输出 password 明文

#### Scenario: 读取拓扑总览
- **WHEN** 系统解析拓扑总览 sheet
- **THEN** 系统必须读取节点键、父节点键、设备名称、设备类型、deviceId、条码 identifier、通讯地址和分路号 roadNo
- **THEN** 首次新建设备允许 deviceId 为空
- **THEN** 节点键必须在当前工作簿内唯一，并用于首跑建树、补偿清单和结果映射

#### Scenario: 读取类型明细
- **WHEN** 工作簿包含网关明细或 XLBA 电表明细
- **THEN** 系统必须按节点键将明细行关联到拓扑总览中的节点
- **THEN** 系统必须按对应设备类型 profile 校验必填字段、字段来源和数据项结构

### Requirement: 自动建档必须支持可扩展设备 profile
系统 SHALL 通过设备类型 profile 描述不同 deviceTypeId 的基础字段、派生字段、extInfos 字段、data item 字段、必填校验和下发结构，首期 SHALL 支持 8163 网关和 XLBA 电表。

#### Scenario: 解析已支持设备类型
- **WHEN** Excel 中的设备类型为 8163 网关或 XLBA 电表
- **THEN** 系统必须将设备类型解析为对应 deviceTypeId
- **THEN** 系统必须使用对应 profile 生成校验规则、建档 payload 和可选下发 payload

#### Scenario: 遇到未支持设备类型
- **WHEN** Excel 中出现首期未支持的设备类型或 deviceTypeId
- **THEN** 系统必须报告不支持的设备类型、节点键和建议补充 profile
- **THEN** 系统不得自行猜测该类型需要的字段或 data item 结构

#### Scenario: 虚拟网关暂未实现
- **WHEN** Excel 中出现虚拟网关类型
- **THEN** 系统必须明确提示虚拟网关 profile 留作二期实现
- **THEN** 系统不得把虚拟网关当作 8163 网关或 XLBA 电表处理

### Requirement: 通讯地址必须按已确认规则生成和校验
系统 SHALL 支持从条码 identifier 生成 12 位 deviceAddress，转换规则为去掉条码第 1、2、7 位后在中间补 3 个 0；系统 SHALL 校验所有写入的 deviceAddress 为 12 位。

#### Scenario: 根据条码生成通讯地址
- **WHEN** 节点提供条码 identifier 且未显式提供通讯地址
- **THEN** 系统必须使用已确认规则生成 deviceAddress
- **THEN** 对于 identifier `224356000099`，系统必须生成 `435600000099`

#### Scenario: 通讯地址格式非法
- **WHEN** Excel 显式提供的 deviceAddress 不是 12 位
- **THEN** 系统必须在 dry-run 阶段报告格式错误
- **THEN** 系统不得把非法 deviceAddress 写入边缘后端

### Requirement: 网关必须配置代理通信方式
系统 SHALL 将 proxyCommType 作为网关设备的必填前置通信字段；系统 SHALL 优先使用网关明细中的值，其次使用任务配置中的默认值，二者都缺失时必须阻止联通类操作。

#### Scenario: 网关明细提供 proxyCommType
- **WHEN** 网关明细行提供代理通信方式 proxyCommType
- **THEN** 系统必须在网关建档或更新时写入该字段
- **THEN** 系统必须在 dry-run 输出中展示该字段已配置

#### Scenario: 使用任务默认 proxyCommType
- **WHEN** 网关明细未提供 proxyCommType 但任务配置提供默认 proxyCommType
- **THEN** 系统必须在计划中标注使用任务默认值
- **THEN** 系统必须在执行时将该默认值写入网关档案

#### Scenario: proxyCommType 缺失
- **WHEN** 网关缺少 proxyCommType 且任务配置没有默认值
- **THEN** 系统必须在 dry-run 阶段报错
- **THEN** 系统不得执行通讯状态查询、召测或参数下发

### Requirement: 自动建档必须先生成幂等 dry-run 计划
系统 SHALL 在任何写入前生成 dry-run 计划，计划必须基于现有设备树、Excel 节点、deviceId 和 roadNo 判断创建、更新、跳过和冲突。

#### Scenario: 首次新建设备
- **WHEN** Excel 节点没有 deviceId
- **THEN** 系统必须使用节点键和父节点键规划建档顺序
- **THEN** 系统必须在执行报告中输出节点键到新 deviceId 的映射

#### Scenario: 复跑已存在设备
- **WHEN** Excel 节点提供 deviceId 且该 deviceId 与 roadNo 在目标父网关下可匹配
- **THEN** 系统必须将该节点视为可复跑对象
- **THEN** 系统必须比较 profile 相关字段并生成跳过或增量更新计划

#### Scenario: 幂等冲突
- **WHEN** 同一 deviceId、roadNo、父节点或设备类型之间存在无法自动判定的冲突
- **THEN** 系统必须在计划中列出冲突项和可选处理方式
- **THEN** 系统不得在用户确认前执行写入

### Requirement: 自动建档必须通过原子 MCP 工具编排写入
系统 SHALL 提供原子 MCP 工具，由 XLPA Skill 按 dry-run 计划、用户确认和阶段结果编排执行，不得只提供不可审计的一键黑盒建档工具。

#### Scenario: 原子工具覆盖建档链路
- **WHEN** 实现自动建档能力
- **THEN** 系统必须提供解析模板、生成计划、建档/更新设备、挂载设备、读取设备、删除设备、参数下发、通讯状态查询、召测和补偿清理所需的原子能力
- **THEN** 每个写入类工具必须返回动作、关键入参摘要、返回码、返回消息和是否成功

#### Scenario: Skill 编排写入
- **WHEN** XLPA Skill 执行自动建档
- **THEN** Skill 必须先展示 dry-run 计划
- **THEN** Skill 必须在用户确认后才调用写入类原子工具
- **THEN** Skill 必须在阶段结束后输出可复跑摘要和产物清单

### Requirement: 下发和联通验证必须显式确认并归一化结果
系统 SHALL 将参数下发、通讯状态查询和召测视为联通类操作，支持配置超时、离线归一化和副作用提示；下发必须额外提示审计日志副作用并二次确认。

#### Scenario: 下发默认关闭
- **WHEN** Excel 未明确允许下发
- **THEN** 系统不得调用 setDeviceParam
- **THEN** 系统必须在结果中说明参数下发未执行

#### Scenario: 下发前二次确认
- **WHEN** Excel 允许下发且 dry-run 计划包含 setDeviceParam
- **THEN** Skill 必须展示目标网关、目标电表数量、itemId、关键 itemBody 摘要和写审计日志提示
- **THEN** 用户确认后才允许调用下发工具

#### Scenario: 联通类三态结果
- **WHEN** 通讯状态查询、召测或下发返回代理通信方式未配置
- **THEN** 系统必须归一化为 NOT_CONFIGURED
- **WHEN** 联通类操作阻塞至客户端超时
- **THEN** 系统必须归一化为 OFFLINE_TIMEOUT
- **WHEN** 联通类操作返回成功业务码
- **THEN** 系统必须归一化为 OK

### Requirement: 自动建档必须生成补偿清单并支持确认式清理
系统 SHALL 在执行写入时记录本次新建、更新和挂载的动作；当流程失败或用户要求清理时，系统 SHALL 支持按补偿清单删除本次新建设备。

#### Scenario: 生成补偿清单
- **WHEN** 自动建档执行了创建、更新或挂载动作
- **THEN** 系统必须生成结构化补偿清单
- **THEN** 补偿清单必须至少包含本次新建设备的节点键、deviceId、设备名称和 deleteDevice 请求体

#### Scenario: 按补偿清单删除本次新建设备
- **WHEN** 用户明确确认按补偿清单清理本次新建设备
- **THEN** 系统必须按叶子到父节点的顺序调用 deleteDevice
- **THEN** 系统必须回读设备树确认本次新建设备已不存在
- **THEN** 系统不得删除补偿清单之外的既有设备

### Requirement: 自动建档产物清理必须保留可复用资产
系统 SHALL 仅删除后续不会复用的临时产物，并 SHALL 保留输入、结果、审计、补偿、模板和可复用缓存。

#### Scenario: 流程结束清理临时产物
- **WHEN** 自动建档流程结束
- **THEN** 系统可以删除临时解压目录、一次性请求 dump、调试残留和无复用价值的中间文件
- **THEN** 系统不得删除用户输入 Excel、生成模板、dry-run plan、执行报告、补偿清单或可复用字典缓存

#### Scenario: 清理敏感临时产物
- **WHEN** 临时产物包含 token、password 或登录响应
- **THEN** 系统必须优先删除该临时产物或在保留前脱敏
- **THEN** 系统不得将敏感临时产物打入 Agent 资源包
