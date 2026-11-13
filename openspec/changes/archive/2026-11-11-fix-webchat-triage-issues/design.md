## Context

三个缺陷的定位与实测证据见 proposal.md（grill 会话结论，含探针数据：创建冷
10.4s/热 6.6s、登录 1.4s；iOS 真机截图顶栏被顶出；平台模型清单原始数据
`is_free=true` + `price_factor=0.1` 并存）。现状约束：

- 前端为零构建单页应用（`static/js/app.js` + `app.css`），无框架、无构建管线；
  移动端此前已做 100dvh + 16px 防放大（webchat-ui-refine，已实现未归档）。
- 后端 `runtime.create()` 同步串行完成 mint → `_activate()`（对 /mcp 完整 MCP
  握手 + 平台 login）→ `_ensure_client()`（SDK connect）→ `list_models()` +
  `set_model()`；`EventStore.append()` 不限事件类型、seq 单调（已核实）。
- 截图通道现状：临时落盘 → OCR → 原图删除、只写 `<stem>.ocr.txt`；OCR 失败
  422、依赖缺失 503。
- `webchat-ui-refine` change 已全部实现并回归绿但未归档，同改 `web-chat-ui`。

## Goals / Non-Goals

**Goals:**

- 移动端顶栏在任何键盘/滚动场景下完整可见（根治文档滚动余量）。
- 创建会话的"可对话反馈"与"实例就绪"解耦：点创建 1 秒内进入会话，初始化全程
  有状态反馈，失败可辨识、可回滚、可重试。
- 图片原图永不丢失；OCR 仅作兜底文本，失败显式降级。
- 模型成本标记口径统一为 `price_factor`。

**Non-Goals:**

- 不做会话创建的预热池/常驻实例池（容量与配额复杂度，另行立项）。
- 不做多模态消息直传（图片进聊天消息体）；图片仍经工作区文件由 Agent Read。
- 不改 OCR provider 协议与 PDF 提取通道；不改写门禁/租约/确认卡片语义。
- 不处理 iOS <15 的 fixed+键盘历史行为差异（真机验证兜底，见 Risks）。

## Decisions

### D1 移动端布局：fixed 沉浸替代文档流 100dvh

`#view-app { position:fixed; inset:0 }`，删除 `height:100vh/100dvh`；`enterAppView`
与 `doLogout` 复位 `window.scrollTo(0,0)` 并对 `document.activeElement` 失焦。

- 备选 (a) 仅切视图复位滚动：iOS 键盘再次弹起（发消息场景）残留会复发——键盘弹起
  时滚动是浏览器为露出输入框的合法滚动，收起后残留重现；(b) 仅 fixed：极老 iOS
  或异常路径无兜底。两者都做，fixed 根治 + 复位兜底。
- 键盘遮挡输入框风险：iOS 15+ 对 fixed 容器内聚焦输入框采用 visual viewport
  平移（键盘收起自动复位，无残留），输入框可达；topbar/compose 已有 safe-area
  padding 不受影响。桌面端 fixed 与 100dvh 视觉等价。
- 侧栏抽屉（`position:absolute; top:52px` 于 `.layout`）与 modal（fixed z-50）
  定位基准不变，无需联动改动。

### D2 异步创建：快路/慢路拆分 + 状态机 + 单点回收

- **快路**（`create()`）：配额检查（语义不变）→ 槽位 acquire（2s 超时不变）→
  mint → 工作区 → 注册会话（`status="creating"`）→ `session_started` 事件 →
  `asyncio.create_task` 启动慢路 → 返回。mint 失败在未注册状态下局部回滚
  （release 槽位 + 删工作区）后抛原异常。
- **慢路**（`initialize_session()`，后台任务 + `asyncio.wait_for(60s)` 总超时）：
  `asyncio.gather` 并行执行「平台激活」与「SDK connect + list_models」，随后
  串行 `set_model` 预选（依赖清单）。任一失败按 account_source 映射既有错误
  语义（InvalidQoderPat / SessionActivationFailed / DefaultAccountUnavailable）。
- **状态与事件**：`WebSession` 增 `status`（creating/ready/failed）、`status_error`、
  `init_task`。成功 → ready + `session_ready`；失败 → failed + `session_failed`
  （payload 含原因、不含凭据）。
- **单点回收纪律**：槽位 release 与 `user_counts` 减 1 只发生在 `close()`；
  慢路失败统一走 `close(reason="init_failed")` + 删除工作区（close 幂等：同步段
  置 closed，asyncio 单线程下无竞态窗）。`close()`/`delete_session` 先 cancel +
  await `init_task` 再回收。
- **竞态守卫**：慢路每个 await 后检查 `session.closed` 与 `runtime.get(sid)`，
  已删即中止且不写事件（沿用 PDF 后台提取同款范式）。
- **写路径守卫**：`send_message`/`set_model`（sessions_api）与 `upload`
  （artifacts）在 `status != "ready"` 时 409「会话初始化中，请稍候」；lease、
  SSE、history、abort、close 不加守卫（abort 对无轮次会话本就安全返回）。
