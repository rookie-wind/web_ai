# agent-runtime-session Specification

## Purpose
定义 Web 会话运行时的行为契约：会话生命周期、会话与 CLI 实例及接入凭据的
1:1:1 绑定、SDK 事件向自有事件契约 v1 的归一化、SSE 下发与断线重放、
单写者租约、实例池与配额、会话工作区布局与隔离。

**变更四要素**

| 要素 | 内容 |
|---|---|
| 前置条件（含需先验证事项） | 1) C1/C2 已归档；2) V1/V3/V4/V9/V10 已 PASS（v1v3 + C2 证据）；3) **需补验**：V1b（SDK 会话恢复粒度：resume/session_id + SessionStore 载体已确认存在，行为待实测）、V2（`/xlpa` 技能在无头 SDK 会话中是否展开；失败回退：系统提示词注入路由表）、实例冷启动成本（采样记录）；4) MCP Server 可启动且 mint 端点就绪（mcp-token-mint spec 同变更交付） |
| 要做的事 | SDK adapter（SDK 类型只出现在 webchat/webchat/sdk_runtime/ 单层）、会话管理（创建/发消息/列表/历史/结束）、1:1:1 绑定、事件契约 v1（归一化+持久化+seq 重放）、SSE 端点、单写者租约、实例池与配额、会话工作区布局、IDE 兼容回归 |
| 通过标准（可执行判据） | 1) webchat pytest 全过（1:1:1 隔离断言：两并发会话的实例/凭据/工作区/事件流互不串扰；seq 重放补齐；租约抢占；配额超限拒绝；结束会话凭据撤销）；2) 主 pytest 基线全绿；3) V1b/V2/冷启动结论留证（含失败回退决策记录）；4) 一次真实"登录→建会话→发消息→收到事件流→断线重连补齐"端到端演练取证；5) IDE 回归：/mcp 与接入页行为不变 |
| 执行顺序与依赖 | 依赖 C2（票据体系）与本变更的 mcp-token-management delta + mcp-token-mint（同变更内先交付）；C4/C5 依赖本变更 |

## Requirements

### Requirement: Web 会话必须与 CLI 实例及接入凭据 1:1:1 绑定

每个 Web 会话 MUST 对应恰好一个专属 CLI 实例与一把专属 MCP 接入凭据；
凭据在实例启动时随配置绑定，运行期 MUST NOT 切换；实例与凭据 MUST NOT
跨会话共享；会话结束时凭据 MUST 撤销、实例 MUST 终止、工作区按保留策略
处置。

#### Scenario: 并发会话互不串扰

- **WHEN** 用户 A 与用户 B 各自创建会话并同时在各自会话中执行任务
- **THEN** 两会话使用不同的 CLI 实例、不同的接入凭据、不同的工作区目录
- **THEN** 任一会话的工具调用审计归属各自的 owner_ref，互不混淆

#### Scenario: 会话结束即回收

- **WHEN** 会话被用户结束或超时回收
- **THEN** 该会话的接入凭据立即撤销（后续 /mcp 调用 401），CLI 实例终止，
  事件流以收尾事件关闭

### Requirement: SDK 事件必须归一化为自有事件契约 v1

后端 MUST 将 SDK 消息归一化为自有事件契约（版本字段 v=1），事件统一携带
v、seq（会话内单调递增）、session_id、ts；事件类型至少覆盖：
session_started、text_delta（实时增量，基于 SDK 流式能力）、tool_call、
tool_result、ask_user（Agent 向用户提问；来源为 SDK elicitation 事件，
或本轮结束时模型文本中含待用户补充的提问——后者为当前唯一可达路径，
elicitation 通道若在其他系统落地可作为扩展来源）、
gate_blocked（写入门禁拒绝，Agent 等待用户确认）、artifact（产物就绪，含产物
标识与下载入口提示，供前端渲染下载入口，MUST NOT 含凭据或一次性下载 grant
（grant 由按需铸造端点下发））、turn_done（本轮结束，payload MUST 携带
本轮真实轮次序号 `turn` 与本轮耗时 `duration_ms`；`turn` MUST NOT 使用
事件 seq 或其他计数器替代）、session_closed、error。SDK 类型与字段名 MUST NOT
泄漏到契约之外（业务层与前端只见自有事件）；未知事件类型 MUST 保留透传
（type=unknown，前端降级展示）。流式增量与完整文本块 MUST NOT 重复
产出（已产出 partial 增量的文本不再产出完整 text_delta 事件）。

