# modbus-mcp-workflow Specification

## Purpose
定义 MODBUS 协议转换 Skill 在首期如何以现有 `modbus-conversion` 流程为基准，编排规约管理 MCP 原子工具、本地参考资料、权限控制、本地 JSON 生成与可选平台同步，确保所有参数来源和写入行为可验证、可追溯、可由用户确认。

## Requirements

### Requirement: 首期范围限定为 MODBUS Skill
系统 SHALL 仅在首期完善 MODBUS 协议转换 Skill 的 MCP 工具编排能力，并 SHALL NOT 在本次变更中实现 HTTP/MQTT 协议转换 Skill 的 MCP 工具限制或完整流程。

#### Scenario: 使用 MODBUS Skill 基准流程
- **WHEN** 开始首期方案实现
- **THEN** 系统以 `.trae/skills/modbus-conversion/SKILL.md` 的现有 MODBUS 流程作为流程基准
- **THEN** 系统使用 `规约管理MCP服务化Spec.md` 中定义的规约管理 MCP 原子工具作为实际工具来源

#### Scenario: 排除 HTTP/MQTT 首期范围
- **WHEN** 首期方案生成或实现任务拆解
- **THEN** 不得要求修改 HTTP/MQTT Skill 的完整 MCP 编排流程
- **THEN** 不得实现 HTTP/MQTT 专属 MCP 工具白名单策略

### Requirement: Skill 必须声明 MCP 工具用途
MODBUS Skill SHALL 明确列出会调用的 MCP 工具、工具类型、调用目的、触发条件和结果用途，不得继续使用示例性高阶 MCP 工具作为实际实现依据。

#### Scenario: 废弃示例高阶工具名
- **WHEN** 更新 MODBUS Skill 的 MCP 工具章节
- **THEN** 不得将 `analyze_modbus_protocol`、`analyze_type_definitions`、`generate_modbus_config`、`validate_config_rules`、`save_conversion_config` 作为实际 MCP 工具调用
- **THEN** 必须改为引用规约管理 MCP 服务化 Spec 中的原子工具

#### Scenario: 工具用途可验证
- **WHEN** 用户或实现者阅读 MODBUS Skill 文档
- **THEN** 能明确看到每个 MCP 工具用于获取或写入哪类参数
- **THEN** 能明确看到该工具属于探测、登录、只读、条件写入或平台同步中的哪一类

### Requirement: 登录信息与 Token 必须分层隔离
MODBUS Skill SHALL 在 XLPA 入口下区分 MCP 接入 Token、云端后端业务 Token 和边缘建档任务凭据；MCP 接入 Token 仅用于连接 MCP endpoint，云端业务 Token 仅用于云端规约平台 API，边缘建档凭据仅用于 `:7500` RSA 登录。

#### Scenario: 用户提供登录信息
- **WHEN** 用户提供 `phoneNum` 和 `code`
- **THEN** Skill 调用 `login(phoneNum, code)` 获取云端后端业务 Token
- **THEN** 后续云端后端 API 类 MCP 工具使用该业务 Token
- **THEN** Skill 必须根据本地超级账号配置判断云端平台写权限

#### Scenario: 用户未提供登录信息
- **WHEN** 用户未提供 `phoneNum` 或 `code`
- **THEN** Skill 必须告知用户后续所有云端参数来源仅使用本地 `references` 目录或无需业务 Token 的来源
- **THEN** Skill 不得调用需要云端后端业务 Token 的后端 API 类 MCP 工具

#### Scenario: Token 不得混用
- **WHEN** Skill 调用 MCP Server、云端规约平台或边缘建档后端
- **THEN** MCP 接入 Token 仅用于连接 `/mcp` 端点
- **THEN** 云端业务 Token 仅用于调用云端规约平台 API
- **THEN** 边缘建档 loginName/password 仅用于边缘 `:7500` RSA 登录
- **THEN** 任一 Token 或凭据不得替代另一 Token 或凭据使用

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

### Requirement: MODBUS 字段映射必须明确
系统 SHALL 使用已确认字段映射生成 MODBUS JSON：`classNum` 来源于大类编号，`modelNum` 来源于设备类型管理的 `deviceTypeCode` 字段。

#### Scenario: classNum 映射
- **WHEN** Skill 需要生成 MODBUS JSON 的 `classNum`
- **THEN** Skill 必须从大类查询结果的大类编号或用户确认的本地来源值中取值
- **THEN** Skill 不得仅凭设备名称自行推断未验证编号

