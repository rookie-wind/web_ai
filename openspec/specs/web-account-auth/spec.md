# web-account-auth Specification

## Purpose
定义 Web/移动端账号密码准入的行为契约：账号库与密码哈希约定、登录/登出/票据
校验、票据 TTL 与失效语义、登录限流、与平台业务凭据的绑定，以及"准入不等于
写权限"的身份边界。

**变更四要素**

| 要素 | 内容 |
|---|---|
| 前置条件（含需先验证事项） | 1) C1 已归档（只读母本前提成立）；2) 主 pytest 基线全绿（C1 已证 719/0/0/1）；3) V10 验证：PAT 注入不出现在子进程命令行（探针留证，C3 SDK 实例化先决项）；4) 平台 LoginByCode 可达（2026-10-28 演练已实测：9413 登录成功、角色 super）；5) 密码哈希选型确认：PBKDF2-HMAC-SHA256 标准库实现（零新依赖，OWASP 认可），不引入 argon2 |
| 要做的事 | webchat/ 独立服务骨架（独立 venv）、账号库+模板、PBKDF2 哈希工具、login/logout/me 端点、会话票据 TTL、登录限流、业务凭据绑定（LoginByCode 代理 + superAccounts 判定）、webchat pytest |
| 通过标准（可执行判据） | 1) webchat pytest 全过（哈希往返、错误密码 401、票据 TTL/过期拒绝、logout 后票据失效、限流触发、账号库缺文件/损坏时拒绝并明确报错、两份名单不混用断言）；2) 主 pytest 基线全绿（mcp_server 零改动）；3) `git ls-files` 不含 webchat_accounts.json 且模板存在；4) 密码明文不出现在任何入库文件；5) `openspec validate --strict` 通过 |
| 执行顺序与依赖 | 依赖 C1（已完成）；C3（会话运行时）依赖本变更的票据体系；本变更不得触碰 mcp_server 行为 |

## Requirements

### Requirement: 账号库必须以哈希形态存储密码

Web 准入账号库 MUST 为独立 JSON 文件（不入版本控制，附模板入库），每条账号
MUST 包含 username、密码哈希（PBKDF2-HMAC-SHA256，含盐与迭代次数）、绑定的
平台手机号与验证码、启用标记；密码明文 MUST NOT 出现在账号库、日志或任何入库
文件中。系统 MUST 提供生成密码哈希的命令行工具。

#### Scenario: 账号库模板入库而实文件不入库

- **WHEN** 检查版本库跟踪清单
- **THEN** 账号库实文件不在跟踪清单，模板文件在跟踪清单中，且模板不含真实密码

#### Scenario: 哈希工具生成可用条目

- **WHEN** 管理员运行密码哈希工具并输入明文密码
- **THEN** 工具输出 `pbkdf2_sha256$<iterations>$<salt>$<hash>` 格式的哈希行，且不回显明文到日志

#### Scenario: 账号库缺失或损坏时拒绝服务

- **WHEN** 账号库文件缺失或 JSON 损坏
- **THEN** 登录端点返回明确的服务端配置错误，不崩溃、不退化为放行任何账号

### Requirement: 登录必须校验账号密码并签发会话票据

登录端点 MUST 校验 username 与密码哈希；成功时签发随机会话票据（含过期时间）
并返回账号展示信息；失败时 MUST 返回 401 且不区分"账号不存在"与"密码错误"
（防账号枚举）；disabled 账号 MUST 拒绝登录。

#### Scenario: 正确账密登录成功

- **WHEN** 以账号库中 enabled 账号的正确用户名密码调用登录
- **THEN** 返回会话票据与过期时间，票据在有效期内可通过 /me 校验

#### Scenario: 错误密码拒绝且不泄露账号存在性

- **WHEN** 以正确用户名 + 错误密码调用登录
- **THEN** 返回 401，错误信息与"用户名不存在"场景完全一致

#### Scenario: disabled 账号拒绝登录

- **WHEN** 以 enabled=false 的账号正确密码调用登录
- **THEN** 返回 401