#### Scenario: 消息轮产生完整事件序列

- **WHEN** 会话中一轮用户消息被处理
- **THEN** 前端按序收到该轮的 tool_call / tool_result / text_delta / turn_done
  事件，seq 单调递增且无空洞
- **THEN** 同一段文本不因流式增量与完整文本块双重产出而重复展示

#### Scenario: Agent 向用户提问

- **WHEN** Agent 在执行中需要用户补充信息（elicitation 请求，或本轮以
  提问文本结束而未发起任何工具调用）
- **THEN** 前端可识别出这是一次待用户补充的提问（事件型走 ask_user；
  本轮结束型由前端从本轮文本判定并呈现补充输入入口），任务等待用户回答；
  用户的回答作为下一轮输入回注同一会话并保持上下文

#### Scenario: 写入门禁拒绝事件

- **WHEN** Agent 的写入类工具调用被门禁 Hook 拒绝（gate_blocked 语义，
  详见 write-gate-isolation 能力）
- **THEN** 前端收到 gate_blocked 事件（含 tool_name 与目标提示），
  可渲染"等待用户确认"提示；用户确认后 Agent 可重试该调用

#### Scenario: 产物就绪事件

- **WHEN** Agent 产出可下载产物（落会话工作区 xlpa-output/，由后端 turn 收尾扫描
  检测；来源 B mcp_server 原生产物的自动检测一期不做、降级二期）
- **THEN** 前端收到 artifact 事件（含产物标识与下载入口提示），据此渲染下载入口
- **THEN** artifact 事件 MUST NOT 含凭据或一次性 grant；下载 grant 由按需铸造端点
  下发，实际下载经 web-artifact-delivery 的代理下载 + 一次性 grant 流程完成

#### Scenario: SDK 事件类型不外泄

- **WHEN** 检查事件契约与前端接口的响应结构
- **THEN** 不出现 SDK 的类型名（如 AssistantMessage/StreamEvent）作为契约字段

#### Scenario: turn_done 字段语义正确

- **WHEN** 一轮用户消息处理完毕，事件流写入 turn_done
- **THEN** 其 `turn` 等于本轮在会话内的轮次序号（首轮为 1），而非事件序号
- **THEN** 其 `duration_ms` 为本轮实际耗时，取值来自运行时而非缺省 0

### Requirement: 事件必须持久化并支持断线重放

事件流 MUST 由 webchat 后端持久化为自有事实源（按会话分区、seq 有序）；
SSE 下发 MUST 支持 `Last-Event-ID` 续传：客户端断线重连后 MUST 补齐
断线期间漏掉的事件；重放与实时下发 MUST NOT 产生 seq 冲突或重复投递
（同 seq 事件幂等）。实时下发 MUST 采用**增量读取**：建连时执行一次历史
回放并记录文件字节偏移，其后每次轮询 MUST 只读取该偏移之后的新增完整事件
行，MUST NOT 重读并解析整份历史；无新增事件时 MUST 直接返回而不打开事件
文件。服务端 MUST NOT 因单个连接的历史规模而放大实时轮询成本。

#### Scenario: 断线重连补齐

- **WHEN** 客户端在事件 seq=10 断线、任务继续推进至 seq=25 后重连并携带
  Last-Event-ID=10
- **THEN** 服务端按序补发 seq=11..25 的事件，随后无缝转入实时下发

#### Scenario: 刷新后回看完整过程

- **WHEN** 用户刷新页面或新设备进入同一会话
- **THEN** 前端可从持久化事件源回看该会话的全部历史事件（seq 从头重放）

#### Scenario: 大历史会话的实时轮询开销不随历史增长

- **WHEN** 一个已有上万条历史事件的会话保持 SSE 连接且暂无可下发事件
- **THEN** 每次轮询只做常量级判断，不重新读取与解析历史文件

