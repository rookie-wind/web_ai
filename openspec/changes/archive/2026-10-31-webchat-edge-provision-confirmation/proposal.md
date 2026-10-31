## Why

webchat 会话内"仅读取某边缘后端设备档案/设备树"的请求当前**结构性无法完成**：
建立边缘会话、返回读取类 `edge_*` 工具所需 `task_id` 的唯一免模板入口
`edge_get_token`，被 `write-gate-isolation` 现有契约与 `LOGIN_TOOL_NAMES` 一并
列为"登录类工具"予以**绝对禁止**（`PreToolUse` 无条件 deny、不进入票据校验），
而该禁令的安防前提（"会话已持凭据"）只对云平台业务登录 `login` 成立——webchat
会话并不持有边缘后端账号密码。同时，被绝对禁止的调用仍会触发前端"确认"卡片与
后端铸票，铸出一张永不参与校验的孤儿票据，使**用户确认成为空操作**。该问题在
多起真实会话事件/审计台账中 100% 复现，是既有公理的必然产物而非偶发缺陷。

## What Changes

- **重分类 `edge_get_token`（BREAKING，降低一条被测试锁定的安全边界）**：
  从"登录类绝对禁止"改为**"需人类确认"类（provision）**——`PreToolUse` 无 grant
  时仍 deny 并给出确认提示，用户经 confirm 端点铸票后在 TTL 窗口内放行，返回
  `task_id`。`login`（云平台业务登录）**保持绝对禁止不变**。
- **门禁拒绝语义分层**：`gate_blocked` 事件 payload 增加**"是否可经确认解除"**
  标记；区分"需确认（confirm-required）"与"绝对禁止（forbidden）"两类拒绝。
- **消除空操作确认**：前端仅对"需确认"类渲染确认按钮；"绝对禁止"类改为明示
  "该操作被策略禁止，无法通过确认解除"，后端铸票端对不可解除目标拒绝铸票。
- 同步更新防漂移单测断言与门禁注释，新增 provision 放行用例。

**不在本次范围**：修复 `adapter` 流式模式下 `tool_call` 入参不回填、`tool_result`
不落盘的可观测性缺陷（该项会改变 password 是否进入事件流的落盘面，单独评估）。

## Capabilities

### New Capabilities
- 无

### Modified Capabilities
- `write-gate-isolation`: "运行时工具面必须收敛为 MCP 工具且登录类工具禁用"
  要求拆分——`edge_get_token` 由绝对禁止改为需确认放行，`login` 维持禁止；
  并新增"门禁拒绝须区分需确认与绝对禁止两类语义、绝对禁止不得触发确认与铸票"
  的要求。

## Impact

- 代码：`webchat/webchat/grants.py`（`LOGIN_TOOL_NAMES`/新增 provision 集合/
  `classify_tool`/`WriteGate.decide`/`_deny`）、`webchat/webchat/runtime.py`
  （`confirm_grant` 铸票校验）、`webchat/webchat/sessions_api.py`（confirm 端点）、
  `webchat/webchat/static/js/app.js`（`renderGateCard`）。
- 测试：`webchat/tests/test_grants.py`（防漂移断言必改、补 provision 用例；
  无票 deny 断言保持不变）、`webchat/tests/test_gate_hook.py`（无票 deny 断言
  保持不变）。
- 既有归档契约：`openspec/specs/write-gate-isolation/spec.md` 对应要求以 delta
  修订。
- 安全边界：webchat 内 `edge_get_token` 从"绝对禁用"降为"用户确认可放行"；
  仅影响 10.* 直连段（20.* 门户代理约束不变）。
- 不改动 `mcp_server/*`（服务端本就不拦 `edge_get_token`，属 `edge_util`）。
