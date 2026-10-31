## Context

见 proposal.md（Why）。设计输入均为已核实事实：

- 现有身份体系三件套：`permissions.py`（SuperAccountConfig / BusinessTokenCache /
  extract_account_identity）、`api_client.py`（`login(phoneNum, code)` →
  `/api/Auth/LoginByCode`，`PCA_API_BASE_URL` 环境变量，默认
  `https://18091.chinadny.com`）、`token_manager.py`（MCP 接入 Token，
  本变更不触碰）；
- 主 venv（Python 3.14.5）：仅有 mcp/uvicorn/httpx（`mcp_server/requirements.txt`
  共 3 项），**无 fastapi、无 argon2**；
- MCP Server 以 `CompositeApp` 裸 ASGI 复合路由承载 10 条非 MCP 端点
  （`server.py:2690-2784`），Bearer 鉴权范式已存在；
- 写权限事实源 `permissions.json`：`superAccounts.userIds/phones`，userId 或
  phone 任一命中即 super；
- 需求文档 DR-02：账号库条目 = username + password 哈希 + 绑定 phone/code；
  准入 ≠ 授权（沿用旧方案 D15）。

## Goals / Non-Goals

**Goals:**

- webchat 独立服务骨架（进程/venv/依赖/测试四隔离）+ 账号准入完整闭环
  （账密校验、票据、限流、业务凭据绑定、角色判定接口）；
- 为 C3 提供稳定的会话身份基座（票据、账号引用、owner_id 派生输入）。

**Non-Goals:**

- 不做前端页面（登录页属 C3+/C7 验收期）；
- 不做 MCP 接入凭据签发 / Registry v3 / mint（C3）；
- 不做票据与业务 Token 的落盘持久化（重启失效为既定语义，见 Risks）；
- 不做验证码/2FA、账号自助管理（改密走管理员编辑账号库 + 哈希工具）；
- 不动 `mcp_server/` 任何行为（含 `/mcp`、71 工具、TokenManager）。

## Decisions

### D1 框架：FastAPI + uvicorn，独立 venv

- 依赖：`webchat/requirements.txt` = fastapi、uvicorn、httpx（含 pytest 到
  dev 段）；venv 位置 `webchat/.venv`（`.gitignore` 的 `.venv/` 通配已覆盖）。
- *理由*：C3 起事件流（SSE）、实例池、SDK adapter 复杂度上升，FastAPI 的
  依赖注入与 TestClient 能力显著降低后续成本；独立 venv 是旧方案定稿结论
  （SDK/OCR 重依赖不污染 mcp_server 环境），C2 即建立避免 C3 迁移。
- *替代方案*（否决）：裸 ASGI 仿 CompositeApp——C2 能省依赖，但 C3+
  的路由/SSE/测试成本线性上升，得不偿失；复用主 venv——违反四隔离纪律。

### D2 密码哈希：PBKDF2-HMAC-SHA256（hashlib 标准库）

- 格式：`pbkdf2_sha256$<iterations>$<salt_b64url>$<hash_b64url>`，
  迭代默认 480,000（OWASP 2023 对 PBKDF2-SHA256 的建议下限量级），盐 16 字节
  `secrets.token_bytes`；校验用 `hmac.compare_digest` 恒时比较。
- 哈希工具：`python -m webchat.hash_password`（stdin 读密码，避免进命令行
  历史；输出哈希行）。
- *理由*：零新依赖（venv 最小化）、标准库可移植、OWASP 认可；argon2-cffi
  需新依赖且主平台收益有限。
- *否决*：SHA 系列“加盐哈希”自造方案——无 KDF 迭代，不符合现代口令存储要求。

### D3 会话票据：内存态 + TTL + 惰性过期

- 票据 = `secrets.token_urlsafe(32)`；服务端 `dict[token, Session]`，
  Session 含 username、签发/过期时间、业务凭据（business_token/userId/phone，
  内存持有）、角色判定结果（super 与否）；
- 校验为惰性过期（比对 expires_at，过期即删）；`WEBCHAT_SESSION_TTL`
  默认 12h；登出立即删除；重启全失效（记录在案的既定语义）。
- *理由*：C2 阶段无跨进程共享需求；C3 若引入实例池仍单进程持有票据，
  无需外置存储；持久化列为后续可选（Open Question 无——已定为不做）。

### D4 业务凭据绑定：webchat 直连平台 API，不经 /mcp

- 账密校验通过后，webchat 用绑定的 phone/code 直接 HTTP 调
  `/api/Auth/LoginByCode`（httpx，`PCA_API_BASE_URL` 语义沿用）；
  成功 → `extract_account_identity` 同款键位提取（本地复刻该纯函数，
  不 import mcp_server——跨包依赖违反隔离）userId/phone/token 存入 Session；
  失败 → 登录整体失败并明确报错（spec 场景：不得静默降级）。