#### Scenario: 写入中的半行不提前下发

- **WHEN** 事件追加尚未写完（末尾无换行符）
- **THEN** 该半行不下发，待完整行落盘后的下一次轮询才下发

### Requirement: 会话必须实施单写者租约

每个会话 MUST 至多有一个持有写租约的执行者（前端 15s 心跳、租约默认
45s TTL）；无租约或租约过期的连接 MUST 以只读旁观方式接收事件；
新连接 MUST NOT 并发写入同一会话；接管 MUST 先中断当前执行轮再转移
租约。

#### Scenario: 第二个标签页只读旁观

- **WHEN** 同一用户在第二个标签页打开同一会话（不持租约）
- **THEN** 第二标签页实时收到事件但无法发送消息
- **THEN** 第一标签页的执行不受干扰

#### Scenario: 租约失联自动释放

- **WHEN** 持有租约的连接停止心跳超过租约 TTL
- **THEN** 租约自动释放，后续连接可接管

### Requirement: 实例池必须有配额与明确拒绝语义

系统 MUST 实施资源上限：全局活跃会话上限（默认 100，可配）、每用户并发
会话上限（默认 5，可配）、单轮 max_turns 上限（默认 25）、并发执行轮次上限
（默认 16，可配）；达到上限时 MUST 返回明确的"繁忙/超限"响应（含建议重试
信息），MUST NOT 复用他人实例、MUST NOT 静默排队无限等待。并发执行轮次
达到上限时，发送消息 MUST 直接拒绝且 MUST NOT 拉起新的 CLI 子进程、MUST NOT
写入用户消息事件。

#### Scenario: 全局实例上限

- **WHEN** 活跃实例数达到全局上限且有新会话创建请求
- **THEN** 新请求被明确拒绝并提示繁忙，现有会话不受影响

#### Scenario: 单轮工具迭代上限

- **WHEN** 一轮对话的工具调用轮次达到 max_turns 上限
- **THEN** 运行中止并以 error 事件说明原因，会话可继续下一轮

#### Scenario: 并发轮次达到上限

- **WHEN** 正在执行的 Agent 轮次达到并发轮次上限，用户继续发送消息
- **THEN** 请求返回 409「系统繁忙，请稍后重试」，不创建新轮次、不拉起新进程

### Requirement: 会话工作区必须与会话绑定并受布局约束

每个会话 MUST 拥有独立工作区目录（布局含 xlpa-tmp/、xlpa-input/ 与
xlpa-output/，遵循 C1 约定）；工作区路径 MUST 由后端分配，MUST NOT 由客户端
指定（防路径逃逸）；会话结束后工作区内容按保留策略处置（保留期由
web-artifact-delivery 能力按 cleanup.py 分类定义并接入清理：temp 会话销毁即清、
result/template 30 天、sensitive_temp 任务终态后 7 天、input 30 天、audit 不清、
未知分类一律保留；本能力只声明"会话结束不删除、按目录隔离"，保留机制归
web-artifact-delivery）。

#### Scenario: 工作区按会话隔离

- **WHEN** 两个并发会话各自产生作业产物
- **THEN** 产物分别落位各自工作区的 xlpa-output/，互不可见

### Requirement: 会话事件流必须与会话凭据解耦

任务执行 MUST 与浏览器连接解耦：连接断开时运行中的任务 MUST 继续执行并
持续产生事件（写入持久化事件源）；重连后按重放语义补看。会话票据校验
MUST 先于 SSE 订阅（无票据或票据过期拒绝订阅）。

#### Scenario: 断线不中断任务

- **WHEN** 用户在任务执行中关闭浏览器
- **THEN** 任务继续执行至本轮结束，事件持续入库；用户重连后可看到全部过程

### Requirement: Web 会话运行时必须由国内版 Qoder Agent SDK 构建驱动