#### Scenario: modelNum 映射
- **WHEN** Skill 需要生成 MODBUS JSON 的 `modelNum`
- **THEN** Skill 必须从设备类型管理查询结果的 `deviceTypeCode` 字段或用户确认的本地来源值中取值
- **THEN** 如果查询结果没有 `deviceTypeCode` 或该字段为空，Skill 必须回退本地来源或询问用户

### Requirement: 权限必须限制写入行为
系统 SHALL 使用云端业务登录账号和本地超级账号配置决定云端平台写入是否可用；MCP 接入 Token、localhost 或本机 IP 不得单独授予云端平台写入能力。边缘建档写入能力 SHALL 由自动建档 Excel 中的边缘任务凭据单独决定，并仍需用户确认。

#### Scenario: 普通用户遇到写入步骤
- **WHEN** 用户执行 MODBUS 流程且缺失参数可能需要新增或同步云端平台，但当前业务账号未命中超级账号表
- **THEN** Skill 必须跳过云端平台写入分支
- **THEN** Skill 不得询问用户是否新增到云端平台或是否同步云端平台
- **THEN** Skill 不得调用云端写入工具以等待 `FORBIDDEN` 返回
- **THEN** Skill 必须说明本次仅保留本地结果，云端平台写入需要超级账号登录

#### Scenario: 系统级用户执行写入步骤
- **WHEN** 云端业务账号命中超级账号表且流程需要写入云端平台
- **THEN** Skill 必须先展示拟调用工具、调用目的和关键入参摘要
- **THEN** 只有用户确认后才允许调用写入工具
- **THEN** 超级账号权限不得被视为自动写入授权

#### Scenario: 有业务 Token 但无系统权限
- **WHEN** MCP 接入 Token 有效但没有云端业务 Token 或云端账号未命中超级账号表
- **THEN** Skill 仍不得执行云端平台写入工具
- **THEN** 写入权限不得仅由 MCP 接入 Token、来源 IP 或 localhost 决定
- **THEN** Skill 必须把 MCP 接入 Token 能力描述为连接 MCP 的能力，而不是云端平台写入能力

### Requirement: 写入操作不得自动重试
系统 SHALL 将写入工具返回值展示给用户，并 SHALL NOT 在失败后自动重试或自动执行补偿写入。

#### Scenario: 写入成功或失败返回
- **WHEN** 任一写入工具完成调用
- **THEN** Skill 必须展示写入动作、调用工具、调用目的、关键入参摘要、返回 code、返回 message、返回 data 或 raw、是否成功、下一步待用户决定项

#### Scenario: 写入失败
- **WHEN** 写入工具返回失败、异常或非成功业务码
- **THEN** Skill 不得自动重试
- **THEN** Skill 不得自行选择替代写入操作
- **THEN** Skill 必须等待用户决定下一步

### Requirement: 数据项和原子标签首期只处理基础信息
系统 SHALL 将原子标签查询映射到功能项查询工具（API-E10 `GetProtocoFunctionTypeList`，MCP 工具 `get_function_type_list`），并 SHALL 在首期只查询或新增基础信息，不通过平台写入工具写入完整 MODBUS 寄存器采集配置；原子标签匹配 SHALL 优先使用平台功能项列表，平台未命中后再回退本地 references 和用户补充。

#### Scenario: 查询数据项
- **WHEN** Skill 需要匹配协议文档中的数据项中文名到原子标签或平台功能项
- **THEN** Skill 必须使用 `get_function_type_list` 查询平台功能项候选，不依赖 `protocolId` 或前置规约查询
- **THEN** 工具参数限于既有 `functionTypeName`、`functionCode`、`pageIndex`、`pageSize`，不添加 `token` 或 `protoType`
- **THEN** Skill 必须优先在平台功能项候选中进行精确、归一、同义词或模糊匹配
- **THEN** 查询结果必须进入用户确认表，`unit` 仅作为目标单位候选；缺失、为空或与内部类型定义冲突时回查适用参考资料并交用户确认
- **THEN** 来源必须精确到字段，例如 `MCP:get_function_type_list.rows[i].unit`，并记录查询条件和页码

