## Why

Web 路径的写入/下发类操作必须在用户于页面明确确认后才能执行，且"用户已确认"
必须由服务端持有事实、不依赖模型自述（需求交互要求 3，FR-5）。现状两道防线
都有缺口：模型自填的 `confirm=true` 可被幻觉或提示注入置真；agent 运行时
无边界，公网场景下存在越权写入与供应链污染风险（旧方案 D8）。C3 已交付会话
运行时与 webchat 族凭据，本变更在其之上加"服务端验票门禁 + 运行时隔离"。

两处必须正视的现实（评审已核实）：其一，建档是**多阶段/多台设备**闭环，若
grant 一次性消费会退化为"每步每台重确认"的确认风暴，验收判据"端到端走完
建档闭环"走不完；其二，C3 实例已设 `QoderAgentOptions.tools=[]`（SDK 序列
化为 `--tools ""`，内置文件/命令工具面为空），模型仅见 MCP 工具与
`Skill(xlpa)`——故本变更不重建路径白名单（无对应工具面，实现即死代码）。

## What Changes

- **计划域授权票据（grant，窗口语义）**：webchat 后端新增 grant 存储——用户
  在页面点击 [确认执行] 后，后端对该 `(session_id, target)` 铸一张计划域
  grant（`target` = plan_id/task_id 或 tool_name；默认 TTL 5 分钟，可配）；
  grant 在 TTL 窗口内**可被同一目标的多次调用复用**（覆盖 batch/cursor 分批
  续跑与共享 active_plan_id 的逐台 edge 写序列），一次确认覆盖整个已确认
  计划。放行即记消费、工具执行失败**不退票**（防重放窗口）；窗口过期后同
  目标写入需重新确认。
- **建档统一走一键编排入口**：webchat 建档执行 MUST 走 `execute_archive_task`
  （单工具、`stages="all"`、服务端编排全阶段，支持 batch/cursor 续跑）——
  一次调用、一张 plan/task 域 grant、一次确认覆盖整条建档闭环，杜绝确认风暴。
- **PreToolUse 写入门禁 Hook（V7 落地）**：SDK 实例的 `hooks.PreToolUse`
  以进程内回调挂接（V3 已验）；Hook 对写入类工具（`server.py` 注册表
  `type ∈ {write, edge_write}` 全集：云端 32 + 边缘 10）执行验票：
  - 目标在窗口内持有效 grant → allow（放行即记消费）；
  - 无 grant / 窗口过期 / 后端验票通道异常 → **deny（Fail-Closed）**；
  - 拒绝原因以工具错误形式回给模型（触发 ask_user/重新规划），同时以
    `gate_blocked` 事件入会话事件流（前端可见"等待用户确认"卡片）。
- **登录类工具禁用 + 防御性兜底（隔离）**：Hook 对登录类工具（`login`、
  `edge_get_token`）显式 deny（webchat 会话已持 C3 mint 的族凭据，禁对话内
  业务登录改角色）；对任何不在已知 MCP 工具集内的工具名（内置工具因配置
  漂移意外出现）防御性 deny。内置文件/命令工具面已由 C3 `tools=[]` 关闭，
  本变更不实现路径白名单（延至 C6 路线 A 按真实工具面设计）。
- **门禁配置由后端注入且位于工作区外**：Hook 逻辑全部在 webchat 后端进程内
  （SDK 进程内回调），不落任何 agent 可改写的工作区文件——结构性满足
  "门禁配置不得位于可写工作区"。
- **确认端点、事件与审计台账**：webchat 新增 `POST /api/sessions/{id}/confirm`
  （票据鉴权 + 租约持有者）铸造 grant；事件契约 v1 增加 `gate_blocked`
  事件类型（payload 含 tool_name 与 plan_id/task_id 提示）；新增**独立门禁
  审计台账**（JSONL，不随会话生命周期清理，记 confirm/allow/deny），供验收
  举证与汇报。
- 明确**不在本变更内**：前端确认卡片 UI 与参数摘要（C7）、产物代理下载
  （C5）、OCR（C5）、路线 A 路径/命令白名单（C6）。

## Capabilities

### New Capabilities

- `write-gate-isolation`: Web 会话写入门禁与运行时隔离——计划域 grant 的
  铸造/窗口消费/过期语义、建档一键编排入口、PreToolUse 验票与 Fail-Closed、
  登录类工具禁用与防御性兜底、`gate_blocked` 事件、独立审计台账、门禁与
  工作区的结构性隔离。

### Modified Capabilities

- `agent-runtime-session`: 事件契约 v1 的事件类型集合增加 `gate_blocked`；
  实例启动参数增加 hooks 注入（其余不变）。delta 修改"SDK 事件必须归一化
  为自有事件契约 v1"一条 Requirement。

## Impact

- **代码**：
  - `webchat/webchat/`：新增 `grants.py`（计划域票据存储 + 窗口语义 +
    消费时机）与门禁审计台账（JSONL 追加）；`sdk_runtime/adapter.py` 增加
    hooks 构造与验票/登录-deny/防御兜底回调；`runtime.py` 接线（会话持有
    grant 存储、注入 writer 与审计回调、结束清理 grants）；`sessions_api.py`
    新增 confirm 端点；`sessions.py`（或 events）事件类型集合扩展
    `gate_blocked`；
  - `mcp_server/`：**零改动**（验票全部在 webchat 侧；MCP Server 的
    `_validate_plan_guard`（plan_id+confirm）与 `_require_super` 原样保留，
    形成双保险）。
- **依赖**：无新依赖（Hook 为 SDK 既有能力，V3 已验）。
- **既有测试**：主 pytest 基线零影响（mcp_server 不动）；webchat pytest
  新增门禁用例（fake hook 输入喂验票/登录-deny/窗口复用断言；防漂移单测按
  `type` 解析 server.py 注册表比对 `WRITE_TOOL_NAMES`/`LOGIN_TOOL_NAMES`）。
- **前置验证**：V3 已 PASS（PreToolUse 含参拦截 + deny 阻断）；V7 需验
  "Hook 回调内查询 grant 的时延与正确性 + 建档闭环一次确认 + batch 续跑
  复用票据"（进程内回调直查内存，预期 <1ms，留证即可）。
- **风险**：deny 误伤（误判写入/登录工具）→ 集合按注册表 `type` 派生并单测
  比对；grant 不校验参数（用户确认"加品牌 X"模型可传 Y）→ MVP 接受，
  **C7 确认卡片带参数摘要兜底**（C7 硬依赖）；IDE 路径零影响（Hook 仅挂接
  webchat 的 SDK 实例）。
- **引用规范**：本变更全部工件以**符号/type 锚**（`WRITE_TOOLS`、
  `_validate_plan_guard`、`execute_archive_task`、`QoderAgentOptions.tools`、
  注册表 `type` 字段）表述，不用行号（两仓库副本行号已分叉）。
