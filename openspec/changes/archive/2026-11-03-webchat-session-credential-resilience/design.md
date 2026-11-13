## Context

动机见 `proposal.md - Why`。当前状态与约束：

- 两条彼此独立的计时器共同导致长建档会话卡死：
  - **门禁票据（grant）**：`webchat/webchat/grants.py` `GrantStore`，键为
    `(session_id, target)`，`target` 由 `resolve_target` 取 `plan_id/task_id`
    或工具名；默认 TTL 300s（`WEBCHAT_GRANT_TTL`），原语义"窗口内可复用但
    放行不延长"。
  - **MCP 接入 Token**：`mcp_server/server.py` `TokenManager`，webchat 族签发时
    带绝对 `expires_at`（默认 `MINT_TTL_DEFAULT=7200`，上限 `MINT_TTL_CAP=86400`）；
    `AuthMiddleware` 每次 `/mcp` 请求先 `is_valid` 再 `touch_token`，但原
    `touch_token` 只更新 `lastSeenAt`、不动 `expires_at`。
- 前端 `webchat/webchat/static/js/app.js` `renderGateCard` 对 `gate_blocked`
  一律弹卡；非 `guard` 事件还 `hideBusy()` 暂停转圈，绝对禁止类（`login`）
  因此会打断进度。
- 包边界纪律：`grants.py` 不 import `mcp_server`；接入 Token 的滑动续期落在
  MCP Server 侧即可，webchat 后端无需改动换发逻辑。

## Goals / Non-Goals

**Goals:**
- 持续活跃/持续写入的会话不再因固定窗口或绝对死线中途失效。
- 保留安全阀：闲置满窗口后凭据/票据自然回收；接入 Token 有绝对寿命封顶。
- 确认卡只对"需用户决策"的拦截弹出并暂停；其余降级为不打断的弱提示。
- 铸票唯一入口仍是卡片确认手势（安全底线不动）。

**Non-Goals:**
- 不重划 42 个门控写入工具的集合（"名为 write 实为 read"的分级留待后续）。
- 不改前端铸票/续跑协议与后端 confirm 端点契约。
- 不引入 Token 主动换发/refresh 端点（滑动续期已消除对换发入口的需求）。
- 不动 IDE 族凭据的长期有效语义。

## Decisions

1. **接入 Token 滑动续期 + 绝对封顶**（Q1=c）：在 `touch_token` 内按签发窗口
   顺延 `expires_at = min(now + window, createdAt + MINT_TTL_CAP)`，`mint_token`
   额外存 `ttl_seconds` 作为窗口来源（旧 registry 无该字段时以
   `expires_at - createdAt` 回推）。
   - 窗口来源 `ttl_seconds` MUST 在 `_normalize_entry`/load 往返中保留；回推
     仅限未记录过窗口的历史条目，已有窗口不得被归一化丢弃（否则重启后退化为复利放大）。
   - 为什么服务端改而非 webchat 换发：`AuthMiddleware` 已在每请求调
     `touch_token`，续期就近生效，客户端零改动、无新端点。
   - 备选：仅放大绝对 TTL（长任务仍会撞墙，只是推后）——否决。
2. **门禁票据滑动消费**（Q2=a）：`GrantStore.check` 命中放行即
   `expires_at = now + ttl_seconds`。写入流不断票据不死，停手满 TTL 回收。
   - 备选：任务级永不过期票据（去时间边界，风险大）、仅调大 TTL——均否决。
   - 现有测试 `test_execution_failure_does_not_refund_or_extend`（单次放行后停手
     仍在原边界过期）语义不变，另补滑动续期用例。
3. **确认卡触发面收窄**（Q3=a、Q4=c、Q5=a）：`gate_blocked` 分流判据
   `blocking = !guard && confirmable !== false`；仅 blocking 才 `hideBusy` 并弹卡。
   `confirmable === false`（login/`read_path`）走 `renderForbiddenNotice` 一行弱提示。
   后端语义与事件不变，纯前端渲染分流。

## Risks / Trade-offs

- [滑动续期让活跃凭据更长寿，扩大被盗凭据的可用时间窗] → 绝对封顶
  `createdAt + MINT_TTL_CAP` 硬约束总寿命；webchat 会话本身仍受闲置回收
  （`session_idle_ttl`）约束，会话结束即撤销凭据。
- [票据滑动延长授权窗口，理论上放宽"一次确认"的时间边界] → 仅在"确有放行写入"
  时顺延，非空闲延长；停手满 TTL 立即回收，安全阀保留。
- [旧 registry 条目缺 `ttl_seconds`，首帧窗口由 `expires_at-createdAt` 回推] →
  归一化/加载路径若不透传 `ttl_seconds`，重启后会丢窗口并退化为回推复利；
  故 `_normalize_entry` 字段清单显式保留 `ttl_seconds`，仅未记录过窗口的历史
  条目走一次性回推，并补重载保留测试；IDE 族不参与续期。
- [把 login/读越界降级为弱提示，用户可见度下降] → 弱提示仍保留拒绝原因与计数，
  事件流与审计台账照旧记录，可观测性不丢。

## Migration Plan

- 无需数据迁移：`ttl_seconds` 为新增可选字段，缺省时回退推导；registry 结构向后兼容。
- 部署：MCP Server 与 webchat 各自重启加载新代码即可；无需清 registry。
- 回滚：还原 `touch_token`/`check`/`app.js` 三处改动即回到固定窗口/绝对到期语义。