- 角色判定：读 `WEBCHAT_PERMISSIONS_PATH`（默认 `../mcp_server/permissions.json`
  的解析绝对路径）解析 superAccounts，userId/phone 任一命中 → super；
  判定结果随 /me 返回。**判定只读该文件，不写、不缓存跨登录**（每次登录时
  重读，改配置即时生效）。
- *理由*：login MCP 工具需要 MCP 接入凭据，而接入凭据是登录后才签发的
  （鸡生蛋）；webchat 直连平台 API 与"后端只经 HTTP 回环 /mcp 调工具"纪律
  不冲突——该纪律约束的是 **agent 运行时调 xlpa 工具**，不约束 webchat 自身
  的平台登录代理。
- *否决*：复用 `mcp_server/permissions.py`（import 跨包）——以复制约 40 行
  纯函数换取包边界干净（Karpathy：最小且明确）。

### D5 限流：内存滑动窗口，双维度键

- 键 = `(client_ip, username)`；窗口默认 60s、阈值默认 5 次（失败计数），
  `WEBCHAT_LOGIN_RATE_LIMIT` 格式 `"<window_s>,<max_failures>"`；
- 超限返回 429 + Retry-After；计数留痕（内存日志列表，含 ip/username/时间，
  不含密码）。
- *理由*：C2 无多进程；键含 username 使"单 IP 撞库多账号"也被同 IP 维度
  捕获（ip 维度作为第二键并行计数——实现按两键任一超限即拒）。

### D6 目录与文件布局

```
webchat/
├── requirements.txt          # fastapi/uvicorn/httpx（入库）
├── requirements-dev.txt      # pytest（入库）
├── webchat_accounts.template.json   # 模板（入库）
├── webchat_accounts.json     # 实文件（gitignore，不入库）
├── README.md                 # 启动/配置/哈希工具说明
├── webchat/
│   ├── __init__.py
│   ├── __main__.py           # uvicorn 入口
│   ├── config.py             # 环境变量解析
│   ├── accounts.py           # 账号库加载/校验
│   ├── hashing.py            # PBKDF2 实现
│   ├── hashing 工具入口（__main__ 或 hash_password.py）
│   ├── sessions.py           # 票据存储/TTL
│   ├── ratelimit.py          # 滑动窗口
│   ├── platform_auth.py      # LoginByCode 代理 + 身份提取 + super 判定
│   └── api.py                # FastAPI 路由（login/logout/me）
└── tests/
    └── test_account_auth.py  # 全部场景用例（mock 平台 API）
```

- `.gitignore` 追加 `webchat/webchat_accounts.json`；
- 测试对平台 API 一律 mock（httpx MockTransport），不依赖外网与真实账号。

### D7 失败语义：防枚举与配置错误区分

- 账号不存在 / 密码错误 / disabled → 同一 401 响应体（同一错误信息）；
- 账号库缺失/损坏 → 503 + 明确"服务端账号库配置错误"（可区分，因为这是
  运维问题不是攻击面）；
- 平台登录失败 → 401 + "平台凭据绑定失败"（不区分平台侧具体原因，不回显
  绑定的 phone/code 明文，只回显脱敏尾号）。

## Risks / Trade-offs

- [票据内存态 → 服务重启全员掉线] → 既定语义记录在案；运维重启低频可接受；
  持久化列为后续可选变更（不做承诺）。
- [PBKDF2 迭代 48 万次单次登录耗时 ~0.1-0.3s] → 仅登录路径一次计算，
  可接受；不缓存哈希结果（恒时比较防时序侧信道优先）。
- [限流内存态 → 重启清零] → 与票据同语义；攻击窗口极小（重启即恢复防护）。
- [复制 permissions.py 纯函数 → 两处维护] → 约 40 行、键位表稳定；
  C4 若需深化写权限判定，届时评估是否下沉共享包（记录为 C4 前置考量）。
- [webchat 直连平台 API 的出网流量] → 与 MCP Server login 工具同一出口
  语义（同一 API、同一凭据形态），无新增数据目的地。

## Migration Plan

1. 建骨架（venv + requirements + 包结构）→ 哈希工具与账号库（含模板）→
   sessions/ratelimit/platform_auth → API 路由 → 测试全量；
2. 回归：主 pytest（mcp_server 零改动证明）+ webchat pytest 双绿；
3. 汇报证据归档至 `validation/c2-web-account-auth/`。

回滚：`webchat/` 整目录 + `.gitignore` 一行为独立提交，`git revert` 整体
回退即回到 C1 后状态；无数据迁移、无既有行为耦合。

## Open Questions

（无——D4 的"直连平台 API"与 D1 的"独立 venv"为本次规划已定决策，
如需求方对平台 API 出网方式或框架选型有异议请在实施前提出。）
