# 公网接入前置清单（Public Access Prerequisite Checklist）

> 适用范围：把 PCA MCP Server 与 webchat 从「仅内网/本机」形态收紧到
> 「可经受控反向代理对外提供」时，上线前 MUST 逐项核验的配置与安全前置。
> 本清单对应变更 `public-access-hardening`（C7）任务 5.1，逐项附**可执行
> 判据**（可复制命令或可观测结果），全部判据通过方可对外暴露。
>
> 基线事实（源码核对，2026-10）：
> - MCP Server 门控三分类见 `mcp_server/server.py` `_exposure_category`：
>   展示类 `open` / 票据类 `ticket` / Bearer 既有类 `pass`。
> - webchat 配置项见 `webchat/webchat/config.py`（`WEBCHAT_*` 环境变量）。
> - 默认全部关闭公网收紧：`MCP_PUBLIC_MODE=0` 时门控对所有请求放行，
>   与既有内网行为逐一致。

---

## 0. 阅读约定

- **本机来源**：`_resolve_client_ip` 解析后的直连/代理真实 IP 命中
  `LOCALHOST_IPS`（127.0.0.1 / ::1 等）。
- **可信代理**：直连来源命中 `MCP_TRUSTED_PROXY`（MCP 侧）或
  `WEBCHAT_TRUSTED_PROXY`（webchat 侧）清单，才采信 `X-Forwarded-For`
  最左值；否则一律用直连地址。
- 每条判据标注【MCP】【webchat】【反代】归属，便于分工核验。

---

## 1. 对外形态与证书（双轨二选一）

对外只提供两种受支持形态，二者都要求 **TLS 终止在边缘、源站仅监听回环**。

### 1.1 轨道 A：Caddy 自动证书（推荐，公网直连域名）

适用：有公网可达域名、希望自动签发/续期 Let's Encrypt 证书。

```caddyfile
pca.example.com {
    # webchat 单页前端 + API + SSE
    reverse_proxy /api/sessions/*/events 127.0.0.1:8800 {
        flush_interval -1        # 关闭缓冲，SSE 逐帧下发（见 §3）
    }
    reverse_proxy 127.0.0.1:8800
}

mcp.example.com {
    reverse_proxy /mcp 127.0.0.1:8765 {
        flush_interval -1        # /mcp 流式响应同样关缓冲
    }
    reverse_proxy 127.0.0.1:8765
}
```

判据【反代】：`curl -sI https://pca.example.com/` 返回 200 且
`strict-transport-security` 或证书链有效（`curl -v` 无证书告警）。

### 1.2 轨道 B：企业反向代理（Nginx / 硬件 LB，证书由企业侧托管）

适用：企业已有统一入口与证书体系，PCA 仅作为上游。

```nginx
# webchat SSE 专用 location（关缓冲）
location ~ ^/api/sessions/[^/]+/events$ {
    proxy_pass http://127.0.0.1:8800;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_buffering off;         # 关闭响应缓冲（见 §3）
    proxy_cache off;
    proxy_read_timeout 1h;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header Host $host;
}
location / {
    proxy_pass http://127.0.0.1:8800;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header Host $host;
}
```

判据【反代】：企业入口以有效证书对外提供 HTTPS；HTTP 明文访问被 301
跳转到 HTTPS。

### 1.3 TLS 终止位置与源站监听（两轨通用）

- TLS MUST 在边缘（Caddy / 企业反代）终止，源站（MCP、webchat）MUST
  仅监听 `127.0.0.1`，不直接暴露公网。
- **默认值陷阱**：两侧默认值不同，MCP 侧 **不会**自动只监听回环。

| 变量 | 源码默认 | 公网形态要求 |
|------|----------|--------------|
| `MCP_HOST` | `0.0.0.0`（全部网卡，`server.py`） | MUST 显式设为 `127.0.0.1` |
| `MCP_PORT` | `8765` | 与反代 upstream 一致 |
| `WEBCHAT_HOST` | `127.0.0.1`（`config.py`） | 保持默认即可 |
| `WEBCHAT_PORT` | `8800` | 与反代 upstream 一致 |

- 判据【MCP】：启动日志出现 `Uvicorn running on http://127.0.0.1:<port>`；
  `netstat -ano -p TCP | findstr :8765` 显示监听地址为 `127.0.0.1:8765`
  而**非** `0.0.0.0:8765`。若为 `0.0.0.0` 说明 `MCP_HOST` 未注入，禁止上线。
- 判据【webchat】：`WEBCHAT_HOST=127.0.0.1` 生效，`netstat` 显示
  `127.0.0.1:8800`。

