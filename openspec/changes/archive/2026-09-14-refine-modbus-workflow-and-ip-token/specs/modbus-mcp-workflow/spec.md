## MODIFIED Requirements

### Requirement: 参数来源必须优先查询并可追溯
系统 SHALL 优先通过 MCP 只读工具查询 MODBUS JSON 所需参数；当 MCP 查询命中、为空、失败、未登录或关键词不一致时，必须按不同结果类型处理，并在最终输出中标注参数来源、匹配方式和置信度。

#### Scenario: MCP 查询成功且命中
- **WHEN** MCP 查询工具返回成功且存在匹配结果
- **THEN** Skill 使用查询结果作为候选参数
- **THEN** 最终确认表必须标注来源为对应 MCP 工具名、rows 下标和字段
- **THEN** 最终确认表必须标注匹配方式和置信度

#### Scenario: MCP 查询成功但为空
- **WHEN** MCP 查询工具正常返回成功但无匹配结果
- **THEN** Skill 必须将该结果标记为查询为空，而不是查询失败
- **THEN** Skill 可以继续执行关键词变体、本地 `references` 搜索或请求用户补充
- **THEN** Skill 不得仅因空结果直接判断平台缺少该数据项

#### Scenario: MCP 查询失败
- **WHEN** MCP 查询发生网络错误、Token 错误、权限错误、参数错误或后端业务错误
- **THEN** Skill 必须向用户展示错误信息
- **THEN** Skill 不得把该错误当作数据不存在
- **THEN** Skill 不得基于失败结果自动进入新增流程
- **THEN** Skill 可以在用户知情后继续执行不依赖该查询结果的本地 references 分析

#### Scenario: 本地推荐值需要确认
- **WHEN** Skill 从本地 `references` 搜索到推荐参数
- **THEN** Skill 必须标注具体来源文件或本地来源类别
- **THEN** Skill 必须标注该值为本地候选而不是平台已存在数据
- **THEN** 未经用户确认，不得写入最终 MODBUS JSON 或同步平台

### Requirement: 权限必须限制写入行为
系统 SHALL 以 MCP 接入权限决定是否允许写入：普通用户仅可执行只读流程和本地 JSON 生成，系统级用户可在用户确认后执行写入流程；普通用户流程不得展示、询问或执行仅 system 权限可用的平台写入动作。

#### Scenario: 普通用户遇到写入步骤
- **WHEN** 普通用户执行 MODBUS 流程且缺失参数可能需要新增或同步平台
- **THEN** Skill 必须跳过写入分支
- **THEN** Skill 不得询问用户是否新增到平台或是否同步平台
- **THEN** Skill 不得调用写入工具以等待 `FORBIDDEN` 返回
- **THEN** Skill 必须说明本次仅保留本地结果，平台写入需要在服务器本机以 system 权限执行

#### Scenario: 系统级用户执行写入步骤
- **WHEN** 系统级用户执行需要写入的步骤
- **THEN** Skill 必须先展示拟调用工具、调用目的和关键入参摘要
- **THEN** 只有用户确认后才允许调用写入工具
- **THEN** system 权限不得被视为自动写入授权

#### Scenario: 有业务 Token 但无系统权限
- **WHEN** 普通用户提供有效后端业务 Token
- **THEN** Skill 仍不得执行写入工具
- **THEN** 写入权限不得仅由后端业务 Token 决定
- **THEN** Skill 必须把后端业务 Token 能力描述为平台只读查询能力，而不是平台写入能力

### Requirement: 数据项和原子标签首期只处理基础信息
系统 SHALL 将原子标签查询映射到功能项查询工具（API-E10 `GetProtocoFunctionTypeList`，MCP 工具 `get_function_type_list`），并 SHALL 在首期只查询或新增基础信息，不通过平台写入工具写入完整 MODBUS 寄存器采集配置；原子标签匹配 SHALL 优先使用平台功能项列表，平台未命中后再回退本地 references 和用户补充。

#### Scenario: 查询数据项
- **WHEN** Skill 需要匹配协议文档中的数据项中文名到原子标签或平台功能项
- **THEN** Skill 必须使用 `get_function_type_list` 查询平台功能项候选
- **THEN** Skill 必须优先在平台功能项候选中进行精确、归一、同义词或模糊匹配
- **THEN** 查询结果必须进入用户确认表

#### Scenario: 平台关键词未直接命中
- **WHEN** 平台功能项存在但协议文档关键词未直接命中
- **THEN** Skill 必须尝试关键词变体、同义词、英文标签或归一化名称匹配
- **THEN** Skill 必须将多候选或低置信候选交由用户确认
- **THEN** Skill 不得在完成匹配尝试前提示新增平台功能项或原子标签

#### Scenario: 数据项查询不到
- **WHEN** 平台功能项查询为空且本地 references 也无法确认目标原子标签
- **THEN** Skill 必须让用户补充基础信息
- **THEN** 用户补充内容必须进入最终确认表并标注来源为用户
- **THEN** 当前为 system 权限时，Skill 才能在用户确认基础信息后询问是否新增到平台功能项
- **THEN** 当前为 user 权限时，Skill 不得询问是否新增到平台