Web 会话运行时 MUST 由**国内版（CN）构建**的 Qoder Agent SDK 驱动（导入名
`qodercn_agent_sdk`，自带 `qoderclicn` CLI，不依赖部署环境 PATH 提供
`qodercli`）；个人访问令牌（PAT）MUST 经国内版环境变量
`QODERCN_PERSONAL_ACCESS_TOKEN` 注入，且 MUST 仅经环境变量传递、不出现在
子进程命令行。SDK 品牌为构建期常量、MUST NOT 期望以环境变量在运行时切换；
PAT 品牌与 SDK 构建品牌 MUST 一致（不一致将会话初始化握手超时）。SDK 的
模块名与类型名 MUST 限于会话运行时的适配层边界内，MUST NOT 泄漏到事件契约
模块或前端接口（沿用既有“SDK 事件类型不外泄”约束）。

#### Scenario: 国内版 PAT 注入后会话成功初始化

- **WHEN** 运维以 `QODERCN_PERSONAL_ACCESS_TOKEN` 注入有效国内版 PAT 并创建
  会话
- **THEN** 会话实例完成初始化握手（CLI 就绪），可处理用户消息并产生事件流

#### Scenario: 自带 CLI 不依赖 PATH

- **WHEN** 部署环境未在 PATH 提供 `qodercli`
- **THEN** 会话仍能启动（国内版 SDK 自带 `qoderclicn` CLI），不因缺少外部
  CLI 而失败

#### Scenario: SDK 名称限于适配层边界

- **WHEN** 检查事件契约模块与前端接口的源码/响应结构
- **THEN** 不出现国内版 SDK 的模块名（`qodercn_agent_sdk`）或其类型名作为
  契约字段

### Requirement: 空闲会话必须自动回收

系统 MUST 跟踪会话最后活动时间；最后活动超过可配置空闲阈值（默认 1800 秒）
且当前无执行中轮次时，MUST 自动结束该会话。回收 MUST 采用 close 语义：撤销
会话凭据、释放实例槽位、写入 `session_closed` 事件（含 `reason=idle`），
MUST NOT 物理删除会话工作区与已登记产物（仍按保留期留存）。消息发送、租约
心跳、写入确认、SSE 连接存在、上传与下载均 MUST 刷新活动时间；执行中的轮次
MUST 跳过回收。

#### Scenario: 浏览器关闭后的会话被回收

- **WHEN** 用户关闭浏览器且超过空闲阈值未再操作该会话
- **THEN** 该会话被自动结束，槽位释放给其他用户；工作区产物仍按保留期留存

#### Scenario: 页面仍开着的会话不被回收

- **WHEN** 会话的 SSE 连接持续存在（页面未关闭）
- **THEN** 活动时间持续刷新，不触发空闲回收

#### Scenario: 执行中的轮次不被回收

- **WHEN** 会话正在执行 Agent 轮次且已超过空闲阈值
- **THEN** 本轮不被打断，轮次结束后再按空闲规则处理

### Requirement: 确认与凭据收集必须由前端卡片先行

Web 会话 MUST 在 Agent 首次调用**登记了入参**的受门禁工具（如 `edge_get_token`
需现场收凭据）时即渲染参数卡片，供用户在卡片内填写凭据与确认，MUST NOT 要求
用户先通过聊天文本提供敏感凭据（密码/短信验证码）。

对**无需补参、仅需确认**的写入，门禁 deny 后系统 MUST 通过系统提示告知 Agent：
先在会话流播报将执行的操作与关键参数摘要，并请求用户回复口令 `/确认`，MUST NOT
自行假定已授权、MUST NOT 以"调用一次即视为已确认"继续。会话一次 MUST 只挂一个
待确认目标；`/确认` 仅认作用户消息**行首**，其它文本按普通消息处理，MUST NOT 误判
为授权；用户不回 `/确认` 即视为不授权，写入 MUST NOT 发生。

卡片提交与口令 `/确认` 都 MUST 经既有 confirm 端点铸票后由系统续跑，MUST NOT 由
模型自铸票据。续跑若登记时本轮仍在执行（`turn_running`），系统 MUST 把续跑登记为
待办并在本轮 `turn_done` 补发，MUST NOT 丢弃并指望模型自纠重试。

#### Scenario: 请求边缘设备树时卡片先行

- **WHEN** 用户请求读取某边缘后端设备树，而会话尚未提供该环境凭据
- **THEN** Agent 直接调用 `edge_get_token`，前端立即出现参数卡片，用户可在
  卡片内填写账号、密码、验证码并提交，无需先在聊天中粘贴凭据

