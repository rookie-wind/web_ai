## 1. 基础设施：SystemTokenManager 与 SessionRegistry

- [x] 1.1 创建 `mcp_server/token_manager.py`，实现 SystemTokenManager 类（init_system_token / get_token / refresh / update_credentials），验证单元测试覆盖正常启动、网络失败、refresh 成功和 credentials 更新四种场景
- [x] 1.2 创建 `mcp_server/session.py`，实现 Session dataclass 和 SessionRegistry 类（create / get / delete / clear），验证按 MCP Token 绑定和查询返回正确 role
- [x] 1.3 在 permissions.json 模板中新增 `systemAccount` 段（phone/code），创建 `mcp_server/permissions.template.json` 作为 install.bat 拷贝源，验证模板 JSON 格式合法

## 2. AuthMiddleware 与 contextvars 改造

- [x] 2.1 移除 `access_level_var`，新增 `mcp_token_var: ContextVar[str]`；AuthMiddleware 验证 Bearer Token 后将原始 Token 字符串写入 `mcp_token_var`，验证已有 edge 工具和无权限页面仍可正常响应
- [x] 2.2 实现 `_require_session()` 辅助函数：从 `mcp_token_var` 取值 → 查 SessionRegistry → 无 session 则返回 NOT_LOGGED_IN 错误字典，验证未 login 时调用工具返回正确错误

## 3. Login 工具重写与 Token 获取逻辑

- [x] 3.1 重写 `login(phone, code)` 工具：(1) 调用 api_client.login 验证参数 (2) 提取 identity 查 superAccounts (3) 创建 session（super: 无 fallback; user: 存 fallback_token）(4) 返回 {success, role, message}，验证三种场景（super / user / 参数无效）的返回值正确
- [x] 3.2 实现 `_get_api_token()` 和 `_call_platform(coro_fn)` helper：_get_api_token 返回 system_token；_call_platform 捕获 40100 → refresh → 重试 → 仍失败则试 fallback → 最终返回 AUTH_EXPIRED，验证 mock 场景下透明刷新和降级链
- [x] 3.3 实现超级账号 login 时 systemAccount 失效的覆盖更新逻辑（用客户端参数更新 permissions.json），验证文件内容和内存 token 同步更新

## 4. 云端工具签名 Clean Break

- [x] 4.1 批量修改所有云端读工具（~25 个 get_xxx / query_xxx）：删除 `token: str` 参数，函数体改为 `_require_session()` + `_get_api_token()` + api_client 调用，验证 list_mcp_tools 返回的工具 schema 中无 token 参数
- [x] 4.2 批量修改所有云端写工具（~15 个 add_xxx / update_xxx / del_xxx）：同 4.1 + 在 _require_session 后检查 session.role=="super" 否则返回 FORBIDDEN，验证 user role 调写工具被拒
- [x] 4.3 移除 `_check_write_permission()` 旧函数，确认无残留引用；写权限判定统一由 session.role 控制

## 5. 服务端启动流程

- [x] 5.1 在 server.py `__main__` 启动段添加 init 序列：加载 permissions.json → SystemTokenManager.init → 加载/初始化 .stats.json → 运行测试统计 → 更新 stats，验证服务启动后 /api/showcase/data 可返回 live 数据
- [x] 5.2 实现启动时运行 test_protocol_converter.py 并解析输出的函数（subprocess + 正则提取 "Ran N tests"），结果写入 .stats.json；测试失败不阻塞启动，验证 stats 文件内容正确
- [x] 5.3 实现 gen_script 工具成功后 scriptsGenerated +1 并写入 .stats.json，验证调用 gen_script 后文件计数递增

## 6. Showcase 数据端点增强

- [x] 6.1 扩展 `/api/showcase/data` 响应：新增 scriptsGenerated、testTotal、testPassed、testFailed、brandCount、deviceTypeCount 字段（平台数据调用 _call_platform + 本地数据读 .stats.json），验证 API 返回完整结构
- [x] 6.2 showcase.html `loadShowcaseData()` 函数扩展：用 API 返回的 brandCount/deviceTypeCount/scriptsGenerated/testTotal 覆盖 `delivery.stats` 数组值，移除所有硬编码数字，验证页面加载后四个统计格显示动态数据

## 7. Access 页面与前端文案更新

- [x] 7.1 更新 access.html 权限说明文案：移除旧模型中“业务 Token + 超级账号”措辞，改为“MCP 接入 Token 用于连接，登录云端账号后获得读/写权限”，验证页面展示无 system/localhost 相关残留

## 8. Skill 文档与配置更新

- [x] 8.1 全局搜索替换 `.trae/skills/` 下所有 SKILL.md 中 `token=<业务Token>` / `token=xxx` 调用示例，改为不含 token 参数的调用方式；更新 `xlpa/SKILL.md` 登录流程描述，验证 grep 搜索 skill 目录无残留 `token=` 参数引用
- [x] 8.2 更新 `mcp_server/install.bat`：在生成 .env 后自动拷贝 permissions.template.json → permissions.json（若不存在），验证 install 后文件存在且含 systemAccount
- [x] 8.3 更新 `.gitignore`：确认覆盖 `mcp_server/permissions.json`、`mcp_server/.stats.json`（如缺失则添加），验证 git status 不显示这些文件

## 9. 测试验证

- [x] 9.1 更新现有 test_refactor.py 适配新签名（删除 token 参数），验证 pytest 全部通过
- [x] 9.2 新增集成测试：模拟完整 login → 读工具 → 写工具 → FORBIDDEN → AUTH_EXPIRED 降级链，验证各步骤返回预期错误码
- [x] 9.3 端到端验证：启动服务器 → 确认自动 login 成功 → 打开 showcase 确认无降级 → /api/showcase/data 返回 dataSource="live" + 所有统计字段非 null，验证页面显示正常