- **列表暴露**：`GET /api/sessions` 增加 `status`/`status_error`。
- **记住 PAT 时序**：`set_qoder_pat` 从 API 层同步段移到慢路就绪分支。
- 备选 (c) 纯提示不改架构：用户明确选择异步（收益：点创建即进会话、PAT 失败
  回填重试）；备选全量预热池：占用 max_instances 配额、复杂度高，不做。

### D3 截图通道双落盘

原图经 `unique_path` 直接落 `xlpa-input/<原扩展名>`，再读字节 OCR：

- OCR 成功 → 写 `<stem>.ocr.txt`，响应含原图 path/name + `ocr_path`/`text`/
  `confidence`；OCR 失败（OcrFailed）/依赖缺失（OcrUnavailable）→ 200 + 原图
  信息 + `ocr_error` 告警，不生成 OCR 文件；原图落盘 OSError → 显式 4xx/5xx。
- 前端 `uploadStagedAttachments` 引用文案：成功为「已上传图片 <原图路径>（助手
  可直接查看）；OCR 文本 <ocr_path>（读不了图时用）」，降级时说明 OCR 失败原因。
- 实现后需真实会话实测 Agent Read 直读图片；若 CLI/模型不支持读图，引用文案
  降为 OCR 优先（`ocr_path` 在前）。该实测不改变 spec 行为（双落盘已保证两者
  可读），仅影响文案顺序。

### D4 模型成本标记口径

`loadModels` 渲染：`m.price_factor != null ? "×"+m.price_factor : (m.is_free ?
"免费" : "")`。实测 13 个模型全部同时携带两字段，仅 Qwen3.8-Flash 为
`is_free=true`+`price_factor=0.1`——统一显示 ×0.1。计费真相属平台账单范畴，
不在 webchat 侧做防御。

### D5 前端初始化反馈与失败回弹

- `openSession` 按列表 meta.status 设初始态；初始化中禁用 textarea/发送/附件/
  模型下拉 + sticky 提示「正在初始化（连接平台/加载模型）…」；`session_ready`
  → 解锁 + `loadModels` 重拉 + notify；`session_failed` → 错误横幅 + 刷新列表。
  history 重放与 SSE 实时两条路径都能到达状态事件（重放含 ready/failed 时同样
  应用状态）。
- `setTurnActive` 尊重初始化锁（initLock 时发送按钮一律 disabled，避免轮次状态
  覆盖初始化禁用）。
- 失败回弹：记录最近一次创建的 `{session_id, account_source, pat, remember}`；
  `session_failed` 命中该 session_id 时重开创建对话框、回填错误与输入（PAT 掩码
  保持），非 byo 失败仅展示列表失败态。
- 会话列表：creating「（初始化中…）」、failed「（创建失败）」且仅保留删除按钮。

## Risks / Trade-offs

- [iOS fixed 容器内键盘遮挡输入框（iOS <15 老行为差异）] → 实机验证是验收项；
  退路为 visualViewport resize 事件同步容器位置（已预留方案，不预先实现）。
- [慢路与删除/关闭竞态写已删会话] → 慢路 await 后逐点检查 closed/存在性 +
  close 先取消慢路；测试覆盖"初始化中删除"。
- [信号量/配额双重释放或泄漏] → 单点回收纪律（仅 close 释放）+ 状态机测试
  断言"失败后立即再创建成功"。
- [慢路挂起（平台网络黑洞）] → wait_for 60s 总超时兜底转 failed，可配。
- [创建弹窗秒回后用户连点重复创建] → 不新增防线（与现状多击行为一致），
  列表可删除误建会话。
- [现有测试假设 create 返回即就绪] → 慢路抽为独立方法，生产后台调用、测试显式
  await；适配量集中在 test_runtime/test_sessions_api。
- [webchat-ui-refine 未归档导致 delta 基线不一致] → 本变更任务第 0 步先归档
  sync webchat-ui-refine，再应用本变更（同改 web-chat-ui 的 requirement）。

## Migration Plan

1. 归档 `webchat-ui-refine`（sync 其 web-chat-ui delta）。
2. 后端：runtime 状态机 + sessions_api 守卫/status + artifacts 双落盘（测试先行，
   每切片先红后绿）。
3. 前端：fixed 布局 + 复位；初始化反馈/失败回弹/price_factor。
4. 全量回归（webchat pytest）+ 探针复测（快路 <2s）+ 人工真机清单
   （iPhone 登录后顶栏完整、键盘收起无残留、创建即进会话、传图双落盘、下拉 ×0.1）。
5. 回滚策略：单 commit 系列，revert 即回同步创建与旧布局；无数据迁移
   （状态与事件均在内存/JSONL，兼容旧事件流）。

## Open Questions

（无——模型读图能力实测仅影响引用文案顺序，已列入任务验证步骤，不阻塞方案。）
