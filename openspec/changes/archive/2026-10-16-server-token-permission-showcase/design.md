## Context

当前 server.py 单文件承载 59 个工具注册、AuthMiddleware 鉴权、TokenManager IP 分配和 CompositeApp 路由。权限由 `access_level_var`（system/user）在中间件层按 IP 注入 contextvars，写入工具通过 `_check_write_permission(token)` 检查 `access_level == "system"`。api_client.py 所有方法接受 `token` 参数透传至平台 HTTP header。

Motivation 见 proposal.md - Why。

## Goals / Non-Goals

**Goals:**
- 将权限判定从"连接时按 IP 决定"改为"login 后按 session role 决定"
- 工具签名统一去除 token 参数，Token 获取封装在服务端内部
- 启动时自动登录 + Token 透明刷新确保平台 API 始终可用
- showcase 数据完全动态化，消除所有硬编码数字

**Non-Goals:**
- 不改变边缘建档工具（edge_xxx）的内部逻辑和凭据来源
- 不引入新的外部依赖（OAuth、Redis、数据库等）
- 不改变 MCP 协议层或 FastMCP 框架选择
- 不实现多进程/分布式 session（单进程内存足够）

## Decisions

### D1: SystemTokenManager 模块职责

**决定**：新建 `token_manager.py` 模块（或扩展 permissions.py），封装：
- `init_system_token()` — 启动时调用，读 permissions.json → login → 持有 token
- `get_token()` — 返回当前有效 system_token
- `refresh()` — login 获取新 token，更新内存
- `update_credentials(phone, code)` — 覆盖 permissions.json.systemAccount + 重新 refresh

**理由**：与现有 TokenManager（MCP 接入 Token）职责正交，不宜混在同一个类。单独文件便于测试 mock。

### D2: SessionRegistry 数据结构

**决定**：内存字典 `dict[str, Session]`，key 为 MCP 接入 Token 字符串：
```python
@dataclass
class Session:
    phone: str
    role: str           # "super" | "user"
    fallback_token: str | None
    login_at: float
```

**理由**：Python asyncio 单线程，无需锁。按 MCP Token 绑定（用户选 B），粒度到人。

### D3: 工具内部获取 Token 的模式

**决定**：在工具函数体开头调用 `_require_session()` 和 `_get_api_token()`：
```python
@mcp.tool()
async def get_brand_list(nameCN: str = "", ...) -> dict:
    _require_session()  # 抛 NOT_LOGGED_IN 或返回 session
    token = _get_api_token()  # system_token 或 fallback
    return await api_client.get_brand_list(token, ...)
```

`_get_api_token()` 返回 system_token；写工具调用处包裹 try-retry 逻辑捕获 40100。

**备选**：装饰器模式 `@require_login(role="super")`。暂不采用，保持显式可读。

### D4: 透明刷新在 api_client 还是 server 层

**决定**：在 server.py 工具层的 `_call_platform(coro)` helper 中处理：调用 api_client → 检查返回 → 40100 时 `refresh()` + 重试一次。api_client 本身不变。

**理由**：api_client 是纯 HTTP 封装，不应有业务重试逻辑。server 层知道 session 上下文。

### D5: permissions.json 完整结构

```json
{
  "systemAccount": {
    "phone": "13912986342",
    "code": "9413"
  },
  "superAccounts": {
    "userIds": [],
    "phones": ["13912986342"]
  }
}
```

install.bat 首次部署时拷贝模板到 mcp_server/ 目录。

### D6: .stats.json 结构

```json
{
  "scriptsGenerated": 19,
  "testTotal": 91,
  "testPassed": 89,
  "testFailed": 0,
  "testSkipped": 2,
  "lastTestRunAt": "2026-09-20T10:00:00"
}
```

### D7: showcase 前端改造策略

**决定**：保留 SHOWCASE_DATA 对象作为骨架/初始渲染，`loadShowcaseData()` fetch `/api/showcase/data` 后覆盖 delivery.stats 数组值。避免大幅重写页面渲染逻辑。

### D8: AuthMiddleware 简化

**决定**：移除 `access_level_var` 注入（不再区分 system/user）。保留 Token 有效性校验。contextvars 中只注入 `mcp_token_var`（当前接入 Token），供 SessionRegistry 查询使用。

## Risks / Trade-offs

- **[Risk] 启动时 test 跑 2-5s 延迟** → Mitigation: 可接受（开发期）；失败不阻塞，用上次 stats
- **[Risk] 所有 session 在重启后丢失** → Mitigation: 用户只需重新 login，MCP Token 本身持久化不受影响
- **[Risk] permissions.json 明文存 code** → Mitigation: 已在 .gitignore，与 MCP_AUTH_TOKEN 同级安全
- **[Tradeoff] Clean break 无兼容** → 当前开发期无外部用户，可一次性切换
- **[Risk] 单 system_account 单点** → Mitigation: fallback_token 机制 + super 用户可更新 credentials

## Migration Plan

1. 新增 `token_manager.py`（SystemTokenManager）和 `session.py`（SessionRegistry）
2. server.py 启动流程改造：init_system_token → 跑测试 → 加载 stats
3. 全部云端工具删除 token 参数，加 `_require_session()` + `_get_api_token()`
4. 重写 login 工具：判定 role + 存 session + 条件覆盖 systemAccount
5. `_check_write_permission` 改为检查 `session.role == "super"`
6. showcase /api/showcase/data 新增 stats + 平台查询
7. showcase.html 前端 delivery.stats 动态化
8. access.html 权限说明文案更新
9. Skill 文档全局搜索替换：删除 `token=xxx` 调用示例
10. install.bat 添加 permissions.json 模板拷贝
11. .gitignore 确认覆盖 permissions.json + .stats.json
12. 现有测试适配新签名
