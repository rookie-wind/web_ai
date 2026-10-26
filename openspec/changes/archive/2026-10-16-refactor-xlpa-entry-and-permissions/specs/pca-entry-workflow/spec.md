## MODIFIED Requirements

### Requirement: PCA 入口必须执行前置状态检查
系统 SHALL 将协议转换统一入口迁移为 `/xlpa`，并 SHALL 在入口开始业务流程前执行前置状态检查，至少包括 MCP 连接状态、MCP 接入 Token 状态、云端业务 Token 状态、云端平台写权限状态、边缘建档任务凭据状态、MCP Server 版本、Agent 资源包版本、版本兼容风险和后续流程可用性提示。历史 `/pca` 入口不作为兼容入口保留。

#### Scenario: MCP 探测成功
- **WHEN** 用户发起 `/xlpa` 需求且 MCP 连接可用
- **THEN** 系统必须展示当前 MCP 服务名、工具数量、MCP 接入 Token 状态、请求来源和 MCP Server 版本
- **THEN** 系统必须展示远端 Agent 资源包版本、本地 Agent 资源包版本或无法比较的原因
- **THEN** 系统必须说明 MCP 接入、云端只读查询、云端写入、本地 JSON 生成、边缘建档 dry-run、边缘建档写入、下发和召测验证的可用性

#### Scenario: 用户使用旧 PCA 入口
- **WHEN** 用户或资源包尝试以 `/pca` 作为主入口执行新流程
- **THEN** 系统必须将其视为过期入口
- **THEN** 系统必须提示使用 `/xlpa` 或 XLPA Skill
- **THEN** 系统不得继续维护 `/pca` wrapper 作为兼容转发入口

#### Scenario: MCP 探测失败
- **WHEN** 用户发起 `/xlpa` 需求但 MCP 连接或鉴权探测失败
- **THEN** 系统必须展示失败原因或错误返回
- **THEN** 系统不得声称平台查询、平台写入、边缘建档写入或 Agent 资源包更新已完成
- **THEN** 系统可以继续执行仅依赖本地文件的协议分析流程，并必须标注本地来源

#### Scenario: 版本存在兼容风险
- **WHEN** 本地 Agent 资源包版本低于远端版本或缺少当前流程所需特性
- **THEN** 系统必须提示版本兼容风险和可能缺失的能力
- **THEN** 系统必须说明当前任务是否仍可继续
- **THEN** 系统不得把版本更新作为默认执行动作

### Requirement: PCA 入口必须按本地业务 Token 状态提示登录
系统 SHALL 在 XLPA 入口中区分 MCP 接入 Token、云端后端业务 Token 和边缘建档任务凭据；系统 SHALL 在没有可用云端业务 Token 时提示用户提供 `login(phoneNum, code)` 登录参数；获取一次 Token 后 SHALL 保存到本地业务 Token 缓存供后续 `/xlpa` 会话复用。

#### Scenario: 本地已有业务 Token
- **WHEN** 用户发起 `/xlpa` 需求且本地存在云端后端业务 Token
- **THEN** 系统不得重复要求用户输入 `phoneNum` 和 `code`
- **THEN** 系统必须优先使用本地业务 Token 调用只读平台查询工具
- **THEN** 如果任一平台工具返回认证失效，系统必须丢弃或标记该 Token 失效，并重新提示用户登录

#### Scenario: 本地没有业务 Token
- **WHEN** 用户发起 `/xlpa` 需求且本地不存在云端后端业务 Token
- **THEN** 系统必须提示用户可提供 `phoneNum` 和 `code` 以启用平台查询
- **THEN** 用户未提供登录参数时，系统必须说明本次仅使用本地 references 或不需要登录的流程
- **THEN** 系统不得调用需要云端业务 Token 的 MCP 工具

#### Scenario: 登录成功并保存 Token
- **WHEN** 用户提供 `phoneNum` 和 `code` 且 `login` 返回成功
- **THEN** 系统必须将返回的云端业务 Token 保存到本地业务 Token 缓存
- **THEN** 系统必须说明该 Token 仅作为云端后端 API 工具的 `token` 参数使用
- **THEN** 系统不得把云端业务 Token 写入 MCP 配置或作为 MCP 接入 Token 使用

#### Scenario: 登录账号命中超级账号表
- **WHEN** 用户登录云端平台成功且账号命中本地超级账号配置
- **THEN** 系统必须将云端平台写权限标记为可确认后执行
- **THEN** 系统必须说明写权限来源为业务登录账号命中超级账号表
- **THEN** 系统不得将 MCP 接入 Token 或 localhost 来源描述为写权限来源

#### Scenario: 登录失败
- **WHEN** `login(phoneNum, code)` 返回失败、网络错误或业务错误
- **THEN** 系统必须展示错误返回
- **THEN** 系统不得创建或复用新的本地业务 Token
- **THEN** 系统必须等待用户决定重试、跳过登录或停止

### Requirement: PCA 入口必须提供全量 Skills 更新操作
系统 SHALL 在 `/xlpa` 入口提供检查并更新本地 Agent 资源包的操作；更新范围为全部 `.trae/skills`，更新前必须备份，用户确认后允许覆盖本地 Skills，更新后必须提示重新加载会话或重启客户端以生效。

