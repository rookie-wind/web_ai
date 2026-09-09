## Purpose

定义 MODBUS 协议转换 Skill 在首期如何以现有 `modbus-conversion` 流程为基准，编排规约管理 MCP 原子工具、本地参考资料、权限控制、本地 JSON 生成与可选平台同步，确保所有参数来源和写入行为可验证、可追溯、可由用户确认。

## ADDED Requirements

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
MODBUS Skill SHALL 在启动时询问用户是否提供 `login(phoneNum, code)` 所需信息，并 SHALL 明确 MCP 接入 Token 与后端业务 Token 不得混用。

#### Scenario: 用户提供登录信息
- **WHEN** 用户提供 `phoneNum` 和不会过期的 `code`
- **THEN** Skill 调用 `login(phoneNum, code)` 获取后端业务 Token
- **THEN** 后续后端 API 类 MCP 工具使用该业务 Token

#### Scenario: 用户未提供登录信息
- **WHEN** 用户未提供 `phoneNum` 或 `code`
- **THEN** Skill 必须告知用户后续所有参数来源仅使用本地 `references` 目录
- **THEN** Skill 不得调用需要后端业务 Token 的后端 API 类 MCP 工具

#### Scenario: Token 不得混用
- **WHEN** Skill 调用 MCP Server
- **THEN** MCP 接入 Token 仅用于连接 `/mcp` 端点
- **THEN** 后端业务 Token 仅用于调用后端业务 API
- **THEN** 任一 Token 不得替代另一 Token 使用

### Requirement: 参数来源必须优先查询并可追溯
系统 SHALL 优先通过 MCP 只读工具查询 MODBUS JSON 所需参数；当 MCP 查询为空、失败或未登录时，必须按不同结果类型处理，并在最终输出中标注参数来源。

#### Scenario: MCP 查询成功且命中
- **WHEN** MCP 查询工具返回成功且存在匹配结果
- **THEN** Skill 使用查询结果作为候选参数
- **THEN** 最终确认表必须标注来源为对应 MCP 工具名

#### Scenario: MCP 查询成功但为空
- **WHEN** MCP 查询工具正常返回成功但无匹配结果
- **THEN** Skill 可以回退到本地 `references` 搜索候选值或请求用户提供
- **THEN** Skill 不得把空结果当作查询失败

#### Scenario: MCP 查询失败
- **WHEN** MCP 查询发生网络错误、Token 错误、权限错误、参数错误或后端业务错误
- **THEN** Skill 必须向用户展示错误信息
- **THEN** Skill 不得把该错误当作数据不存在
- **THEN** Skill 不得基于失败结果自动进入新增流程

#### Scenario: 本地推荐值需要确认
- **WHEN** Skill 从本地 `references` 搜索到推荐参数
- **THEN** Skill 必须标注具体来源文件或本地来源类别
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
系统 SHALL 以 MCP 接入权限决定是否允许写入：普通用户仅可执行只读流程，系统级用户可在用户确认后执行写入流程。

#### Scenario: 普通用户遇到写入步骤
- **WHEN** 普通用户执行 MODBUS 流程且缺失参数需要新增或同步平台
- **THEN** Skill 必须停止写入步骤
- **THEN** Skill 必须提示需要系统级用户执行该操作

#### Scenario: 系统级用户执行写入步骤
- **WHEN** 系统级用户执行需要写入的步骤
- **THEN** Skill 必须先展示拟调用工具、调用目的和关键入参摘要
- **THEN** 只有用户确认后才允许调用写入工具

#### Scenario: 有业务 Token 但无系统权限
- **WHEN** 普通用户提供有效后端业务 Token
- **THEN** Skill 仍不得执行写入工具
- **THEN** 写入权限不得仅由后端业务 Token 决定

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
系统 SHALL 将原子标签查询映射到数据项管理工具，并 SHALL 在首期只查询或新增基础信息，不通过数据项写入工具写入完整 MODBUS 寄存器采集配置。

#### Scenario: 查询数据项
- **WHEN** Skill 需要匹配协议文档中的数据项中文名到原子标签或数据项
- **THEN** Skill 使用数据项管理只读工具查询候选项
- **THEN** 查询结果必须进入用户确认表

#### Scenario: 数据项查询不到
- **WHEN** 系统级用户查询不到目标数据项
- **THEN** Skill 必须让用户提供基础信息或从本地 `references` 搜索推荐基础信息
- **THEN** 用户确认新增内容后，Skill 再询问是否新增到平台

#### Scenario: 不写入完整采集配置
- **WHEN** 新增数据项基础信息
- **THEN** Skill 不得把寄存器地址、功能码、数据类型、字节序、转换表达式、枚举映射等完整 MODBUS 采集配置写入平台数据项
- **THEN** 完整采集配置仅用于本地 MODBUS JSON 生成

### Requirement: 本地 JSON 生成与平台同步必须分阶段
系统 SHALL 默认先生成本地 MODBUS JSON，并 SHALL 在用户确认本地结果后才询问是否同步到平台。

#### Scenario: 生成本地 JSON
- **WHEN** 用户确认最终参数表和数据项映射
- **THEN** Skill 生成本地 MODBUS JSON
- **THEN** JSON 输出路径和文件名必须展示给用户

#### Scenario: 用户未确认同步平台
- **WHEN** 本地 JSON 已生成但用户未明确同意同步平台
- **THEN** Skill 不得调用 `upload_protocol_file`、`add_protocol_info`、`gen_script` 或其他平台写入工具

#### Scenario: 用户确认同步平台
- **WHEN** 用户明确同意同步平台且当前为系统级用户
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
- **THEN** Skill 必须展示品牌、设备类型、classNum、modelNum、协议类型、采集数据项、原子标签、寄存器地址、功能码、data_type、data_order、data_exprs、参数来源和待确认项

#### Scenario: 缺失项清单
- **WHEN** MCP 查询、本地 references 和用户输入都无法确定某个必需参数
- **THEN** Skill 必须列出缺失项清单
- **THEN** Skill 不得继续生成最终 JSON