---

## 2. 真实客户端 IP 与 XFF 信任链

公网经反代后，源站看到的直连 IP 是反代地址，真实来源在
`X-Forwarded-For` 最左值。门控/限流只有在**可信代理**前提下才采信转发头，
否则客户端可伪造 XFF 绕过本机判定与限流。

### 2.1 两层信任，缺一不可

XFF 的信任发生在**两层**，任务 5.2 演练实测确认二者必须一致收紧：

| 层 | 控制项 | 命中效果 |
|----|--------|----------|
| L1（uvicorn） | `FORWARDED_ALLOW_IPS`（默认 `127.0.0.0/8`） | 直连来源命中即把 `scope["client"]` 重写为 XFF **最左值** |
| L2（应用） | `MCP_TRUSTED_PROXY` / `WEBCHAT_TRUSTED_PROXY` | 直连命中才由 `_resolve_client_ip` 取 XFF 最左值 |

**关键陷阱（演练复现）**：源站回环绑定（§1.3）时，反代到源站的直连来源就是
`127.0.0.1`，必然命中 L1 默认信任段。若客户端能**直接打到源站**（源站被误
暴露到公网）并伪造**单值** `X-Forwarded-For: 127.0.0.1`，L1 会把 `client`
改写成 `127.0.0.1`，L2 见 `127.0.0.1` 又在 `MCP_TRUSTED_PROXY` 内 → 判定为
本机 → **门控被架空、展示端点开放**（实测 `GET /api/access-info` → 200）。

- MUST：源站仅 `127.0.0.1` 监听且**经主机防火墙/安全组确保公网不可直连**，
  令外部流量只能经反代进入。
- MUST：反代对客户端可控路径 **覆盖**（`proxy_set_header X-Forwarded-For
  $remote_addr;`）而非无脑 `$proxy_add_x_forwarded_for` 追加，避免客户端
  自带值停留在最左位；多层代理需拼接时，最左位必须由可信边缘写入。
- 建议：把 L1 信任段收紧到反代实际地址（`FORWARDED_ALLOW_IPS=<反代IP>/32`），
  使 L1 与 L2 口径一致，杜绝回环直连注入。

- 【MCP】`MCP_TRUSTED_PROXY` = 反代回环/内网地址（逗号分隔），例如
  `127.0.0.1`。仅当直连来源命中该清单，`_resolve_client_ip` 才取 XFF 最左值。
- 【webchat】`WEBCHAT_TRUSTED_PROXY` 同理，登录限流按真实 IP 分桶。

判据【MCP】：从**真公网直连**源站（不经反代）带伪造 `X-Forwarded-For:
127.0.0.1` 请求展示端点 → 应 403（直连来源不在 `MCP_TRUSTED_PROXY`，且源站
本就不可公网直连）。若返回 200，说明源站被直接暴露 + L1 回环信任被利用，
禁止上线。经反代的合法公网来源（真实公网 IP 落在 XFF）→ 403。
判据【webchat】：未配 `WEBCHAT_TRUSTED_PROXY` 时，携带伪造 XFF 连续失败登录，
按**直连地址**而非 XFF 值限流（同一直连来源累计触发阈值）。

---

## 3. SSE 关缓冲（事件流实时下发）

webchat 事件流 `/api/sessions/{id}/events` 与 `/mcp` 为长连接流式响应，
反代缓冲会导致消息「憋到最后一次性吐出」或心跳失效。

- 【反代】Caddy：对应 location `flush_interval -1`。
- 【反代】Nginx：`proxy_buffering off;` + `proxy_cache off;` +
  `proxy_http_version 1.1;` + `Connection ""`。
- 服务端已具备心跳：`sessions_api.stream_events` 每 15s 发一次
  `_HEARTBEAT`，用于探活与防中间设备空闲断连。

判据【反代】：浏览器打开会话发消息，Network 面板中 `events` 响应为
`text/event-stream` 且分帧陆续到达（非一次性）；断网 5s 重连后
`Last-Event-ID` 续传，历史事件无缺口（对应任务 4.1 冒烟）。

---

## 4. 暴露路径最小化

### 4.1 MCP Server 端点三分类（`_exposure_category`）