#### Scenario: 用户选择检查 Skills 更新
- **WHEN** 用户在 `/xlpa` 入口选择检查或更新本地 Agent 资源包
- **THEN** 系统必须读取本地资源包和 Skill 版本信息
- **THEN** 系统必须从 MCP Server 获取可用的远端 Agent 资源包版本、manifest 校验状态和兼容性信息
- **THEN** 系统必须展示本地版本、远端版本、manifest 校验状态或无法比较的原因

#### Scenario: 发现可选更新
- **WHEN** 本地版本低于远端版本但当前任务不依赖新能力
- **THEN** 系统必须提示存在可选更新
- **THEN** 系统不得强制用户先更新才能继续当前任务

#### Scenario: 当前任务依赖新能力
- **WHEN** 当前任务需要本地资源包尚不支持的能力
- **THEN** 系统必须提示建议先更新资源包
- **THEN** 系统必须展示不更新继续执行的风险或受限范围

#### Scenario: 用户确认全量更新
- **WHEN** 用户确认更新本地 Agent 资源包
- **THEN** 系统必须先备份当前 `.trae/skills` 目录
- **THEN** 系统必须下载远端 Agent 资源包 ZIP 并覆盖更新全部本地 Skills
- **THEN** 系统必须验证关键 Skill 目录、manifest 声明的必需文件和 `agents/openai.yaml` 存在
- **THEN** 系统必须提示用户重新加载 `/xlpa` 会话或重启客户端以使用新版 Skill

#### Scenario: 用户未确认更新
- **WHEN** 系统展示 Agent 资源包更新计划但用户未明确确认
- **THEN** 系统不得覆盖、删除或移动本地 `.trae/skills` 内容
- **THEN** 系统可以继续执行当前已安装版本支持的流程，并必须提示可能存在版本差异

### Requirement: PCA 入口输出必须给出用户可执行下一步
系统 SHALL 在 `/xlpa` 前置检查和任一子流程结束时输出用户可执行的下一步建议，且建议必须与当前登录状态、云端写权限状态、边缘建档任务状态、版本状态、产物状态和用户选择一致。

#### Scenario: 本地配置已生成但未同步平台
- **WHEN** 协议转换流程生成本地 JSON 且用户未确认平台同步
- **THEN** `/xlpa` 汇总输出必须说明本地文件路径、平台同步未执行、未调用写入工具
- **THEN** `/xlpa` 必须给出后续可选操作，例如测试验证、打包分发、在云端写权限可用时同步平台或使用自动建档模板继续边缘建档

#### Scenario: 当前权限为 user
- **WHEN** 当前 MCP 接入有效但云端业务账号未登录或未命中超级账号表
- **THEN** `/xlpa` 必须说明云端平台写入不可用
- **THEN** `/xlpa` 不得展示平台新增或平台同步的确认选项
- **THEN** 如用户请求云端写入或同步，系统必须提示需要使用超级账号完成 `login(phoneNum, code)`

#### Scenario: 边缘建档凭据可用
- **WHEN** 自动建档 Excel 提供边缘后端地址、loginName 和 password
- **THEN** `/xlpa` 可以展示边缘建档 dry-run 选项
- **THEN** `/xlpa` 必须说明边缘建档写入权限来自 Excel 任务凭据而不是云端超级账号

#### Scenario: 当前存在可选更新
- **WHEN** 前置检查发现本地 Agent 资源包落后于远端但当前任务可继续
- **THEN** `/xlpa` 必须将更新作为可选下一步展示
- **THEN** `/xlpa` 不得用更新提示阻塞当前已可执行的只读查询、本地生成或 dry-run 流程

### Requirement: PCA 入口必须展示能力矩阵
系统 SHALL 在 `/xlpa` 前置检查后展示当前会话能力矩阵，用于说明 MCP 工具调用、云端平台只读查询、本地 references 分析、本地 JSON 生成、云端平台写入、平台同步、边缘建档 dry-run、边缘建档写入、资源包更新是否可用。

#### Scenario: system 权限能力矩阵
- **WHEN** 当前云端业务账号命中超级账号表
- **THEN** 能力矩阵必须显示云端平台写入和平台同步为可确认后执行
- **THEN** 能力矩阵必须说明写入仍需要用户逐项确认
- **THEN** 能力矩阵不得将 system 权限来源描述为 localhost 或 MCP 接入 Token

#### Scenario: user 权限能力矩阵
- **WHEN** 当前有有效云端业务 Token 但账号未命中超级账号表
- **THEN** 能力矩阵必须显示云端只读查询可用
- **THEN** 能力矩阵必须显示云端平台写入和平台同步不可用
- **THEN** 能力矩阵必须说明写入需要超级账号登录

#### Scenario: 未登录业务 Token
- **WHEN** 当前没有可用云端后端业务 Token
- **THEN** 能力矩阵必须说明需要业务 Token 的云端平台查询不可用
- **THEN** 能力矩阵必须说明不依赖业务 Token 的本地分析仍可继续
- **THEN** 能力矩阵不得把 MCP 接入 Token 展示为云端平台写入授权来源

#### Scenario: 边缘建档任务凭据可用
- **WHEN** 自动建档 Excel 提供可用边缘建档凭据
- **THEN** 能力矩阵必须显示边缘建档 dry-run 可用
- **THEN** 在用户确认写入前，能力矩阵必须将边缘建档写入标记为待确认
- **THEN** 能力矩阵必须将边缘建档凭据与云端平台写权限分开展示
