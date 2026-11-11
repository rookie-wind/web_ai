# webchat — Web/移动端接入后端（Host 层）

账号密码准入（C2）、会话运行时（C3）、写入门禁（C4）、产物与上传（C5）。
与 `mcp_server` 完全隔离：独立进程、独立 venv、独立依赖。

## 启动

```powershell
# 首次：创建独立 venv 并安装依赖
python -m venv webchat\.venv
webchat\.venv\Scripts\python -m pip install -r webchat\requirements-dev.txt

# 启动（默认 127.0.0.1:8800）
# 注意：webchat 包位于 webchat\webchat，需在 webchat 目录下运行
cd webchat
.\\.venv\Scripts\python -m webchat
```

## 配置账号库

1. 生成密码哈希（输入不回显、不进 shell 历史）：

   ```powershell
   cd webchat
   .\.venv\Scripts\python -m webchat.hash_password
   ```

2. 复制 `webchat_accounts.template.json` 为 `webchat_accounts.json`，
   填入 username / password_hash / phone / code / enabled。

   - `phone` + `code`：平台业务登录凭据（`/api/Auth/LoginByCode`），
     由 webchat 后端在登录时代为调用；
   - 实文件已被 `.gitignore` 覆盖，不得提交版本控制。

## 环境变量

| 键 | 默认 | 说明 |
|---|---|---|
| WEBCHAT_SESSION_TTL | 43200 | 会话票据 TTL（秒） |
 | WEBCHAT_MAX_INSTANCES | 100 | 全局活跃会话上限 |
| WEBCHAT_MAX_SESSIONS_PER_USER | 5 | 每用户并发会话上限 |
| WEBCHAT_SESSION_IDLE_TTL | 1800 | 空闲会话自动结束阈值（秒） |
| WEBCHAT_IDLE_SWEEP_INTERVAL | 60 | 空闲扫描周期（秒） |
| WEBCHAT_MAX_CONCURRENT_TURNS | 16 | 并发执行轮次上限（超出返回 409 系统繁忙） |
| WEBCHAT_LOGIN_RATE_LIMIT | 60,5 | 限流 "<窗口秒>,<失败阈值>" |
| WEBCHAT_ACCOUNTS_PATH | webchat/webchat_accounts.json | 账号库路径 |
| WEBCHAT_PERMISSIONS_PATH | mcp_server/permissions.json | 超级账号配置（只读） |
| PCA_API_BASE_URL | https://18091.chinadny.com | 平台 API 基地址（沿用既有语义） |
| WEBCHAT_HOST / WEBCHAT_PORT | 127.0.0.1 / 8800 | 监听地址与端口 |
| WEBCHAT_UPLOAD_MAX_TABLE_MB / _IMAGE_MB / _DOC_MB | 10 / 10 / 20 | 三通道上传大小上限 |
| WEBCHAT_RETENTION_INPUT_DAYS / _RESULT_DAYS / _TEMPLATE_DAYS / _SENSITIVE_TEMP_DAYS | 30 / 30 / 30 / 7 | 保留天数（temp 会话销毁即清、audit 不清） |
| WEBCHAT_RETENTION_SWEEP_INTERVAL | 3600 | 保留期后台扫描间隔（秒） |
| WEBCHAT_OCR_ENABLED / WEBCHAT_OCR_PROVIDER | 1 / rapidocr | 截图通道 OCR 开关与 provider |
| WEBCHAT_DOWNLOAD_GRANT_TTL | 120 | 一次性下载 grant TTL（秒，消费即作废） |
| WEBCHAT_SKILLS_ROOT | agent_assets/skills | 技能母本目录（索引进系统提示；内置 Read 白名单根之一） |
| WEBCHAT_READ_EXTRA_ROOTS | `%TEMP%/qoder-mcp-outputs` + `~/.qoder-cn/tmp` | Read 额外白名单目录（逗号/分号分隔，默认已含 CLI 大结果落盘目录） |
| WEBCHAT_AGENT_MODEL | Qwen3.8-Flash | 会话模型名（传入 CLI `--model`；置空回落 CLI 默认） |
| WEBCHAT_INIT_TIMEOUT | 60 | 会话后台初始化（激活/连接/清单）总超时秒数，超时转 failed |

## 端点

| 端点 | 说明 |
|---|---|
| POST /api/auth/login | 账密登录 → 会话票据（+ 平台业务凭据绑定） |
| POST /api/auth/logout | 登出，票据立即作废 |
| GET /api/auth/me | 票据校验与会话信息（角色判定） |
| POST /api/sessions/{id}/artifacts/upload | 三通道上传（`channel` = archive_table / document / screenshot；text 走 /messages；PDF 文档额外结构化抽取 `<stem>.pdf.md`） |
| POST /api/sessions/{id}/artifacts/{aid}/grant | 按需铸造一次性下载 grant（响应体返回，不入事件） |
| GET /api/sessions/{id}/artifacts/{aid}/download | 代理下载（请求头 `X-Artifact-Grant`，URL 不含凭据） |
| POST /api/sessions/{id}/abort | 中止当前任务（Web 轮次 + MCP 建档批次；不回滚已完成的写入） |
| DELETE /api/sessions/{id} | 删除会话（立即物理删除工作区与产物，区别于 close） |