#### Scenario: 卡片提交自动铸票续跑

- **WHEN** 用户在卡片内填写必填参数并点击「确认并提交」
- **THEN** 后端铸造该目标的一次性窗口票据，并把所填参数随续跑消息发给 Agent，
  Agent 重试调用时在窗口内放行

#### Scenario: 无参写入经会话口令请求确认

- **WHEN** Agent 需要执行一项无需补参的写入而被门禁拦下
- **THEN** Agent 在会话流播报操作与参数摘要并请求用户回复 `/确认`，MUST NOT
  自行假定已授权；用户回复行首 `/确认` 后铸票续跑，用户不回复则写入不发生

#### Scenario: 确认落在执行中轮次时于 turn_done 补发续跑

- **WHEN** 用户在 `turn_running` 期间完成确认（卡片提交或口令）
- **THEN** 续跑被登记为待办并在本轮 `turn_done` 自动补发，MUST NOT 因"本轮还在跑"
  而丢弃续跑、指望模型自纠

#### Scenario: Agent 不得引导聊天确认

- **WHEN** 授权流程涉及密码/短信验证码等敏感凭据，或涉及 `login` 等绝对禁止
  类工具
- **THEN** Agent 的回复 MUST 引导用户经参数卡片操作，MUST NOT 声称在聊天中粘贴
  凭据或回复"确认"即可授权此类操作；仅**无需补参、仅需确认**的写入方可走会话
  口令 `/确认`，且敏感凭据 MUST NOT 借 `/确认` 口令索要，绝对禁止类 MUST NOT 因
  任何口令被授权

### Requirement: 会话接入凭据必须完成平台授权激活

webchat 为会话签发的接入凭据 MUST 在会话对用户可用之前完成平台登录绑定，
使该凭据发起的云端工具调用不处于未登录态。激活 MUST 由后端使用账号已预设
的凭据自动完成，MUST NOT 要求用户在页面输入手机号或短信验证码。激活失败
MUST 使会话创建明确失败并向用户给出可辨识原因，MUST NOT 返回一个可对话、
但任何云端操作都会被拒绝的会话。

Agent MUST NOT 调用 `login` 工具，MUST NOT 在对话中索要平台手机号或短信
验证码；`login` 门禁保持绝对禁止。系统提示与技能文档 MUST 与预激活事实
一致；若云端工具返回认证失效，Agent MUST 如实告知用户并由服务端重新激活，
MUST NOT 降级为 Agent 登录或向用户索取凭据。

#### Scenario: 新建会话可直接执行云端只读

- **WHEN** 用户创建会话后首次要求查询云端数据
- **THEN** agent 的工具调用返回真实数据，事件流不出现「需先登录」类拒绝，
  agent 也不向用户索取手机号或验证码

#### Scenario: 激活不向用户索取凭据

- **WHEN** 用户以账号密码登录 webchat 并创建会话
- **THEN** 全流程不出现要求用户补充平台手机号或短信验证码的环节

#### Scenario: 激活失败不留下不可用会话

- **WHEN** 会话创建过程中的平台授权激活失败
- **THEN** 创建请求返回失败且不产生可用会话，前端展示明确原因，
  不出现「会话已就绪但一查就报错」的状态

#### Scenario: Agent 不调用 login

- **WHEN** 用户请求云端只读数据
- **THEN** Agent 直接调用 `get_*` 工具，不调用 `login`，也不要求用户提供
  手机号或验证码；若遇认证失效则如实告知并由服务端重新激活

### Requirement: 技能必须从 canonical 目录索引并按需注入

Web 会话启动时 MUST 读取 `agent_assets/skills`（或 `WEBCHAT_SKILLS_ROOT`
指定目录）下各 `SKILL.md` 的 name/description/when_to_use，形成索引写入
系统提示，并 MUST 给出每个 SKILL.md 的真实路径。模型 MUST 能通过内置 Read
按需读取全文。用户消息以 `/技能名` 开头时，该技能 SKILL.md 全文 MUST 在
**当轮**注入；未匹配的前缀 MUST 按普通文本处理，不得误注入其他技能。
技能来源 MUST NOT 使用仓库 `.qoder/skills` 等客户端副本。