#### Scenario: 功能项与规约数据项隔离
- **WHEN** 使用功能项候选生成寄存器配置或记录缺失原子标签
- **THEN** `functionCode` 不得当作 MODBUS `func_code`，平台 `dataType` 不得直接当作寄存器 `data_type`
- **THEN** `get_data_item_list` 保留规约数据项管理用途，`functionId` 不得当作规约数据项 ID
- **THEN** 不新增平台功能项写入路径，不得用 `add_data_item` 代替功能项新增；既有规约数据项基础信息管理仍需确认对应规约、权限和用户授权
- **THEN** 缺失原子标签必须交用户确认，查询失败不得触发新增

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
系统 SHALL 默认先生成本地 MODBUS JSON，并 SHALL 在用户确认本地结果且云端写权限可用后才进入可选平台同步分支；当云端写权限不可用时，系统 SHALL 不展示云端平台同步确认分支。

#### Scenario: 生成本地 JSON
- **WHEN** 用户确认最终参数表和数据项映射
- **THEN** Skill 生成本地 MODBUS JSON
- **THEN** JSON 输出路径和文件名必须展示给用户

#### Scenario: 用户未确认同步平台
- **WHEN** 本地 JSON 已生成但用户未明确同意同步云端平台
- **THEN** Skill 不得调用 `upload_protocol_file`、`add_protocol_info`、`gen_script` 或其他平台写入工具

#### Scenario: 用户权限为 user
- **WHEN** 本地 JSON 已生成且当前云端写权限不可用
- **THEN** Skill 不得询问用户是否同步云端平台
- **THEN** Skill 必须说明平台同步未执行且需要超级账号登录

#### Scenario: 用户确认同步平台
- **WHEN** 用户明确同意同步云端平台且当前云端写权限可用
- **THEN** Skill 展示平台同步计划并请求确认
- **THEN** 用户确认后才调用平台同步相关写入工具

### Requirement: MODBUS 首期不得调用删除类工具
MODBUS 首期 Skill SHALL NOT 调用删除类 MCP 工具。

#### Scenario: 删除工具不可用
- **WHEN** MODBUS 首期 Skill 生成工具调用计划
- **THEN** 计划中不得包含 `del_classify`、`del_device_type`、`del_brand`、`del_model`、`del_protocol_info`、`del_data_item`、`del_script`、`del_protocol_file` 或其他删除类工具

### Requirement: 输出必须包含可验证确认信息
系统 SHALL 在生成 JSON 前展示最终确认表，并 SHALL 在无法验证参数时输出缺失项清单。

#### Scenario: 最终确认表
- **WHEN** Skill 准备生成 MODBUS JSON
- **THEN** Skill 必须展示品牌、设备类型、classNum、modelNum、协议类型、采集数据项、原子标签、寄存器地址、功能码、data_type、data_order、源单位、目标单位、协议精度/原公式及其输出单位、单位换算关系、最终 data_exprs、来源、验证样例和待确认项
- **THEN** 单位核对列仅为分析记录，不新增引擎 JSON 字段

#### Scenario: 缺失项清单
- **WHEN** MCP 查询、本地 references 和用户输入都无法确定某个必需参数
- **THEN** Skill 必须列出缺失项清单
- **THEN** Skill 不得继续生成最终 JSON

### Requirement: MODBUS 输出记录必须包含交付摘要与阶段化结构
系统 SHALL 在 MODBUS 协议转换完成时输出结构化交互记录或摘要，包含结论摘要、阶段化过程、最终确认表、产物清单、测试清单、未验证项、续跑摘要、变更影响、可选自动建档衔接状态和下一步建议。

#### Scenario: 输出结论摘要
- **WHEN** MODBUS 协议转换流程完成或阶段性结束
- **THEN** 系统必须在输出开头给出结论摘要
- **THEN** 摘要必须说明 MCP 接入状态、云端业务 Token 状态、本地 JSON 是否生成、云端平台同步是否执行、自动建档是否已准备、关键风险或待处理项

#### Scenario: 使用阶段化命名
- **WHEN** 系统整理协议转换过程
- **THEN** 系统必须使用"阶段一/阶段二/阶段三"描述过程
- **THEN** 系统不得使用容易与软件版本混淆的"版本交互一/版本交互二"作为阶段标题

#### Scenario: 输出续跑摘要
- **WHEN** MODBUS 流程阶段性结束且仍有未确认项或后续动作
- **THEN** 系统必须列出已确认实体、已确认点位、待确认点位、本地 JSON 状态、平台同步状态和自动建档准备状态
- **THEN** 系统必须给出用户可执行的续跑动作，例如继续确认点位、跳过未确认点位、重新匹配原子标签、以超级账号登录同步平台或提供自动建档 Excel 执行 dry-run

