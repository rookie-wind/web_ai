> 四要素（需求文档 §7 裁剪：C7 范围含公网门控与前端 UI，见 proposal）
>
> - **前置条件**：C1~C6 全部完成（已满足）；CN-SDK 部署契约（§7.3 规则 5）
>   适用于验收与部署环节。
> - **要做的事**：mcp_server 端点分级门控 + 部署前置清单；webchat 后端验收
>   前提修复（授权激活/身份提取/限流真实 IP）；webchat 单页前端
>   （登录/会话/事件流/确认卡片含参数摘要/ask_user/上传下载/租约管理）；
>   AC-1~AC-4 与 V11 端到端演练留证。
> - **通过标准**：门控矩阵单测全绿；webchat pytest 与主 pytest 基线全绿；
>   AC 四条逐条有证据（截图/输出归档 `validation/public-access-hardening/`）；
>   IDE 回归零变化；部署清单逐项核验记录；真实链路事件流出现 `tool_call`
>   且不再出现 `NOT_LOGGED_IN`（授权激活生效的可执行判据）。
> - **顺序与依赖**：1（门控）与 2~4（后端修复+前端）可并行；**2.3 是 6（演练）
>   的硬前置**，未生效则 AC-1/AC-2 不可开始；5（清单）依赖 1；
>   6 依赖全部；7 收口。

## 1. mcp_server 公网门控

- [x] 1.1 `server.py` 新增配置读取：`MCP_PUBLIC_MODE`（默认 0）、
  `MCP_PUBLIC_ALLOWLIST`、`MCP_TRUSTED_PROXY`；**新建** `mcp_server/.env.example`
  （当前并不存在此文件，按 `permissions.template.json` 的模板范式出）与
  `mcp_server/README.md` 同步说明，并写明 `.env` 仅由 `start.bat` 解析、
  `python server.py` 直起不加载；验证 pytest：默认值与解析。
- [x] 1.2 实现真实客户端 IP 解析：仅当直连来源命中 `MCP_TRUSTED_PROXY`
  时采信 `X-Forwarded-For` 最左值，否则用 `scope.client`；验证 pytest：
  伪造 XFF（无信任代理）不改变本机/远程判定。
- [x] 1.3 实现路由层 `_exposure_gate(path, client_ip)` 单一入口，端点三类
  划分（展示类 / ticket+owner 下载类 / bearer 既有类）；公网模式下展示类
  非本机且非 allowlist → 403（不回显 allowlist 与 Token）；验证 pytest：
  模式 on/off × 本机/远程/allowlist × 三类端点矩阵，off 时行为与基线
  逐一一致。
- [x] 1.4 URL 凭据端点公网收紧：templates 下载非本机来源要求 Bearer 且
  `derive_owner_id(token)` 与 URL `owner` 一致（无/无效 401、不一致 404、
  一致 200）；`/api/logs` 非本机来源 MUST NOT 采信 `?token=` 查询串回退、
  仅接受 Bearer 头；本机保持既有行为；验证 pytest：四种组合 + 本机
  不受影响 + logs 远程 `?token=` 被忽略。
- [x] 1.5 `list_mcp_tools` 与 `/mcp` 鉴权路径确认零改动：既有 77 工具、
  `/mcp` Bearer 校验、mint 双条件准入行为不变；验证：主 pytest 全绿 +
  `list_mcp_tools` 输出与 C6 基线比对仅无差异。

## 2. webchat 后端：gate 参数摘要与验收前提修复

- [x] 2.1 adapter `_pre_tool_use` 拒绝分支 payload 增 `arg_summary`：从
  tool_input 白名单键（brand/model/plan_id/task_id/台数/文件名等）提取，
  脱敏截断；非白名单键一律不进 payload；`execute_archive_task` 类摘要经
  plan_id/task_id 反查计划域数据（台数/品牌型号，design D5 摘要源分层），
  反查不足时标记"摘要不可用"；验证 pytest：白名单提取、敏感键
  （password/token/验证码）不出现、超长截断、反查分支与降级标记。
- [x] 2.2 confirm 端点与 `gate_blocked` 回放链路带摘要（事件 payload 落
  event_store 可重放）；验证 pytest：刷新后历史事件仍含 arg_summary。