#### Scenario: 用户显式 /xlpa 提问

- **WHEN** 用户发送 `/xlpa 帮我生成脚本`
- **THEN** 本轮用户消息前包含 canonical `xlpa/SKILL.md` 全文，且系统提示含技能索引

#### Scenario: 普通消息不注入

- **WHEN** 用户发送不带技能前缀的普通消息
- **THEN** 不注入任何技能全文，行为与存量会话一致

#### Scenario: 技能目录缺失

- **WHEN** 技能母本目录不存在或不可读
- **THEN** 服务仍可启动，系统提示明确说明未发现技能目录，不得伪造技能内容

### Requirement: 内置只读工具必须受根目录白名单约束

系统 MUST 暴露内置 `Read`，且仅当路径经 `resolve()` 后位于会话工作区、
canonical 技能目录或配置的额外白名单目录内时放行。额外白名单 MUST 默认
包含 CLI 大结果落盘目录（`%TEMP%/qoder-mcp-outputs` 与
`~/.qoder-cn/tmp`），并 MUST 支持 `WEBCHAT_READ_EXTRA_ROOTS` 追加
（逗号或分号分隔）。越界路径、目录穿越、缺参或未配置可读根目录 MUST 一律
拒绝，且 MUST NOT 经用户确认解除。事件库、其他会话工作区、仓库密钥与
MCP 配置 MUST 保持在白名单之外。

#### Scenario: 读取技能手册

- **WHEN** Agent 调用 `Read` 读取 `agent_assets/skills/xlpa/SKILL.md`
- **THEN** 放行并记审计

#### Scenario: 读取仓库敏感文件

- **WHEN** Agent 调用 `Read` 读取白名单之外的仓库文件（如 `.env`、
  `permissions.json` 或事件库）
- **THEN** 拒绝并产 `gate_blocked` 事件（`guard=read_path`、不可确认解除）

#### Scenario: 读取 CLI 大结果落盘文件

- **WHEN** MCP 工具结果过大，CLI 将其落盘到 `%TEMP%/qoder-mcp-outputs` 或
  `~/.qoder-cn/tmp` 并让 Agent 读取
- **THEN** 放行并返回文件内容，不再出现“操作被禁止: Read”红卡

#### Scenario: 其他会话仍不可读

- **WHEN** Agent 尝试读取另一个会话的工作区或事件库
- **THEN** 拒绝并产 `gate_blocked` 事件，不得跨会话读取

### Requirement: 同一会话的轮次必须串行

同一会话在一个轮次执行期间 MUST NOT 接受新的用户消息；服务端 MUST 返回
409 并提示「上一轮仍在执行，请稍候」，不得排队、不得拉起第二个 CLI 轮次。
确认端点 MUST 在响应中给出当前会话是否仍有执行中轮次；前端在该轮仍在执行
时 MUST NOT 自动发送续跑消息。

#### Scenario: 执行中重复发送

- **WHEN** 上一轮仍在执行时用户再次发送消息
- **THEN** 返回 409，事件流不出现重复或缺失的轮次序号

#### Scenario: 执行中确认写入

- **WHEN** 轮次仍在执行时用户在确认卡片上确认
- **THEN** 票据照常铸造，前端不自动续跑，提示助手将在当前轮重试

### Requirement: 执行中的任务必须可中止

Web 会话 MUST 支持中止当前任务：`POST /api/sessions/{id}/abort`（租约校验）
MUST 取消当前轮次并调用 `QoderSDKClient.interrupt()`；本轮因中断产生的
`error_during_execution` 结果 MUST 映射为 `turn_aborted` 事件，MUST NOT 记为
普通错误。中止 MUST 复位 `turn_running`、清理本会话旧确认票据，并 MUST NOT
断开客户端，以便同一会话继续下一轮。