#### Scenario: 输出变更影响提示
- **WHEN** 用户选择候选原子标签、补充新标签、确认平台新增内容或选择衔接自动建档
- **THEN** 系统必须说明该选择对 `taskList`、`labelList`、本地 JSON、可选平台同步和可选建档下发的影响
- **THEN** 系统必须说明该选择是否会触发平台写入、边缘建档写入或下发审计副作用以及需要的权限/凭据

### Requirement: MODBUS 字段语义必须拆分并精确标注来源
系统 SHALL 在最终确认表中拆分 C 引擎字段、平台实体字段和查询辅助字段，并 SHALL 将来源标记精确到文件、表格、接口、行或字段级别。

#### Scenario: 展示字段语义拆分
- **WHEN** 最终确认表包含 `classNum`、`modelNum`、`classifyId`、`deviceTypeId`、`deviceTypeCode`、`brandId`、`modelId` 或 `protocolId`
- **THEN** 系统必须说明每个字段的业务含义
- **THEN** 系统必须说明该字段是否写入本地 JSON、仅用于平台查询、或仅用于平台同步

#### Scenario: 精确来源标记
- **WHEN** 参数来自 MCP 查询返回
- **THEN** 来源标记必须精确到工具和字段，例如 `MCP:get_model_list.rows[i].brandId`
- **THEN** 不得只写 `MCP:get_model_list` 作为唯一来源标记

#### Scenario: 本地来源标记
- **WHEN** 参数来自本地 references 或协议文档
- **THEN** 来源标记必须包含文件名和可识别位置，例如 sheet 名、章节名、表名或用户上传文档名称

### Requirement: MODBUS 点表必须展示地址、跨度和单位
系统 SHALL 在用户确认数据项时展示增强点表，至少包含中文名称、英文标签、Hex 地址、十进制地址、寄存器跨度、data_type、data_order、func_code、源单位、目标单位、协议精度/原公式及其输出单位、单位换算关系、最终 data_exprs、来源、验证样例和读写属性。

#### Scenario: FLOAT 数据项展示跨度
- **WHEN** 数据项 `data_type` 为 `[FLOAT]`
- **THEN** 系统必须展示该点位占用 2 个寄存器
- **THEN** 系统必须展示起始地址和实际地址范围

#### Scenario: UINT32 数据项展示跨度
- **WHEN** 数据项 `data_type` 为 `[UINT32]` 或 `[SINT32]`
- **THEN** 系统必须展示该点位占用 2 个寄存器
- **THEN** 系统必须展示字序或字节序依据

#### Scenario: 单位不确定
- **WHEN** 源单位或目标单位缺失、为空、由仪表参数决定或来源冲突
- **THEN** 系统必须将单位标记为待确认或随仪表配置，回查适用参考资料并请用户确认，阻断未确认点位最终配置
- **THEN** 系统不得编造固定单位；明确无量纲量与枚举另行核对精度及映射语义，不因无物理单位一律阻断

### Requirement: MODBUS 歧义项必须由用户确认
系统 SHALL 对影响 JSON 行为、平台同步或业务语义的歧义项列出可选方案，并在用户确认前不得生成最终 JSON 或执行平台写入。

#### Scenario: 功能码不确定
- **WHEN** 协议文档未说明功能码，或同一数据项同时支持多个功能码，或平台历史脚本与协议文档功能码不同
- **THEN** 系统必须列出差异和候选功能码
- **THEN** 系统必须由用户确认最终 `func_code`
- **THEN** 协议文档明确时默认以协议文档为准

#### Scenario: 数据类型差异
- **WHEN** 平台历史脚本的数据类型写法与 Skill 规范不同
- **THEN** 系统必须说明差异
- **THEN** 本地 JSON 默认采用 Skill 规范的数据类型写法
- **THEN** 如用户要求兼容平台旧写法，系统必须将其作为待验证或用户确认项

#### Scenario: 标签语义不唯一
- **WHEN** 一个寄存器含义存在多种解释、多个候选标签或平台暂无数据项
- **THEN** 系统必须列出候选中文名、英文标签、单位、来源和影响
- **THEN** 系统必须由用户确认最终标签处理方式

