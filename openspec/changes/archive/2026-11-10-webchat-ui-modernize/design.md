## Context

动机见 proposal.md「Why」；行为契约见 specs/web-chat-ui delta。当前实现约束（已核实）：

- 零构建 vanilla：`static/index.html` + `app.css`（`:root` 已有 --bg/--panel/--line/
  --text/--muted/--primary/--danger/--ok/--radius）+ ES 模块 `js/app.js`/`api.js`/`sse.js`。
- composer 现为两行：`#upload-channel` 手动下拉 + `#upload-file` + `#btn-upload`；
  `#msg-input` textarea + `#btn-abort` + `#btn-send`。
- 上传流程（`app.js:474`）：选文件→`channelForFile` 自动通道（`app.js:463`）→
  `uploadFile` API 落工作区→把引用文本 `ref` **追加进 textarea**（`app.js:500`）→
  发送时随文本送出。`channelForFile`/上传 API 不变。
- 移动端已有 viewport meta + `@media (max-width:640px)` 抽屉侧栏，但未占满视口、无全屏。
- 品牌文案：`index.html:6/14/31`（title/登录 h1/topbar）。

## Goals / Non-Goals

**Goals:**

- 一体化 composer（附件 chip + 自适应输入 + 工具栏），附件发送前可删除。
- 品牌统一"XLPA 智体"；移动端全视口沉浸 + 按浏览器能力全屏。
- 按 ui-ux-pro-max 形式化设计 token 与状态覆盖（empty/loading/error/focus/对比）。

**Non-Goals:**

- 不引框架/Tailwind（保持零构建）；不做 PWA/加主屏幕/HTTPS（全屏按能力降级）。
- 不改后端 API、上传通道自动匹配逻辑、凭据不进 URL、写门禁/确认卡片、SSE、模型/账号选择。
- 不按 OS 硬分支全屏；不做原生 App。

## Decisions

**D1 — 一体化 composer 结构。** `#compose-form` 重构为单卡片：`#attachment-chips`
行（附件 chip）＋ `#msg-input`（自适应增高）＋ `.compose-toolbar`（`#btn-attach`［＋］
+ 隐藏 `#upload-file`、`#model-select`、`#btn-abort`、`#btn-send`）。移除 `#upload-channel`
手动下拉与 `#btn-upload`。保留路由前缀提示文案。*否决*：保留两行分散布局（不符截图）。

**D2 — 上传并入［＋］，纯自动通道。** `#btn-attach` 触发隐藏 `#upload-file`；change
时 `channelForFile(name)` 自动定通道→`uploadFile` 上传；上传期间禁用 `#btn-attach`
显示忙碌。复用既有上传 API 与 `channelForFile`，无手动通道 override。*否决*：保留手动
通道下拉（用户要纯自动；spec 改为 MUST NOT 手动下拉）。

**D3 — 附件 chip 与删除语义。** 新增 `state.pendingAttachments[]`（{name, ref}）。
上传成功推入并渲染 chip（文件名 + ✕）；✕ 从 pending 移除该引用（**文件已落工作区，
仅移除引用，不物理删除**，留存无害）。`sendMessage` 把文本与 pending 引用合并送出后
清空 pending。引用不再追加进 textarea（改由 chip 承载）。*否决*：继续往 textarea 塞
原始 ref（不直观、无法单独删除）。

**D4 — 品牌改名。** `index.html` title/登录 h1/topbar 三处改"XLPA 智体"；消息泛称
"助手"保留。纯文案，无行为契约。

**D5 — 移动端全视口 + 能力全屏。** CSS：`#view-app` flex 列向占满 `100dvh`，`#messages`
flex:1 独立滚动，composer 吸底，`padding: env(safe-area-inset-*)` 适配刘海。登录 submit
手势内：`if (document.fullscreenEnabled) document.documentElement.requestFullscreen()
.catch(()=>{})`——按能力检测，支持则隐藏 chrome，被拒静默降级为布局占满。*否决*：按
iOS/Android 分支（用户纠正：是浏览器能力差异）；PWA/加主屏幕（用户排除）。

**D6 — 设计 token（ui-ux-pro-max）。** 扩展 `:root`：spacing scale（--space-1..6）、
type scale（--text-sm/base/lg/xl）、radius（--radius-sm/md/lg）、shadow（--shadow-1/2）；
沿用并精修现有色板（primary 蓝）。组件覆盖 hover/focus-visible/disabled 态；empty/
loading/error 状态；focus-visible 描边、对比度达 WCAG AA。*否决*：引入外部设计系统库
（零构建约束）。

## Risks / Trade-offs

- [既有上传测试断言手动通道下拉/上传按钮] → 更新 `test_static_frontend.py` 上传断言为
  ［＋］控件与 chip 标记；`channelForFile` 断言保留。
- [iPhone Safari 拒绝全屏] → 能力检测 + `.catch` 静默降级，不报错、不阻断登录。
- [附件引用合并语义变化] → 发送时合并 pending refs，保持 agent 收到的引用文本格式不变。
- [删除 chip 不删工作区文件] → 明确为"移除引用"语义；文件留存无害（按保留期清理）。
- [100dvh 旧浏览器兼容] → 以 `100vh` 兜底再覆 `100dvh`。

## Migration Plan

- 后端零改动；上传 API、`channelForFile`、凭据头不变。
- 前端 DOM/样式/交互重构；既有上传相关静态测试断言随手动下拉移除而更新。
- 回滚：还原 index.html/app.css/app.js 即回到两行 composer 与旧品牌文案。