中止流程 MUST 先使用会话 MCP Token 请求服务端建档批次中止
（`POST /api/archive/tasks/{task_id}/cancel`）；服务端 MUST 在当前工作单元
完成后停止并返回 `cancelled=true`、`cursor`、`remaining` 与 `report_id`。
中止 MUST NOT 自动回滚已完成的写入，补偿清单 MUST 保留可查。当 `interrupt()`
失败或超时，流程 MUST 回退到取消轮次任务的兜底路径并产生说明原因的 `error`
事件，MUST NOT 静默挂起。

#### Scenario: 中止执行中的轮次

- **WHEN** 轮次正在执行时用户点击「停止」
- **THEN** 轮次被中断，事件流出现 `turn_aborted`，界面不再显示“执行中”
- **THEN** 同一会话随后发送的新消息可正常执行

#### Scenario: 中止服务端建档批次

- **WHEN** 客户端超时但 MCP 服务端仍在执行建档批次
- **THEN** 取消请求使服务端在当前单元后停止，返回 `cancelled=true` 与续跑游标，
  已建设备与补偿清单保留

#### Scenario: 中止后旧确认不生效

- **WHEN** 中止完成后再调用此前已确认的写工具
- **THEN** 旧票据已清理，需重新确认后才放行

### Requirement: 外部检索与协议助手的路由必须可判定且前缀可选

Web 会话 MUST 向模型暴露内置 `WebSearch` 工具（由门禁显式放行并记审计），使外部
公开资料可被检索；MUST NOT 暴露 `WebFetch`、`Bash` 等可拉取任意 URL 或执行命令的
工具。系统提示 MUST 声明路由边界：平台数据、设备、建档、参数下发、协议转换与边缘
操作 MUST 走 xlpa MCP 工具；公开协议标准、厂商手册、行业信息与用户给定 URL 的公开
内容 MUST 走 WebSearch；两者都需要的任务可先检索资料再用 MCP 落地。无法判定时
MUST 默认按 xlpa 理解或向用户澄清，MUST NOT 静默把内部业务内容发往外部检索。

路由 MUST 支持可选前缀 `/web` 与 `/xlpa`：仅对当前一条消息强制指定路由，执行前
MUST 从任务文本中剥离；不带前缀时 MUST 自动判定。前缀 MUST NOT 改变会话模式、
MUST NOT 要求用户每次输入都携带。系统提示 MUST 禁止把凭据（账号/密码/验证码/
Token）、设备地址与内部协议文档原文送入 WebSearch；需要检索内部相关内容时 MUST
先脱敏或征得用户确认。检索失败或不可用时，Agent MUST 如实告知用户，MUST NOT 以
模型记忆冒充检索结果。

#### Scenario: 外部协议标准问题走网页检索

- **WHEN** 用户询问"Modbus TCP 默认端口是多少"或要求查阅公开协议标准
- **THEN** Agent 调用 `WebSearch` 并基于检索结果回答（附来源），不调用 xlpa 写工具

#### Scenario: 平台设备问题走 xlpa

- **WHEN** 用户询问某边缘网关上存在哪些设备
- **THEN** Agent 走 xlpa MCP 工具（必要时先经确认卡片获取凭据），不调用 WebSearch

#### Scenario: 前缀强制路由

- **WHEN** 用户发送 `/web <任务>` 或 `/xlpa <任务>`
- **THEN** 本次消息按指定路由执行，前缀在任务文本中被剥离，后续消息恢复自动判定

#### Scenario: 前缀边界

- **WHEN** 用户发送 `/web`（无任务）、在消息中间出现 `/web`，或使用未约定的 `/xxx`
- **THEN** 无任务时追问检索主题；非开头的 `/` 与其他 `/xxx` 均按普通文本处理，
  不触发路由覆盖

#### Scenario: 混合任务先检索后执行

- **WHEN** 用户要求"先查某公开协议规范，再在平台上创建对应类型"
- **THEN** Agent 先调用 WebSearch 获取公开资料，再用 xlpa MCP 工具执行平台操作

#### Scenario: 内部信息不得外发

- **WHEN** 用户要求检索的内容包含账号、密码、设备地址或内部协议文档原文
- **THEN** Agent 先脱敏或向用户确认，MUST NOT 原样送入 WebSearch

### Requirement: 会话运行时必须持有一个持久 SDK 客户端

