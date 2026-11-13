## Why

真机实测暴露三个体验缺陷，均有代码级根因与实测证据：①移动端登录后顶栏（含移动端
唯一的会话入口 ☰）被 iOS 键盘滚动残留顶出视口——登录时键盘弹起滚动文档，切视图后
偏移残留，`#view-app` 在文档流中（100dvh）且 body 按 iOS 大视口解析仍有 50~90px 滚动
余量，用户感知"页面不全"；②新建会话在请求内串行完成 mint→平台激活→CLI 连接→
list_models+set_model（实测冷 10.4s、热 6.6s），期间前端仅有按钮禁用、零进度反馈，
用户以为卡死；③图片上传走截图通道经 OCR 转文本后原图被丢弃（只留 `.ocr.txt`），而
Agent 的 Read 工具可直接读原始图片（真机会话中 Agent 自述并要求上传原图），原图
信息损失且提示文案让用户误以为"传图片变 txt 是 bug"。

## What Changes

- **移动端布局根治**：`#view-app` 由文档流 `100dvh` 改为 `position:fixed; inset:0`
  沉浸布局（文档无滚动余量，顶栏不可被推出），登录切视图/登出时复位文档滚动并
  失焦输入（兜底键盘残留）。
- **会话创建异步化**：`POST /api/sessions` 拆快慢两路——快路（配额检查+凭据铸造+
  工作区+注册）≤1s 返回；慢路（平台激活 ∥ CLI 连接+模型清单并行）后台执行，整体
  60s 超时。会话新增 `creating→ready/failed` 状态机，就绪/失败经 SSE 事件
  `session_ready`/`session_failed` 通知；失败自动回滚（撤销凭据、删工作区、单点
  释放槽位与配额）。发消息/传文件/切模型在非 ready 时 409。
- **截图通道双落盘**：图片按原扩展名落 `xlpa-input/`（模型可直接 Read），同时生成
  `.ocr.txt` 兜底；OCR 识别失败/依赖缺失不再 422/503 整体失败，降级为"仅原图 +
  显式告警"。引用消息文案同步更新（原图路径 + OCR 路径双说明）。
- **模型成本标记改口径**：下拉成本标记改用 `price_factor`（显示 `×N`），仅当
  无 `price_factor` 时才回落 `is_free` 显示"免费"（平台对 Qwen3.8-Flash 同时下发
  `is_free=true` 与 `price_factor=0.1`，自相矛盾，实测确认字段忠实转发自平台）。
- **创建过程前端反馈**：创建弹窗立即关闭并进入会话，输入区显示"正在初始化
  （连接平台/加载模型）…"并禁用发送；会话列表区分初始化中/创建失败；自带 PAT
  创建失败时自动重开弹窗回填错误与输入（不丢已输 PAT）。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `web-chat-ui`：
  - MODIFIED「移动端必须全视口沉浸布局」（`100dvh` 文档流布局 → `position:fixed`
    沉浸 + 切视图滚动复位；新增"键盘收起后顶栏完整可见"Scenario）
  - MODIFIED「前端必须可在移动浏览器正常使用」（新增"登录后顶栏完整可见、无需
    手动滚动/缩放"约束）
  - MODIFIED「输入区必须提供模型选择下拉」（成本标记口径：`price_factor` 优先，
    `is_free` 仅兜底）
  - MODIFIED「新建会话必须提供账号选择对话框」（异步创建：提交即进会话并反馈
    初始化状态；失败自动重开弹窗回填原因与输入；记住 PAT 仅在就绪后持久化）
- `agent-runtime-session`：
  - ADDED「会话创建必须异步完成并具备状态机」（快路/慢路拆分、并行化、60s 超时、
    `session_ready`/`session_failed` 事件、非 ready 写路径 409、删除/关闭/回收与
    慢路的竞态纪律、快路配额语义不变）
  - MODIFIED「会话接入凭据必须完成平台授权激活」（激活失败由"创建请求返回失败"
    改为"会话转 failed 并经事件告知"；仍 MUST NOT 留下可对话但云端必错的会话）
  - MODIFIED「会话必须绑定一个 Qoder 云账号且会话级固定」（PAT 校验失败由"拒绝
    创建请求"改为"会话转 failed"，原因可辨识）
  - MODIFIED「空闲会话必须自动回收」（回收扫描跳过 creating 状态会话）
- `web-artifact-delivery`：
  - MODIFIED「输入必须按三通道分道进入会话」（截图通道：原图与 OCR 文本双落盘，
    运行时可直接读原图）
  - MODIFIED「本地 OCR 必须为可插拔 provider 且失败显式提示」（识别失败/依赖缺失
    由整体拒绝改降级：保留原图 + 显式告警，MUST NOT 静默以猜测内容继续）

## Impact

- 代码：`webchat/webchat/static/app.css`、`webchat/webchat/static/js/app.js`、
  `webchat/webchat/runtime.py`、`webchat/webchat/sessions_api.py`、
  `webchat/webchat/artifacts.py`（`ocr.py` 协议不变）。
- API 行为：`POST /api/sessions` 语义变化（立即返回，不再等待激活/模型清单）；
  `GET /api/sessions` 响应新增 `status`/`status_error` 字段；事件流新增
  `session_ready`/`session_failed` 类型（EventStore.append 不限事件类型，已核实）；
  截图上传响应 payload 新增原图路径与 `ocr_path`/`ocr_error` 字段。
- 测试：`test_runtime.py`（create 拆段为两步调用）、`test_sessions_api.py`
  （status 字段与写路径守卫）、`test_artifacts_upload.py`（OCR 降级语义）、
  `test_static_frontend.py`（fixed 布局/初始化徽标/price_factor 标记）适配与新增。
- 前置依赖：`openspec/changes/webchat-ui-refine` 已实现完毕（243 全绿）但未归档，
  同改 `web-chat-ui` 能力，MUST 先归档 sync 再应用本变更。
- 假设（grill 推荐结论，可复核调整）：①byo PAT 失败采用"自动重开弹窗回填"方案；
  ②`webchat/README.md` 与 docs 架构文档补记行为变化（不新开 ADR）；③实现后需
  真机会话实测 Agent Read 直读原图能力，若不支持则引用文案降为 OCR 优先。