### Requirement: 平台暂无数据项必须明确处理策略
系统 SHALL 在平台数据项不存在但本地 JSON 需要保留该点位时，明确输出本地保留、平台新增需求、所需权限和是否阻塞同步。

#### Scenario: 本地保留但平台暂无
- **WHEN** 平台数据项查询为空但用户确认本地 JSON 保留该数据项
- **THEN** 系统必须在最终输出中列出该数据项
- **THEN** 系统必须说明该数据项未同步到平台
- **THEN** 系统必须说明后续新增平台数据项需要用户确认基础信息和 system 权限

#### Scenario: 平台同步前存在缺失数据项
- **WHEN** 用户请求同步平台且存在平台暂无的数据项
- **THEN** 系统必须先展示缺失项清单
- **THEN** 系统不得自动新增数据项
- **THEN** 系统必须等待用户确认新增内容和同步计划

### Requirement: MODBUS 输出必须包含最小冒烟测试与未验证项
系统 SHALL 在转换完成输出中提供最小冒烟测试清单和未验证项清单，用于区分已验证事实、用户选择和后续风险。

#### Scenario: 输出最小冒烟测试清单
- **WHEN** MODBUS JSON 已生成
- **THEN** 系统必须输出可执行的最小冒烟测试清单
- **THEN** 清单至少覆盖 JSON 结构一致性、地址 Hex/Dec 对应、寄存器跨度、功能码来源、data_type 规范、六种字节序、位范围、转换公式和单位门控
- **THEN** 必须按真实字段 `addr_base/data_type/data_order/addr_exprs/data_exprs/func_code` 校验，不要求不存在的 `readPlan/polling/scale` 字段，功能码保持 read=3/4、write=6/16
- **THEN** 静态契约检查、离线算例、真实引擎测试和现场测试必须分别报告，文档/资源测试不得冒充运行时验证

#### Scenario: 输出未验证项清单
- **WHEN** MODBUS 流程完成或中止
- **THEN** 系统必须列出未验证项、未验证原因和是否阻塞当前产物
- **THEN** 未验证项必须包括适用的现场设备读取、平台写入、平台新增数据项、功能码现场兼容性或 data_type 兼容性
- **THEN** 缺少实际引擎或设备时，BCD 符号/异常编码解码和字节序真实兼容性必须列为未验证，不得声称现场通过

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
- **THEN** Skill 只有在查询条件变化、需要继续分页或用户要求刷新时才重新调用 `get_function_type_list`
- **THEN** 不得把单页未命中直接判断为不存在，必须依据实际分页信息完成必要查询

### Requirement: MODBUS 数据类型与位范围必须有协议依据
系统 SHALL 保留 `[UINT16]`、`[SINT16]`、`[UINT32]`、`[SINT32]`、`[FLOAT]` 及位提取，补齐 `[UBCD16]`、`[SBCD16]` 配置类型说明，不实现新解码器。

#### Scenario: BITS 使用具体范围
- **WHEN** 界面类型为 `[BITS]`，表示一个 byte 未用满
- **THEN** 最终 `data_type` 必须使用具体 `[起始位:结束位]`，例如 bit0～bit3 写 `[0:3]`，不得使用无范围的 `[BITS]`
- **THEN** 位号以协议为准，保留 `[0:7]`、`[8:15]`，不得擅自将高字节位号改为低字节或推定读取不足一个寄存器
- **THEN** 离线算例必须覆盖 byte `0xAB` 的 `[0:3]` 为 11，`0x1234` 的 `[8:15]` 为 18、`[0:7]` 为 52
- **THEN** 保留位提取与按位运算互斥，PQ 等需要 `&` 的字段仍以 `[UINT16]` 读取整寄存器

#### Scenario: 有符号及无符号 BCD
- **WHEN** 协议明确为 16 位有符号或无符号 BCD
- **THEN** 分别使用 `[SBCD16]` 或 `[UBCD16]`，跨度为 1 个寄存器
- **THEN** 不自行规定符号位置、符号码或异常编码处理，不套用二进制补码规则
- **THEN** 编码语义不明的点位标记待确认，不得编造符号解码测试预期

### Requirement: MODBUS 必须完整说明六种字节序
系统 SHALL 以高位到低位的字节命名 A/B/C/D，列出两字节 `AB/BA` 和四字节 `ABCD/DCBA/BADC/CDAB`，具体选择必须有协议依据，不新增默认值。