- [x] 2.3 **会话授权激活**（design D9，AC 演练硬前置）：`runtime.create` mint
  成功后、实例启动前，用该接入凭据对 `/mcp` 调一次
  `login(account.phone, account.code)`；激活失败 MUST 使会话创建失败并返回
  可辨识原因；MUST NOT 要求用户输入手机号或短信验证码。验证 pytest：
  mock `/mcp` 断言 login 被调用一次且失败时不产生会话记录；回归判据：
  真实链路事件流中 `tool_call` 事件数 ≥ 1 且不出现 `NOT_LOGGED_IN`。
- [x] 2.4 **身份提取对齐**（design D10）：`platform_auth._PHONE_KEYS` 补
  `mobilePhone`；`_dig` 取值改为 `str()` 宽容以接受整型 `userId`（与
  mcp_server `permissions.extract_account_identity` 行为一致）。验证 pytest：
  给定 `{data: {user: {userId: 55, mobilePhone: "139..."}}}` 实测形状，
  `business_user_id`/`phone` 均提取成功；命中 superAccounts 时 `is_super=True`。
- [x] 2.5 **登录限流真实客户端 IP**（design D11）：`_client_ip` 增加可信代理
  判定（未配置时只用直连地址、不采信任何转发头），并把账号级与来源级
  阈值拆为两个配置项（来源级显著放宽）。验证 pytest：伪造 XFF 不改变计数
  维度；命中信任代理时按 XFF 最左值分桶；不同来源的失败互不影响。

## 3. webchat 前端骨架（零构建单页）

- [x] 3.1 新增 `webchat/static/`（index.html + css/js 原生 ES 模块），
  FastAPI StaticFiles 挂载，`/` 出登录页；凭据仅存内存，全部 API 经
  Authorization 头；验证：浏览器打开 8800 出现登录页，未登录无会话
  数据请求（Network 面板留证）。
- [x] 3.2 登录/登出界面：调用既有 `/api/auth/*`，失败脱敏提示、不回显
  口令；验证 pytest（API 侧不变）+ 手工冒烟截图。
- [x] 3.3 会话管理界面：列表/创建/关闭/删除，配额 409 明确报错文案，
  多会话并行切换；进入会话先取写租约、丢失自动重取且不当作业务失败
  展示（含发消息路径，spec 租约场景）；验证冒烟：两会话并行各跑一条
  消息互不干扰；租约过期后发消息自动恢复成功。

## 4. webchat 前端：事件流与交互闭环

- [x] 4.1 消息发送与 SSE 渲染：text_delta 增量、tool_call/tool_result
  可读折叠展示（工具名+参数摘要，无原始凭据）、断线 EventSource 自动
  重连带 last-event-id、刷新后 history 回放；`type=unknown` 事件安全忽略或
  降级展示；本轮无任何可见文本时 MUST 回落展示本轮最终结果（不出现空白
  气泡），“本轮结束”判据取 `turn` 字段而非事件序号；验证冒烟：中途断网 5s
  重连后事件无缺口（截图对照）。
- [x] 4.2 确认卡片：渲染 `gate_blocked` 的 tool_name + arg_summary，
  确认按钮调 `/confirm` 铸票并展示结果，拒绝/关闭不铸票；ask_user 事件
  呈现提问与补充输入框，提交走 messages 续跑；验证冒烟：建档演练中
  卡片摘要与实际写入参数一致；未确认时平台零写入。
- [x] 4.3 上传与产物下载：文件选择上传（表格/文档/图片，走既有通道）
  引用进消息；artifact 事件出下载按钮，经 header/grant 代理取回，
  URL 无凭据；验证冒烟：下载成功且浏览器历史无 token 串。
- [x] 4.4 移动端响应式：布局在 375px 宽度可用，确认卡片完整摘要 +
  按钮触达；验证：手机浏览器（或 devtools 模拟）完成一次确认闭环截图。
- [x] 4.5 写租约管理：前端调用 `/api/sessions/{id}/confirm` 前确认持有租约，
  冲突（409，现网实测：缺 `x-holder-id` 即 409）时先取租约再重试，不把
  租约错误暴露为业务失败；租约过期可重新获取并重发；验证冒烟：租约过期后
  点击确认能自动恢复并完成写入。

## 5. 公网部署前置清单