错误语义：账号不存在/密码错误/disabled 同一 401（防枚举）；
账号库配置错误 503；平台登录失败 401 + 手机号脱敏尾号。

## 容量与账号管理

- SSE 事件流采用**增量读取**：建连时一次历史回放，之后每 0.5 秒只读文件新增
  字节，不再重读历史，单事件循环可支撑 100 个并发连接量级。
- 会话空闲（`WEBCHAT_SESSION_IDLE_TTL`，默认 30 分钟）且无执行中轮次时自动
  close：撤销凭据、释放槽位、产 `session_closed(reason=idle)` 事件；工作区与
  产物仍按保留期留存，不物理删除。打开的 SSE 连接会持续刷新活动时间。
- `WEBCHAT_MAX_CONCURRENT_TURNS` 限制同时执行的 Agent 轮次；超出时发送消息
  返回 409"系统繁忙，请稍后重试"，不排队、不拉起新 CLI 子进程。
- 账号库按文件 mtime **热加载**：新增/禁用账号改完 `webchat_accounts.json`
  即生效，无需重启。**一人一账号**：会话列表、配额与审计均按 username 归属；
  需要平台侧按人区分权限时，每个账号绑定各自的平台手机号与验证码。
- 压测脚本：`webchat/tools/load_sse.py`，可对指定账号批量建会话并保持 SSE
  连接，用于验证 100 连接下的资源占用：

  ```powershell
  cd webchat
  .\.venv\Scripts\python tools\load_sse.py --accounts "u1:p1,u2:p2" --sessions-per-user 5 --seconds 10
  ```

## 网页检索与路由

- 内置 `WebSearch` 已开放（仅传查询词）；`WebFetch`、`Bash` 等仍关闭。
- 默认自动判定：平台/设备/建档/下发/召测/协议转换/边缘操作 → xlpa MCP；
  公开协议标准、厂商手册、行业信息、给定 URL 的公开内容 → WebSearch；
  混合任务先检索后用 MCP 落地；不确定时默认按 xlpa 理解或先澄清。
- 可选前缀（只影响当前一条消息，执行前剥离，不改变会话模式）：
  - `/web <任务>`：本次强制网页检索；
  - `/xlpa <任务>`：本次强制协议助手。
  不带前缀即自动判定，不需要每次输入都加前缀。
- 数据边界：禁止把账号、密码、验证码、Token、设备地址或内部协议文档原文
  送入网页检索；需要时先脱敏或征得用户确认。检索失败如实告知，不以模型
  记忆冒充检索结果。

## 技能加载与内置读取

- 技能来源锁定仓库 `agent_assets/skills`（canonical，只读母本），不使用
  `.qoder/skills` 等客户端副本；`WEBCHAT_SKILLS_ROOT` 可改。
- 服务启动时读取各 `SKILL.md` 的 name/description/when_to_use 形成索引，写入
  系统提示（含各 SKILL.md 路径）；模型需要时用内置 `Read` 读取全文。
- 消息以 `/技能名` 开头（如 `/xlpa ...`）时，该技能 SKILL.md 全文在**当轮**
  注入，不改变会话模式；未匹配的前缀按普通文本处理。
- 内置 `Read` 仅允许读取会话工作区、技能目录与 `WEBCHAT_READ_EXTRA_ROOTS`
  （默认含 CLI 大结果落盘目录 `%TEMP%/qoder-mcp-outputs`、
  `~/.qoder-cn/tmp`；路径 `resolve()` 后校验），仓库其他文件与目录穿越一律
  拒绝且不可确认解除。

## 中止当前任务

- 前端在轮次执行期间显示「停止」按钮；点击后调用
  `POST /api/sessions/{id}/abort`（需租约）。
- 后端同时做两层中止：
  1. 先请求 MCP 批次取消（`interrupt` 不会停止已发出的 MCP 工具）；
  2. 再调用 SDK `interrupt()` 结束当前轮次，宽限期内未收尾才取消任务兜底。
- 每会话持有一个持久 `QoderSDKClient` 与单个常驻接收循环，跨轮复用；
  中断后会话上下文保留，可直接继续下一轮，`session_id` 不变。
- 中止是**协作式**的：已完成的建档/挂载/参数保存不会回滚，补偿清单仍可查；
  中止时清理本会话旧确认票据，避免后续误放行。
- 中止后发 `turn_aborted` 事件，前端收起“任务进行中”状态。

## 会话创建异步化