| 类别 | 路径 | 公网模式（`MCP_PUBLIC_MODE=1`）行为 |
|------|------|--------------------------------------|
| `open` 展示类 | `/`、`/showcase`、`/access`、`/api/access-info`、`/api/showcase/data`、`/api/docs/export-skills*` | 非本机且非 allowlist → **403**（不回显 allowlist 与 Token） |
| `ticket` 票据类 | `/api/archive/templates/<id>` | 路由放行，handler 内补充：非本机要求 Bearer 且 `derive_owner_id(token)` 与 URL `owner` 一致（无/无效 401、不一致 404、一致 200） |
| `pass` Bearer 既有类 | `/mcp`、`/api/archive/uploads`、mint/revoke、`/api/logs` 等 | 门控不介入，既有 Bearer 鉴权不变；`/api/logs` 非本机不采信 `?token=` 查询串，仅接受 Bearer 头 |

- 判据【MCP】展示类：`MCP_PUBLIC_MODE=1` 下从公网来源 `curl http://<host>:8765/`
  → 403；本机来源 → 200。
- 判据【MCP】票据类：公网来源无 Bearer 请求 templates → 401；带他人 Token →
  404；带本人匹配 Token → 200。
- 判据【MCP】logs 收紧：公网来源 `GET /api/logs?token=<x>` → 该 `?token=` 被
  忽略（仅 Bearer 头有效）。

### 4.2 webchat 暴露面

- webchat 仅需对外暴露 `/`（单页）、`/static/*`、`/api/auth/*`、
  `/api/sessions/*`。管理/内部端点（若有）MUST NOT 经反代对外。
- webchat 与 MCP Server 之间（`WEBCHAT_MINT_URL`、`/mcp`）走**回环/内网**，
  不经公网。
- 判据【webchat】：对外域名访问 `/`、登录、发消息、下载产物均正常；访问
  未列入白名单的内部路径（如直接打 MCP 源站端口）在公网侧不可达。

---

## 5. 鉴权凭据注入与运行配置（两大易错点）

### 5.1 易错点一：`.env` 仅由 `start.bat` 解析

- `mcp_server/.env` **只**由 `mcp_server/start.bat` 读取并注入环境；直接
  `python server.py` **不会**加载 `.env`（无 dotenv 装载）。
- 判据【MCP】：在 `start.bat` 环境里 `MCP_PUBLIC_MODE=1` 生效；而
  `python server.py` 直起时若未在当前 shell 显式 `set`，`MCP_PUBLIC_MODE`
  取默认 `0`。上线 MUST 用 `start.bat` 或在服务管理器环境里显式注入。

### 5.2 易错点二：密钥注入与 `.gitignore` 前置确认

需注入的两个密钥：

| 变量 | 归属 | 语义 | 注入方式 |
|------|------|------|----------|
| `QODERCN_PERSONAL_ACCESS_TOKEN` | webchat | 实例接入 Qoder 的 PAT（`api.py` 从环境读取，注入子进程，不出现在命令行/URL） | 服务环境 / `start` 脚本，**不写死进代码** |
| `WEBCHAT_MINT_SECRET` | webchat **与** MCP 两侧一致 | mint 端点共享密钥（`X-Mint-Secret`） | 两侧同一值，经环境注入 |

- **落盘前 MUST 确认目标文件已在 `.gitignore` 内**：
  - `mcp_server/.env` 已被根 `.gitignore` 忽略（现状：是）。
  - **`webchat/.env` 当前并未被忽略**（根 `.gitignore` 无此条目）。若为
    webchat 建 `.env` 存放上述密钥，MUST 先把 `webchat/.env` 加入
    `.gitignore` 再写入任何密钥，否则密钥会进入版本控制。
- 判据【webchat】：`git check-ignore webchat/.env` 返回该路径（退出码 0）
  后方可写入密钥；若返回非 0（当前状态），先补 `.gitignore` 再落盘。
- 判据【webchat】：`git grep -I -e "WEBCHAT_MINT_SECRET=.\+" -e "QODERCN_PERSONAL_ACCESS_TOKEN=.\+" -- ':!*.md'`
  在受版本控制的文件中 MUST 无命中（密钥不入库）。

### 5.3 MCP 侧其余密钥

- `MCP_AUTH_TOKEN`：管理员 Token（localhost 系统级）。公网形态下 MUST 设置
  强随机值，不得为空。
- `WEBCHAT_ALLOWED_IPS`：允许调 mint 端点的来源（默认 `127.0.0.1,::1`）。
  公网形态下保持仅回环/内网，MUST NOT 放开到 `0.0.0.0`。

---

## 6. 限流参数

### 6.1 webchat 登录限流（design D11）

