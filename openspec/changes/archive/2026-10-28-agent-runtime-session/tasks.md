## 1. mcp_server：Registry v3

- [x] 1.1 TokenManager 重构为 Token 主键（tokens: dict[token, entry] + ip_ide_token 索引；is_valid/touch 按 Token；get_or_create_token 保持 IDE 族按 IP 复用语义），新增 mint_token/revoke_webchat_token/ttl 校验，验证新增单元测试（同 IP 多凭据并存、webchat 族过期拒绝、IDE 族语义不变）通过
- [x] 1.2 v1/v2→v3 迁移（备份 tag=v2、逐条转 family=ide、损坏回退空表），验证迁移测试三态（v2 文件、v1 文件、损坏文件）+ 迁移后既有 Token 立即可用断言通过
- [x] 1.3 既有测试适配：test_auth_revamp / test_session_permission 等按 v3 语义更新，主 pytest 全绿（junit 存证到 validation/c3-agent-runtime-session/）→ 722/0/0/1
- [x] 1.4 owner_ref 接入操作日志审计分区（design D8）：AuthMiddleware 注入 owner_ref_var，_current_owner_id_server 优先 owner_ref（IDE 族回退 sha256(token) 现状），验证通过

## 2. mcp_server：mint / revoke 端点

- [x] 2.1 CompositeApp 新增 POST /api/mcp-token/mint 与 POST /api/mcp-token/revoke（X-Mint-Secret + WEBCHAT_ALLOWED_IPS 白名单 + 内存滑窗限流 + owner_ref/TTL 签发（默认 7200s，上限 86400，username strip 规范化）+ operation_log 审计；revoke 仅对 family=webchat 生效，IDE 族 403），验证新增 pytest 全过（401/403/429/签出可用/TTL/owner_ref/审计存在/IDE 族撤销被拒）→ 7 项
- [x] 2.2 端到端冒烟：起 MCP Server（测试环境变量），webchat 侧脚本走 mint→/mcp list_mcp_tools→revoke→/mcp 401 全链路，留证 → PASS（total=71）

## 3. webchat：SDK adapter 与补验

- [x] 3.1 sdk_runtime/adapter.py 落地（SDK 唯一 import 点、AgentHandle、实例启动参数按 design D3、事件归一化到自有契约 v1），验证 adapter 单元测试（用 fake SDK 消息流喂归一化断言）通过 → 4 项
- [x] 3.2 V2 探针（含技能加载来源，design D3/D6）：真实 SDK 会话验证（a）xlpa 入口路由可用，（b）能路由到 xlpa 之外子技能（device-archiving、protocol-conversion 至少各一），（c）setting_sources=[] 下技能母本可加载；留证 + 结论与回退决策 → PASS（a/b/c 全 true）
- [x] 3.3 V1b 探针：resume 语义验证（首轮→销毁实例→resume 重启→上下文保持断言），留证 + 回退决策记录 → PASS（resume_recalled=true，回退方案无需启用）
- [x] 3.4 冷启动采样：5 次实例启动→首事件耗时，留证 → 6.16~8.42s（均值 ~6.8s）

## 4. webchat：会话运行时

- [x] 4.1 事件存储（JSONL 按会话分区 + seq 单调 + 先落盘再广播 + partial/完整块去重），单元测试覆盖 seq 连续性、幂等重放与文本不重复产出
- [x] 4.2 会话管理器（1:1:1 绑定：会话→mint 凭据→实例→工作区；结束撤销凭据+终止实例+封存事件），单元测试用 fake adapter 覆盖生命周期（含配额竞态修复：active 按未关闭会话计数 + 信号量 wait_for 保底）
- [x] 4.3 租约（45s TTL/心跳续期/旁观/接管）与实例池（全局信号量+每用户上限默认 2+明确拒绝），单元测试覆盖租约抢占与配额超限
- [x] 4.4 会话 API 七路由（design D7）+ SSE（Last-Event-ID 重放 + :ping 心跳）+ C2 票据鉴权接线，TestClient 测试全过（含断线重连补齐、第二连接只读、无票据订阅 401）
- [x] 4.5 webchat pytest 全量全绿（junit 存证）→ 24/24

## 5. 端到端与回归取证

- [x] 5.1 真实端到端演练（需 MCP Server 与 webchat 同时运行）：登录→建会话→发消息（真实模型，只读任务如查工具列表）→收到完整事件流→断开 SSE→重连续传补齐→结束会话→凭据失效验证，全程留证（事件流 dump + 截图说明）→ PASS（26 事件，drill 临时账号已清理）
- [x] 5.2 并发隔离演练：两会话并发（fake 或真实），断言实例/凭据/工作区/事件流互不串扰，留证 → 单测覆盖 PASS
- [x] 5.3 主 pytest 基线最终全绿 + git diff 审查（/mcp 与 71 工具零行为改动确认），存证 → 729/0/0/1
- [x] 5.4 IDE 回归：接入页取 Token、既有 IDE Token 迁移后可用（人工验证，留记录）→ 用户 2026-10-28 确认两项均正常
- [x] 5.5 证据索引 evidence-index.md 归集（含 V1b/V2/冷启动结论与回退决策），供 html-ppt 汇报引用