#### Scenario: 不写入完整采集配置
- **WHEN** 新增数据项基础信息
- **THEN** Skill 不得把寄存器地址、功能码、数据类型、字节序、转换表达式、枚举映射等完整 MODBUS 采集配置写入平台数据项
- **THEN** 完整采集配置仅用于本地 MODBUS JSON 生成

### Requirement: 本地 JSON 生成与平台同步必须分阶段
系统 SHALL 默认先生成本地 MODBUS JSON，并 SHALL 在用户确认本地结果后才进入可选平台同步分支；当当前 MCP 权限为 user 时，系统 SHALL 不展示平台同步确认分支。

#### Scenario: 生成本地 JSON
- **WHEN** 用户确认最终参数表和数据项映射
- **THEN** Skill 生成本地 MODBUS JSON
- **THEN** JSON 输出路径和文件名必须展示给用户

#### Scenario: 用户未确认同步平台
- **WHEN** 本地 JSON 已生成但用户未明确同意同步平台
- **THEN** Skill 不得调用 `upload_protocol_file`、`add_protocol_info`、`gen_script` 或其他平台写入工具

#### Scenario: 用户权限为 user
- **WHEN** 本地 JSON 已生成且当前 MCP 权限为 user
- **THEN** Skill 不得询问用户是否同步平台
- **THEN** Skill 必须说明平台同步未执行且需要 system 权限

#### Scenario: 用户确认同步平台
- **WHEN** 用户明确同意同步平台且当前为系统级用户
- **THEN** Skill 展示平台同步计划并请求确认
- **THEN** 用户确认后才调用平台同步相关写入工具

### Requirement: MODBUS 输出记录必须包含交付摘要与阶段化结构
系统 SHALL 在 MODBUS 协议转换完成时输出结构化交互记录或摘要，包含结论摘要、阶段化过程、最终确认表、产物清单、测试清单、未验证项、续跑摘要、变更影响和下一步建议。

#### Scenario: 输出结论摘要
- **WHEN** MODBUS 协议转换流程完成或阶段性结束
- **THEN** 系统必须在输出开头给出结论摘要
- **THEN** 摘要必须说明 MCP 接入状态、后端业务 Token 状态、JSON 是否生成、是否同步平台、关键风险或待处理项

#### Scenario: 使用阶段化命名
- **WHEN** 系统整理协议转换过程
- **THEN** 系统必须使用“阶段一/阶段二/阶段三”描述过程
- **THEN** 系统不得使用容易与软件版本混淆的“版本交互一/版本交互二”作为阶段标题

#### Scenario: 输出续跑摘要
- **WHEN** MODBUS 流程阶段性结束且仍有未确认项或后续动作
- **THEN** 系统必须列出已确认实体、已确认点位、待确认点位、本地 JSON 状态和平台同步状态
- **THEN** 系统必须给出用户可执行的续跑动作，例如继续确认点位、跳过未确认点位、重新匹配原子标签或在 system 权限下同步平台

#### Scenario: 输出变更影响提示
- **WHEN** 用户选择候选原子标签、补充新标签或确认平台新增内容
- **THEN** 系统必须说明该选择对 `taskList`、`labelList`、本地 JSON 和可选平台同步的影响
- **THEN** 系统必须说明该选择是否会触发平台写入以及需要的权限

## ADDED Requirements

### Requirement: 原子标签匹配必须支持批量确认与置信度
系统 SHALL 将 MODBUS 点位的原子标签匹配结果按批量表格展示，并 SHALL 为每个点位标注平台功能项候选、本地候选、用户补充状态、置信度、来源和建议动作。

#### Scenario: 高置信平台候选
- **WHEN** 平台功能项候选与协议文档点位形成高置信匹配
- **THEN** Skill 可以将该候选作为默认建议
- **THEN** 该候选仍必须进入最终确认表并标注为平台功能项来源

#### Scenario: 中低置信或多候选匹配
- **WHEN** 同一协议点位存在多个平台候选、本地候选或低置信匹配
- **THEN** Skill 必须批量展示候选差异
- **THEN** Skill 必须由用户确认最终采用哪个标签或选择用户补充

#### Scenario: 无候选匹配
- **WHEN** 平台和本地 references 都没有可用候选
- **THEN** Skill 必须请求用户补充基础信息
- **THEN** Skill 不得编造英文标签、单位或业务含义

### Requirement: 平台查询结果必须避免重复请求
系统 SHALL 在同一 MODBUS 转换会话中复用已获取的平台功能项候选，避免对每个点位重复调用相同范围的功能项查询。

#### Scenario: 同一批点位匹配
- **WHEN** Skill 已获取平台功能项列表
- **THEN** 后续点位匹配优先复用该列表
- **THEN** Skill 只有在查询条件变化或用户要求刷新时才重新调用 `get_function_type_list`