#### Scenario: 两字节排列
- **WHEN** 使用 UINT16/SINT16/UBCD16/SBCD16 等两字节类型
- **THEN** 候选为 AB 大端或 BA 小端；`0x12 34` 分别排列为 `12 34`、`34 12`

#### Scenario: 四字节排列
- **WHEN** 使用 UINT32/SINT32/FLOAT 等四字节类型
- **THEN** `0x12 34 56 78` 的 ABCD/DCBA/BADC/CDAB 分别排列为 `12 34 56 78`、`78 56 34 12`、`34 12 78 56`、`56 78 12 34`
- **THEN** BADC 表示每个寄存器内部字节交换，CDAB 表示两个寄存器交换；离线排列验证不等于引擎或现场验证

### Requirement: MODBUS 单位换算必须防止遗漏与重复
系统 SHALL 先按协议解码，再还原精度、符号及经确认的一次/二次侧语义，最后换算到目标单位；先确定原公式输出单位，PT/CT 变比不作为单位换算。

#### Scenario: 已知倍率转换
- **WHEN** 已确认源单位与目标单位为同一物理量的已知倍率关系
- **THEN** 支持功率、电能、电压、电流等已知关系，使用既有算术表达式，不扩展引擎语法
- **THEN** 1500 W→1.5 kW 使用 `$D/1000`；1.5 kW→1500 W 使用 `$D*1000`
- **THEN** 15000 个 0.1 W→1.5 kW 使用 `$D/10/1000`，同时覆盖负值与零值

#### Scenario: 同单位或已有换算
- **WHEN** 原协议直接提供目标单位、原公式已完成缩放或已有单位换算
- **THEN** 不重复除以 1000、不重复乘 PT/CT，保留原有数值语义，不自动迁移存量配置
- **THEN** 同单位且无其他转换时 `data_exprs` 保持空字符串；同单位但需要协议精度处理时保留该公式，不省略字段
- **THEN** 找不到协议转换公式也必须核对单位，不能直接判定无需转换

#### Scenario: 不同物理量或复杂关系
- **WHEN** 候选关系为 W 与 kWh 等不同物理量，或需要偏移及其他复杂关系但没有明确公式
- **THEN** 阻断该未确认映射并请用户确认目标标签或补充公式，不自行推导、不编造公式

#### Scenario: 写操作独立确认方向
- **WHEN** 用户要求配置 write
- **THEN** 独立分析目标值到设备值的方向，保留既有 write/convert 机制，不直接复制 read 公式
- **THEN** 不可逆、舍入规则或写公式语义不明确时阻断该未确认写配置，不擅自舍入、截断或新增写操作

#### Scenario: 兼容与验证边界
- **WHEN** 更新本轮 Skill、规范和资源契约测试
- **THEN** 保留 prtlType/modelNum/classNum/taskList/labelList、read/write/convert、辅助标签顺序、动态精度、PT/CT、多路地址及空表达式规则
- **THEN** 不新增引擎 JSON 字段，不为新增校验改动无关历史样例，不修改运行时引擎、平台 API、鉴权、建档、HTTP/MQTT 或重庆适配
- **THEN** 不发布、不覆盖客户端 Skill、不同步平台、不读写设备；缺少真实环境的验证必须明确列出

### Requirement: MODBUS 流程必须可选衔接 XLPA 自动建档
系统 SHALL 在 MODBUS 转换完成后提供可选的自动建档衔接；该衔接 SHALL 使用自动建档 Excel 模板和边缘任务凭据，并 SHALL 先执行 dry-run，不得直接写入边缘后端。

#### Scenario: 用户选择衔接自动建档
- **WHEN** MODBUS JSON 已生成且用户希望继续建档
- **THEN** Skill 必须提示用户提供或生成 XLPA 自动建档 Excel 模板
- **THEN** Skill 必须调用自动建档 dry-run 能力生成计划
- **THEN** Skill 不得仅凭 MODBUS JSON 自动推断所有建档字段

#### Scenario: 用户跳过自动建档
- **WHEN** 用户未选择自动建档或缺少必要 Excel 信息
- **THEN** Skill 必须说明自动建档未执行
- **THEN** Skill 必须保留本地 JSON、确认表和可复用产物供后续续跑

#### Scenario: 建档衔接存在缺失项
- **WHEN** Excel 模板或协议文件缺少建档所需字段
- **THEN** Skill 必须列出缺失项和来源
- **THEN** Skill 必须等待用户补充或选择跳过自动建档
