## Why

现有 webchat 前端 composer 是"上传通道下拉 + 独立上传按钮 + 文本框 + 发送/停止"
的分散两行布局，附件无预览/删除入口，品牌仍叫"XLPA 助手"；移动端虽响应式但未占满
视口、无沉浸全屏。用户已实测手机经内网 WiFi 可达（网络零改造），诉求转为 UI 体验：
参考现代对话产品（截图）重构 composer、统一品牌为"XLPA 智体"、移动端获得"小程序般"
的全视口沉浸感。按 ui-ux-pro-max 方法论在现有零构建栈内形式化设计 token 与状态覆盖。

## What Changes

- **品牌改名**：title/登录 h1/topbar 的"XLPA 协议转换助手"/"XLPA 助手"统一为
  **"XLPA 智体"**（消息中对 AI 的泛称"助手"保留）。
- **一体化 composer**：重构为单一卡片——附件 chip 行（文件名/缩略 + ✕ 删除、支持多
  文件）＋自适应 textarea＋底部工具栏（［＋］加文件、模型下拉、中止、发送）。
- **上传入口并入＋**：点［＋］选文件即上传，通道按扩展名自动识别；**移除独立"上传
  通道"手动下拉与独立"上传"按钮**（行为变化：纯自动通道，无手动 override）。
- **附件可删除**：已附加文件以 chip 呈现，发送前可逐个✕删除。
- **移动端全视口沉浸**：CSS 全视口 app-like 布局（`100dvh`、composer 吸底、消息区
  滚动、safe-area 适配）；登录手势按 `document.fullscreenEnabled` **能力检测**尝试
  `requestFullscreen()` 隐藏浏览器 chrome，不支持则优雅降级为布局占满（**不按 OS 分支**）。
- **设计 token**：形式化 spacing/type/color/radius/shadow token，覆盖 empty/loading/
  error 状态与焦点/对比度（ui-ux-pro-max 方法论）。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `web-chat-ui`: MODIFIED「产物必须可在页面上传与下载且凭据不进 URL」（上传入口改为
  composer［＋］、纯自动通道，保留既有 5 个 Scenario 行为）；ADDED「输入区必须为一体化
  composer 且附件可删除」「移动端必须全视口沉浸并按浏览器能力全屏」。既有路由前缀提示、
  停止入口、模型下拉、账号对话框等要求保持不变。

## Impact

- 代码：`webchat/webchat/static/index.html`、`static/app.css`、`static/js/app.js`
  （composer DOM/样式/交互、品牌文案、全屏能力检测、附件 chip）。
- 测试：`webchat/tests/test_static_frontend.py`（静态标记约定）；上传通道相关既有断言
  随手动下拉移除而调整。
- 不变：后端 API、上传通道自动匹配逻辑（channelForFile）、凭据不进 URL、写门禁/确认
  卡片、SSE 事件流、模型/账号选择行为。
- 方法论：ui-ux-pro-max（设计 token + 状态覆盖）；零构建 vanilla HTML/CSS/JS，不引框架。
- 网络：零改造（内网 WiFi 已实测可达）；全屏按浏览器能力降级，不依赖 HTTPS/PWA。