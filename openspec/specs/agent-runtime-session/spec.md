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

Web 会话 MUST 在 Agent 首次调用受门禁保护的工具（含 `edge_get_token`）时即渲染
确认/参数卡片，供用户在当前卡片内填写凭据与确认，MUST NOT 要求用户先通过聊天
文本提供凭据再触发卡片。系统 MUST 通过系统提示告知 Agent：需要确认或凭据时直接
调用相应工具（缺失参数可留空）以触发表单，MUST NOT 在聊天中索要密码或验证码，
MUST NOT 要求用户以聊天回复"确认"作为授权方式。卡片提交后，MUST 由既有 confirm
端点铸票并自动携带所填参数续跑，无需用户再次输入。

#### Scenario: 请求边缘设备树时卡片先行

- **WHEN** 用户请求读取某边缘后端设备树，而会话尚未提供该环境凭据
- **THEN** Agent 直接调用 `edge_get_token`，前端立即出现确认/参数卡片，
  用户可在卡片内填写账号、密码、验证码并提交，无需先在聊天中粘贴凭据

#### Scenario: 卡片提交自动铸票续跑

- **WHEN** 用户在卡片内填写必填参数并点击「确认并提交」
- **THEN** 后端铸造该目标的一次性窗口票据，并把所填参数随续跑消息发给 Agent，
  Agent 重试调用时在窗口内放行

#### Scenario: Agent 不得引导聊天确认

- **WHEN** Agent 需要用户授权某受门禁工具
- **THEN** 其回复 MUST 引导用户使用确认卡片，MUST NOT 声称"回复确认"即可授权

### Requirement: 会话接入凭据必须完成平台授权激活

webchat 为会话签发的接入凭据 MUST 在会话对用户可用之前完成平台登录绑定，
使该凭据发起的云端工具调用不处于未登录态。激活 MUST 由后端使用账号已预设
的凭据自动完成，MUST NOT 要求用户在页面输入手机号或短信验证码。激活失败
MUST 使会话创建明确失败并向用户给出可辨识原因，MUST NOT 返回一个可对话、
但任何云端操作都会被拒绝的会话。

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