每个 Web 会话 MUST 绑定恰好一个持久的 `QoderSDKClient` 实例：会话创建时
`connect()`，会话结束或空闲回收时 `disconnect()`；同一会话的多个轮次 MUST
复用同一客户端，MUST NOT 每轮重新拉起 CLI 进程。客户端 MUST 在其 `connect()`
所在的同一 asyncio 上下文内使用；MUST NOT 跨事件循环或跨任务组共享。客户端实例
MUST 限于适配层内，MUST NOT 泄漏到事件契约或前端接口。

#### Scenario: 多轮复用同一客户端

- **WHEN** 同一会话连续执行两轮用户消息
- **THEN** 两轮由同一客户端实例处理，第二轮的 `session_id` 与第一轮一致
- **THEN** 不出现每轮新建 CLI 子进程的行为

#### Scenario: 会话结束释放客户端

- **WHEN** 用户结束会话或会话被空闲回收
- **THEN** 该客户端 `disconnect()`，CLI 实例终止，接入凭据按既有契约撤销

### Requirement: 每会话必须只有一个消息接收循环

每个客户端 MUST 只启动一个常驻 `receive_messages()` 接收循环，跨轮持续接收；
轮次逻辑 MUST NOT 自行新建第二个接收循环。接收循环 MUST 把消息按本轮归属归类后
再归一化为事件契约 v1，MUST NOT 把上一轮尾部消息计入下一轮。接收循环异常退出
MUST 产生 `error` 事件并使该会话进入明确的不可继续状态，MUST NOT 静默丢弃消息。

#### Scenario: 单接收循环跨两轮

- **WHEN** 同一会话依次发送两条消息
- **THEN** 一个接收循环连续消费两轮消息，两轮各自的 `turn_done` 均按序产生
- **THEN** 两轮事件归属无交叉、无丢失

#### Scenario: 接收循环异常

- **WHEN** 接收循环因 SDK 异常退出
- **THEN** 事件流出现 `error` 事件说明接收中断，后续发送消息被明确拒绝而非挂起

### Requirement: 中断后同一会话必须可继续

`interrupt()` 成功结束当前轮后，同一会话 MUST 可继续发送下一轮消息，且模型
MUST 能引用中断前已完成的对话上下文；`session_id` MUST 保持不变。空闲状态下
调用中止 MUST 安全返回，MUST NOT 破坏会话。中断 MUST NOT 自动断开客户端。
中断 MUST NOT 被假定为能停止已进入执行的 MCP 工具调用：中止流程 MUST 继续通过
服务端批次取消契约止损，已完成的写入不回滚。

#### Scenario: 中断后继续并保留上下文

- **WHEN** 一轮执行中被告知中止，随后用户在同一会话发送新消息
- **THEN** 新轮次正常返回，且能基于中断前的对话内容作答
- **THEN** 会话 `session_id` 与中断前一致

#### Scenario: 空闲置停

- **WHEN** 会话空闲时收到中止请求
- **THEN** 接口安全返回，随后发送消息仍可正常执行

#### Scenario: 中断不停止已执行的 MCP 工具

- **WHEN** 中断发生在某个 MCP 写工具已开始执行之后
- **THEN** 轮次立即结束，但该工具可能仍完成；服务端取消契约为 MUST 保留项，
  补偿清单可查

### Requirement: 流式增量与完整文本必须去重

启用流式 partial 消息时，事件层 MUST 对同一段文本只产出一次：存在增量时
MUST 仅由增量产出 `text_delta`，随后到达的完整文本 MUST NOT 再次产出；无增量
到达时 MUST 以完整文本兜底产出一条 `text_delta`。该规则 MUST 在长文本、多工具
连续轮次下同样成立。

#### Scenario: 短回复不重复

- **WHEN** 一轮回复产生 1 个增量且随后到达内容相同的完整文本消息
- **THEN** 前端只收到一条对应的 `text_delta`，不出现重复展示

#### Scenario: 无增量时兜底

- **WHEN** 本轮未产生任何增量（例如仅工具调用或极短回复）
- **THEN** 完整文本仍以一条 `text_delta` 产出，文本不丢失