- [x] 5.1 `docs/deployment/` 新增公网前置清单：对外形态与证书双轨
  （Caddy 自动证书 / 企业反代）、TLS 终止、SSE 关缓冲配置片段
  （flush_interval/proxy_buffering）、XFF 信任链、webchat 与 mcp_server
  暴露路径最小化（含 webchat 默认绑定与登录接口限流参数）、限流参数、
  巡检项；必须写明两个运行配置误区分：`.env` 仅由 `start.bat` 解析（直起
  `python server.py` 不加载），以及 `QODERCN_PERSONAL_ACCESS_TOKEN` /
  `WEBCHAT_MINT_SECRET` 的注入方式（落盘前 MUST 确认目标文件已在
  `.gitignore` 内；`webchat/.env` 当前并未被忽略）；每项附可执行判据；
  验证：清单评审通过（无 TBD 项）。
- [x] 5.2 本机模拟公网演练环境：`MCP_PUBLIC_MODE=1` + 非本机来源模拟
  （第二网卡/代理转发），按清单完成一次端到端配置验证并记录结果；
  验证：展示端点远程 403、票据下载远程需 Bearer、SSE 经代理不缓冲。

## 6. 端到端验收演练（AC-1~AC-4 + V11）

- [x] 6.1 AC-1 建档闭环（前置：2.3 已生效）：真实账号浏览器走完
  上传→计划→确认卡片→执行→回读→下载；含"未确认零写入"分支；证据
  （playwright 脚本输出 + 截图）落 `validation/public-access-hardening/`。
  <!-- 2026-10-30 演练：除『下载』腿外全部浏览器实证 PASS（未确认零写入
  分支＋确认→执行→回读→回退分支，证据见 6_1_exec_branch/）。
  2026-10-31 用户指示关闭归档：原阻塞（内置写工具关闭、来源 B 二期）已由
  `webchat-conversation-file-delivery` 解决（产物目录受限 Write + 白名单
  file_id 回源），下载管线机制由 C5 端到端测试背书；本次未再跑真机浏览器
  下载腿取证，作为偏差记录（见 evidence-index §7）。 -->
- [x] 6.2 AC-2 转换闭环：浏览器完成 MQTT 转换 文档→映射→配置→
  沙箱测试 passed→pack ZIP 下载解包 SHA256 校验；证据归档。
  <!-- 2026-10-31 用户指示关闭归档：转换 pack 的 file_id 下载路径已由来源 B
  桥接补齐；本次未跑真实转换闭环并留存新证据，作为偏差记录（见
  evidence-index §7）。 -->
- [x] 6.3 AC-3 IDE 回归：演练同期 IDE 连接既有工作流验证 + 主 pytest
  全绿 + `list_mcp_tools` total=77 比对；记录归档。
- [x] 6.4 AC-4 交互要求 1~5 逐条演示：每条给出通过/未通过结论与
  证据（截图或事件流片段）。
  <!-- 2026-10-31 用户指示关闭归档：req1/2/3/5 已有通过证据；req4『产物
  可查看下载』所需能力（模板 file_id 下载、产物目录写入）已实现，但未新增
  真实转换产物截图，作为偏差记录（见 evidence-index §7）。 -->
- [x] 6.5 V11 限流验证：多用户并发 + 同用户多任务压到配额拒绝与上游
  限流，记录现象与可承受并发数；证据归档。

## 7. 回归与收口

- [x] 7.1 全量回归：主 pytest 全绿、webchat pytest 全绿（含本变更新增
  测试），记录通过数；防漂移测试（test_grants）不受 arg_summary 影响。
- [x] 7.2 依赖声明收口：playwright 仅进 `webchat/requirements-dev.txt`（不进
  运行时依赖），演练脚本经 `PCA_TEST_BROWSER` 复用已有 chromium（日志中
  无重复下载）；验证：新建干净 venv 仅装 `requirements.txt` 能启动 webchat。
- [x] 7.3 证据索引 `validation/public-access-hardening/evidence-index.md`：
  交付清单、测试矩阵结果、AC 逐条结论、部署清单核验记录、偏差记录；
  `openspec validate` 通过后按流程归档本变更。
  <!-- 2026-10-31：索引补充 §7 关闭记录，`openspec validate --all --strict`
  通过后归档。 -->
