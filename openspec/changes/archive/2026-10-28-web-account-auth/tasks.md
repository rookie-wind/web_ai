## 1. 前置取证（不改产品文件）

- [x] 1.1 V10 验证：PAT 注入不出现在子进程命令行（探针脚本方式，留证 `validation/c2-web-account-auth/t11_v10_probe.txt`；失败则阻塞 C3 并回报）
- [x] 1.2 主 pytest 基线重跑取证（复用 C1 结论 719/0/0/1，输出存 `validation/c2-web-account-auth/t12_baseline.txt`）

## 2. webchat 服务骨架

- [x] 2.1 建 `webchat/` 目录结构与 `requirements.txt` / `requirements-dev.txt`，创建独立 venv 并安装依赖，验证 `python -c "import fastapi, uvicorn, httpx"` 通过
- [x] 2.2 实现 `webchat/config.py`（环境变量解析：SESSION_TTL/LOGIN_RATE_LIMIT/ACCOUNTS_PATH/PERMISSIONS_PATH/PCA_API_BASE_URL，含默认值与非法值报错），验证非法配置启动即明确报错
- [x] 2.3 实现 `webchat/hashing.py`（PBKDF2 编码/校验 + `python -m webchat.hash_password` stdin 工具），验证哈希往返与恒时比较（单元测试）

## 3. 账号库与会话

- [x] 3.1 实现 `webchat/accounts.py`（加载/校验账号库，缺失/损坏→明确配置错误状态），加 `webchat_accounts.template.json` 模板 + `.gitignore` 条目 `webchat/webchat_accounts.json`，验证 git status 对实文件不可见
- [x] 3.2 实现 `webchat/sessions.py`（票据签发/校验/TTL 惰性过期/登出删除），单元测试覆盖 TTL 过期与登出失效
- [x] 3.3 实现 `webchat/ratelimit.py`（(ip, username) 双键滑动窗口 + 429 + Retry-After + 留痕），单元测试覆盖窗口滑动与阈值触发

## 4. 业务凭据绑定与 API

- [x] 4.1 实现 `webchat/platform_auth.py`（LoginByCode 代理 + 身份键位提取纯函数 + superAccounts 判定读 WEBCHAT_PERMISSIONS_PATH），平台 API 用 httpx MockTransport 单元测试（成功/失败/网络错误三分支）
- [x] 4.2 实现 `webchat/api.py`（POST /api/auth/login、POST /api/auth/logout、GET /api/auth/me；防枚举同构 401；账号库配置错误 503；平台失败 401 + 脱敏提示），TestClient 全场景用例：正确账密/错误密码/不存在用户/disabled/TTL 过期/登出失效/限流/两份名单不混用（superAccounts-only 账号无法登录）断言全过
- [x] 4.3 `webchat/__main__.py` + README（启动命令、配置表、哈希工具用法、账号库配置步骤），验证 `python -m webchat` 可启动并监听配置端口（冒烟，不留常驻进程）

## 5. 回归与验收取证

- [x] 5.1 webchat pytest 全绿存证（junit xml 到 `validation/c2-web-account-auth/`）
- [x] 5.2 主 pytest 基线全绿存证 + `git diff --stat` 证明 mcp_server/ 零行为改动
- [x] 5.3 敏感文件断言：`git ls-files` 不含 webchat_accounts.json、模板在库、grep 全库无密码明文/真实 phone-code 对
- [x] 5.4 证据索引 `validation/c2-web-account-auth/evidence-index.md` 归集（含 V10 结论），供 html-ppt 汇报引用