### Requirement: 会话票据必须带 TTL 且可主动失效

会话票据 MUST 有可配置 TTL，过期后校验 MUST 失败；登出端点 MUST 立即作废
票据；票据存储为服务端内存态（服务重启即全部失效，需重新登录——记录在案
的既定语义，持久化属后续变更可选项）。

#### Scenario: 票据过期后校验失败

- **WHEN** 票据年龄超过 TTL 后调用 /me
- **THEN** 返回 401

#### Scenario: 登出后票据立即失效

- **WHEN** 调用登出端点后再以原票据调用 /me
- **THEN** 返回 401

### Requirement: 登录必须限流

登录端点 MUST 按 IP 与用户名维度实施滑动窗口限流（阈值可配置）；超限请求
MUST 被拒绝且计数留痕；限流状态为服务端内存态。

#### Scenario: 连续失败触发限流

- **WHEN** 同一 IP 对同一用户名在窗口内连续失败登录超过阈值
- **THEN** 后续请求被限流拒绝，且拒绝记录含 IP、用户名与时间（不含密码）

### Requirement: 准入必须绑定平台业务凭据且不产生写权限

登录成功后，webchat 后端 MUST 以账号库绑定的 phone/code 代为完成平台
`/api/Auth/LoginByCode` 登录并缓存业务 Token（仅会话内存，不落盘、不回显）；
写权限判定 MUST 且仅以既有 `permissions.json`（superAccounts）与业务登录
结果为依据；Web 准入命中 MUST NOT 产生任何写权限；两份名单（webchat 账号库
与 permissions.json）MUST NOT 合并或互相替代。平台登录失败时 MUST 明确报错，
不得静默降级为"已准入无业务凭据"。

#### Scenario: 平台登录成功并缓存业务凭据

- **WHEN** 账密登录成功且绑定的 phone/code 平台登录成功
- **THEN** 会话持有业务 Token 与账号标识，/me 可返回角色判定结果

#### Scenario: 平台登录失败明确报错

- **WHEN** 账密登录成功但绑定的 phone/code 平台登录失败
- **THEN** 返回明确错误提示，会话不建立业务凭据

#### Scenario: 准入不等于写权限

- **WHEN** 账号存在于 webchat 账号库但绑定的业务账号不在 superAccounts
- **THEN** 该会话写权限判定为否，即使账密登录成功

#### Scenario: 两份名单互不替代

- **WHEN** 账号仅在 permissions.json 的 superAccounts 中配置而账号库无此条目
- **THEN** 该账号无法通过 Web 准入登录，superAccounts 配置不产生任何准入效果

### Requirement: webchat 服务必须与 MCP Server 隔离部署

webchat 后端 MUST 为独立进程与独立 venv（依赖清单与 `mcp_server/requirements.txt`
分离）；本能力范围内 MUST NOT 修改 `/mcp` 端点、既有 71 个工具的入参与返回、
以及 `mcp_server` 的任何运行行为。

#### Scenario: MCP Server 行为零改动

- **WHEN** 本变更实施完成并运行主 pytest 基线
- **THEN** `mcp_server/tests` 全绿，且 git diff 不含 `mcp_server/` 行为性改动

### Requirement: 账号库变更必须热加载

账号库文件变更 MUST 在下次鉴权读取时自动生效，MUST NOT 要求重启 webchat
服务。实现 MUST 以文件修改时间（mtime）判定变更并重载；重载后新增/禁用账号
立即生效，文件损坏时 MUST 进入既有"配置错误 → 503"状态，MUST NOT 崩溃或
放行。系统 MUST 支持"一人一账号"的管理方式：会话归属、并发配额与审计均按
username 区分。

#### Scenario: 新增账号无需重启

- **WHEN** 运维在账号库文件中新增一个账号条目并保存
- **THEN** 下一次登录请求即可使用该账号，无需重启服务

#### Scenario: 账号库损坏即时拒绝

- **WHEN** 账号库被改为非法 JSON
- **THEN** 下一次鉴权读取进入配置错误状态，登录返回 503，既有进程不崩溃