- `POST /api/sessions` 只做快路（配额检查 + 凭据铸造 + 工作区 + 注册），
  约 1 秒内返回 `session_id`；平台授权激活、CLI 连接与模型清单在后台慢路
  执行（激活 ∥ 连接并行，总超时 `WEBCHAT_INIT_TIMEOUT` 默认 60 秒）。
- 会话状态机 `creating → ready / failed`：就绪写入 `session_ready` 事件、
  失败写入 `session_failed`（含原因，不含凭据）；`GET /api/sessions` 携带
  `status`/`status_error`。
- 非 `ready` 会话的发消息/上传/切模型返回 409「会话初始化中，请稍候」；
  前端输入区同步禁用并显示初始化进度，就绪后解锁并加载模型下拉。
- 初始化失败自动回滚：撤销凭据、删除工作区、槽位与配额恰好释放一次；失败
  记录保留（列表呈“创建失败”，仅可删除）。自带 PAT 失败时前端自动重开创建
  对话框并回填原因与输入；“记住 PAT”仅在就绪后持久化。
- 空闲回收跳过 `creating` 会话；初始化中删除/关闭会话会先取消慢路任务。

## 截图通道双落盘

- 图片（截图/照片）按原扩展名落 `xlpa-input/`（Agent 可直接 `Read` 原图），
  同时生成 `<stem>.ocr.txt` 兜底文本；上传响应与消息引用同时给出两路径。
- OCR 识别失败或依赖缺失不再整体拒绝（旧 422/503）：返回 200 + 原图保留 +
  `ocr_error` 显式告警，不生成 OCR 文本文件、不静默以猜测内容继续。

## 平台登录与预激活

- 用户账密登录（`/api/auth/login`）只完成 Web 准入并取得平台业务身份；
- 创建会话后，服务端用账号库内置的 `phone`/`code` 对该会话的 MCP 凭据调用
  一次 `login` 完成授权激活（后台初始化 `initialize_session` →
  `call_login_tool`），MCP 接入 Token 因此已绑定业务 Token；
- 因此 Agent **不应调用 `login`，也不应索要手机号/验证码**，直接调用
  `get_*` 云端工具；`login` 在门禁中仍属绝对禁止，防止 Agent 使用任意账号；
- 激活失败会使会话转 `failed`（`session_failed` 事件含可辨识原因，失败记录
  保留供删除），写路径拒绝直至重建，不会出现“会话可用但云端一查就报未登录”；
  若账号库未配置 `phone`/`code`，则不会激活，云端查询不可用，需要运维补配置。

## PDF 文档转结构化文本

- `document` 通道上传 PDF 后立即返回 `text_status=pending`；后端用 PyMuPDF
  在后台抽取为 `xlpa-input/<stem>.pdf.md`（表格转 GFM），完成后产
  `upload_text` 事件（含 `text_path`/`text_chars`）。
- 解析期间发送的消息会先等待后台抽取完成（最长 120 秒），避免模型读到尚未
  生成的旁路文件。
- 提取失败或扫描件无文本时：原 PDF 保留、上传仍成功，`upload_text` 载荷与
  前端提示显式 `warning`，不伪造"已转文本"。

## 产物来源与文档写入

- **来源 A（工作区）**：Agent 在会话工作区 `xlpa-output/` 生成的文本类文档，turn
  收尾扫描登记并产 `artifact` 事件。**工具结果不会自动落盘为产物**（无论多大），
  只有显式写入或白名单 MCP 工具的 `file_id` 才会产生下载卡片。
- **来源 B（mcp_server 原生产物）**：白名单工具
  （`generate_device_archive_template` / `get_device_archive_template_download` /
  `save_conversion_config` / `pack_bundle`）返回 `file_id` 时，后端立即用会话
  `mcp_token` 回源 `/api/archive/templates/<file_id>` 取字节落 `xlpa-output/`，
  再登记并产 `artifact` 事件；同一 `file_id` 只登记一次，回源失败产 `error` 事件。
  `file_id`、owner 摘要与 Token 不进事件、不进 URL。
- **确认/凭据交互**：需要确认或填写凭据的工具由前端确认卡片收集参数；Agent 被
  系统提示要求直接调用工具触发表单，不得在聊天中索要密码或让用户回复"确认"。
- **内置文档写入边界**：`Write`/`Edit`/`MultiEdit`/`NotebookEdit` 仅在
  `${会话工作区}/xlpa-output/` 内、且扩展名为文本类（md/txt/csv/json/html 等）
  时放行；越界路径、非文本扩展名、缺 `file_path` 一律拒绝且不可确认解除。
  `Bash` 与其他内置工具面保持关闭。

## 安全语义（记录在案）

- 票据与业务凭据均为服务端**内存态**：服务重启即全部失效，需重新登录；
- 准入（账号库）不等于写权限：写权限唯一判据是
  `permissions.json`（superAccounts）+ 平台业务登录结果；
- 业务 Token 绝不落盘、绝不进日志、绝不出现在任何 API 响应中。

## 测试

```powershell
cd webchat
.\.venv\Scripts\python -m pytest
```
