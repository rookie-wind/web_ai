## 1. grant 存储与门禁核心

- [x] 1.1 实现 `webchat/webchat/grants.py`（GrantStore：mint/check/TTL 惰性过期/会话清理；**计划域窗口语义**——同目标窗口内可多次 check 通过；**消费时机**——放行即记消费、执行失败不退票；WEBCHAT_GRANT_TTL 默认 300s），单测覆盖铸造-窗口内多次放行-窗口过期拒绝-执行失败不退票-会话清理-异常 Fail-Closed
- [x] 1.2 定义 `WRITE_TOOL_NAMES`（云端 `write` 32 + 边缘 `edge_write` 10）与 `LOGIN_TOOL_NAMES`（`login`、`edge_get_token`）常量（来源注释锁定：server.py 注册表 `type` 字段），防漂移单测**按 `type` 正则解析 server.py 注册表**抽取 `{write, edge_write}` 与 `{login}`+`edge_get_token` 全集比对（同时覆盖云端与边缘、用符号/type 锚不用行号）
- [x] 1.3 adapter 增加 PreToolUse hook 构造与回调（写入验票 check + 登录类 deny + 未知/内置工具防御性 deny + 只读/规划/Skill 放行 + gate_blocked writer 回调 + 审计回调 + try/except 全包 Fail-Closed），单测用 fake `PreToolUseHookInput` 喂全分支断言（**不含路径白名单分支**——tools=[] 下无内置工具面）

## 2. 接线与端点

- [x] 2.1 runtime 接线（会话持 GrantStore、adapter 注入 writer 与审计回调、会话结束清理 grants），runtime 单测覆盖生命周期
- [x] 2.2 sessions_api 新增 `POST /api/sessions/{id}/confirm`（票据+租约校验、铸造 plan/task 或 tool_name 域 grant）；`events.EVENT_TYPES` 增加 `gate_blocked`；新增**独立门禁审计 JSONL**（confirm/allow/deny，不随会话生命周期清理）；TestClient 测试（非租约 409、确认后 Hook 放行链路 fake 联通、gate_blocked 事件入流与断线回放、审计台账落盘且会话结束后仍可查）
- [x] 2.3 webchat pytest 全量全绿（junit 存证到 validation/c4-write-gate-isolation/）

## 3. 验证与回归

- [x] 3.1 V7 探针（真实 SDK 会话 + 运行中 MCP Server）**全部 PASS**：**Part 2 确定性**——经生产 Hook 回调 `AgentHandle._pre_tool_use → WriteGate.decide` 覆盖全分支，16 次调用全对（无 grant deny / 有 grant allow / 窗口复用 / 边缘 plan_id 序列 / execute_archive_task stages+cursor / login deny / read allow / Bash deny / Skill allow / 窗口过期），时延 avg 0.004ms；**Part 1 实时端到端**——换装国内版 `qodercn-agent-sdk 1.0.17`（自带 qoderclicn.exe）+ 国内版 PAT，真实会话初始化成功、xlpa MCP `connected`、工具全加载，DeepSeek-Flash 实际发起结构化 `mcp__xlpa__add_brand` 调用 → 真实 Hook 触发（`hook_fired=true`）→ 无 grant **deny** → `gate_blocked` 入流 + 审计落 1 条（`denied_add_brand=true`），CLI 遵从拒绝、零数据写入（见 evidence-index §3.1/§3.2）。排查复盘：初跑 `tools_count=0` 的真凶是 MCP 鉴权（.env admin token 被拒 401 → `auth_required`），改用注册表 ide/user 级有效 token 后 connected；prompt 补全 add_brand 必填参数 + 强制不确认后模型即发起调用——两处均环境因素，非 C4 缺陷
- [x] 3.2 主 pytest 基线全绿（729 tests, 0 errors, 0 failures, 1 skipped）+ git diff 证明 mcp_server 零 C4 改动，存证
- [x] 3.3 IDE 回归：IDE 会话（无 Hook 挂接）行为不变（代码路径已由 `test_hooks_absent_when_no_gate` 覆盖；**用户人工验证通过**）
- [x] 3.4 证据索引 evidence-index.md 归集（含 V7 结论），供 html-ppt 汇报引用
