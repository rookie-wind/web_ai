## MODIFIED Requirements

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

## ADDED Requirements

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
