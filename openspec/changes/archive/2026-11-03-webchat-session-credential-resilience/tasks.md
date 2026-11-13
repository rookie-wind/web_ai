## 1. 接入 Token 滑动续期（mcp_server）

- [x] 1.1 在 `mcp_server/tests/test_refactor.py::TestTokenRegistryV3` 先写**失败
  测试**（红）：monkeypatch `srv.MINT_TTL_CAP=86400`，`mint_token(..., ttl_seconds=7200)`
  后把 `expires_at` 压到 `now+100`，调 `touch_token` 断言 `expires_at≈now+7200`
  且 `lastSeenAt` 刷新；另断言 `now+7200 > createdAt+86400` 时封顶到
  `createdAt+86400`（前置：TokenManager 可注入 `MCP_TOKEN_REGISTRY_PATH`；
  判据：`pytest mcp_server/tests/test_refactor.py -k touch_token` 先红；依赖：无）
- [x] 1.2 实现滑动续期使 1.1 转绿（绿）：`mint_token` 存 `ttl_seconds`；
  `touch_token` 对 webchat 族 `expires_at = min(now + window, createdAt +
  MINT_TTL_CAP)`，`window` 取 `ttl_seconds`、缺省回退 `expires_at-createdAt`，
  IDE 族（无 `expires_at`）跳过（前置：1.1 红；判据：`pytest mcp_server/tests/
  test_refactor.py -k touch_token` 转绿；依赖：1.1）
- [x] 1.3 先写**失败测试**（红）：mint 带 `ttl_seconds` 的 webchat 凭据→写盘→
  用同一 registry 路径重建 `TokenManager`（触发 `_normalize_entry`/load）→断言
  `get_entry(tok)["ttl_seconds"]` 保留且 `touch_token` 后按原窗口顺延（非回推
  复利）（前置：1.2 已实现内存滑动；判据：`pytest mcp_server/tests/test_refactor.py
  -k "normalize or reload or roundtrip"` 先红；依赖：1.2）
- [x] 1.4 实现 registry 往返保留使 1.3 转绿（绿）：`_normalize_entry` 字段清单补
  `"ttl_seconds": int(entry.get("ttl_seconds", 0) or 0)`；legacy/迁移分支默认为 0
  （历史条目走一次性回推）（前置：1.3 红；判据：1.3 转绿 + `pytest mcp_server/
  tests -q` 全绿；依赖：1.3）

## 2. 门禁票据滑动消费（webchat）

- [x] 2.1 在 `webchat/tests/test_grants.py` 先写**失败测试**（红）：monkeypatch
  `grants_mod.time`，注入小 TTL，断言连续命中每次把到期顺延一个 TTL、停手满
  TTL 后过期；并复核既有 `test_single_shot_legacy`（有 target 无旧票据 mint→
  check 放行、二次仍放行）在新语义下仍成立（前置：`GrantStore` 可注入
  `ttl_seconds`；判据：在装有 `qodercn_agent_sdk` 的环境 `pytest webchat/tests/
  test_grants.py -k slide` 先红；本机无该 SDK 时用独立脚本 import
  `webchat.grants` 验证同款时序；依赖：无）
- [x] 2.2 实现滑动消费使 2.1 转绿（绿）：`GrantStore.check` 命中且未过期时
  `self._grants[key] = now + self.ttl_seconds` 再放行；同步更新 `grants.py`
  模块 docstring 为滑动消费语义（前置：2.1 红；判据：2.1 测试转绿、
  `test_execution_failure_does_not_refund_or_extend` 仍绿；依赖：2.1）

## 3. 确认卡触发面收窄（webchat 前端）

- [x] 3.1 在 `webchat/webchat/static/js/app.js` 落地分流：`case "gate_blocked"`
  仅在 `!guard && confirmable !== false` 时 `hideBusy()`；`renderGateCard` 将
  `confirmable === false` 分支前移到去重之前、改调新增的 `renderForbiddenNotice`
  （一行 `guard-line` 弱提示、按 `tool_name` 聚合计数、不打断转圈、不入待确认
  队列）（前置：无；判据：`node --check webchat/webchat/static/js/app.js` 通过；
  手动冒烟：在接入页触发 login 越界仅见弱提示、不弹暂停卡，触发写入门禁弹确认卡；
  依赖：无）

## 4. 文档与规格同步

- [x] 4.1 校验并同步三份主规格与本次 delta 一致：`openspec/specs/`
  下 `write-gate-isolation`、`mcp-token-management`、`web-chat-ui` 对应
  Requirement 与 delta 全量块内容对齐（前置：1~3 完成；判据：
  `openspec validate webchat-session-credential-resilience --strict` 通过；
  依赖：1、2、3）
- [x] 4.2 术语表与 ADR 落地检查：`GLOSSARY.md` 接入 Token/门禁票据等词条、
  `docs/adr/0001~0003` 存在且与本设计决策一致（判据：文件存在且内容匹配决策；
  依赖：1、2、3）

## 5. 集成与回归验证

- [x] 5.1 全量回归：在装有 `qodercn_agent_sdk` 的环境跑
  `pytest webchat/tests/test_grants.py -q` 与 `pytest mcp_server/tests -q` 全绿；
  复现原场景（多批 edge 写、跨 2h 活跃会话）验证不再出现确认风暴与 `-32001`
  （判据：两套测试全绿 + 场景复现无拦截死局；依赖：1、2、3）
- [x] 5.2 code-review 双轴（⟨skill:code-review⟩）：Standards 对照 `.qoder/rules`
  PEP8/257/484，Spec 对照本 change 三份 delta；仅机械/规则违规才修正后说明，
  否则原样输出（依赖：1、2、3、5.1）

## 6. 规范偏离收口（可选）

- [x] 6.1 给 `TokenManager.touch_token`、`GrantStore.check` 补 Google 风格
  `Args:`/`Returns:` docstring，`check` 摘要行改祈使语气（pep257 §2/§4）（前置：
  1.4、2.2 已实现；判据：无新增 lint 报错、docstring 段落齐全；依赖：1、2）
- [x] 6.2 修正 `app.js:26` 对 `state.guardNotices` 的注释（该表现收纳
  pdf/绝对禁止两类弱提示，不止“内置写入路径护栏”）（判据：注释与实际
  用途一致、`node --check webchat/webchat/static/js/app.js` 通过；依赖：3）