| 变量 | 默认 | 语义 |
|------|------|------|
| `WEBCHAT_LOGIN_RATE_LIMIT` | `60,5` | 账号级：窗口 60s 内同一账号失败达 5 次即锁 |
| `WEBCHAT_LOGIN_SOURCE_MAX` | `60` | 来源级（不区分账号）：同一直连/真实 IP 窗口内失败阈值，显著高于账号级，避免同反代出口互锁 |
| `WEBCHAT_TRUSTED_PROXY` | 空 | 可信反代清单；决定来源级分桶是否采信 XFF |

- 判据【webchat】：同一来源对多个账号高频失败，先触发**账号级**锁定而不
  误伤整台反代出口（来源级阈值 60 明显高于账号级 5）。
- 判据【webchat】：配 `WEBCHAT_TRUSTED_PROXY` 后，不同真实客户端（不同 XFF
  最左值）的失败互不影响。

### 6.2 MCP mint 限流

- `WEBCHAT_MINT_RATE_LIMIT`（默认 60）：mint 端点速率上限。
- 判据【MCP】：超过速率后 mint 被拒（429/拒绝），不影响正常低频签发。

### 6.3 会话/实例配额（webchat）

| 变量 | 默认 | 语义 |
|------|------|------|
| `WEBCHAT_MAX_INSTANCES` | 4 | 全局活跃实例上限 |
| `WEBCHAT_MAX_SESSIONS_PER_USER` | 2 | 每用户并发会话上限 |
| `WEBCHAT_MAX_TURNS` | 25 | 单轮工具迭代上限 |
| `WEBCHAT_SESSION_TTL` | 43200 | 会话票据 TTL（秒） |
| `WEBCHAT_LEASE_TTL` | 45 | 写租约 TTL（秒） |
| `WEBCHAT_DOWNLOAD_GRANT_TTL` | 120 | 一次性产物下载 grant TTL（消费即废） |

- 判据【webchat】：并发超配额时创建会话返回可辨识 409 文案（前端明确报错，
  对应任务 3.3）。

---

## 7. 上线巡检项（每次变更/重启后逐项打勾）

| # | 巡检项 | 可执行判据 |
|---|--------|-----------|
| 1 | 公网模式开关符合预期 | 生产 `MCP_PUBLIC_MODE=1`；内网/回滚 `=0` |
| 2 | 源站仅监听回环 | `netstat` 显示 8765/8800 绑定 `127.0.0.1`；MCP 侧 MUST 显式设 `MCP_HOST=127.0.0.1`（默认 `0.0.0.0`） |
| 3 | 展示端点公网 403 | 公网来源 `curl /` → 403；本机 → 200 |
| 4 | 票据下载需 Bearer+owner | 无 Token→401，他人→404，本人→200 |
| 5 | logs 不采信 `?token=` | 公网 `?token=` 被忽略 |
| 6 | 可信代理清单正确 | `MCP_TRUSTED_PROXY`/`WEBCHAT_TRUSTED_PROXY` 仅含反代地址 |
| 7 | SSE 关缓冲 | `events` 分帧实时到达，重连无缺口 |
| 8 | 密钥未入库 | `git check-ignore webchat/.env` 命中；`git grep` 无密钥 |
| 9 | 两侧 mint secret 一致 | webchat 能成功 mint 会话凭据（无 401/502） |
| 10 | 授权激活生效 | 真实链路事件流出现 `tool_call` 且无 `NOT_LOGGED_IN`（任务 2.3 判据） |
| 11 | 限流阈值合理 | 账号级/来源级阈值未被误设相等 |
| 12 | 回归基线 | 主 pytest 全绿、webchat pytest 全绿、`list_mcp_tools` total=77 |

---

## 8. 回滚

- 任一公网项异常，MCP 侧置 `MCP_PUBLIC_MODE=0` 即恢复「全部放行、与内网
  逐一致」的既有行为（门控短路返回放行），无需回滚代码。
- webchat 侧将对外路由从反代摘除、恢复 `WEBCHAT_HOST=127.0.0.1` 仅本机访问。

---

## 附：本清单评审结论（任务 5.1 验证）

- 全部条目均给出可执行判据，无 TBD / 占位项。
- 端点分类、配置项名与默认值、`.gitignore` 现状（`webchat/.env` 未忽略）
  均已对照 `mcp_server/server.py`、`webchat/webchat/config.py`、根
  `.gitignore` 源码核对。
- 任务 5.2 演练修订一项：核对 `server.py` 发现 `MCP_HOST` 默认为 `0.0.0.0`，
  原 §1.3 把「仅监听回环」误写为默认行为，已补充默认值陷阱表与生效判据。
