# add-webchat-rich-rendering

## Why

webchat 前端目前把助手回复当纯文本渲染（`app.js` 中 `textContent += text`），
模型输出的 markdown 表格、代码块、流程图一律显示为原始字符（竖线、井号、
反引号直接暴露给用户）。在公网交付、现场与移动端用户直接使用的场景下，
协议点表、配置样例、流程说明这类高频内容几乎不可读。前端无 CSP 头，
一旦引入 HTML 渲染，XSS 面从"无"变"有"，必须同步建立防线。

## What Changes

- 助手消息升级为 markdown 富渲染管线：标题/列表/表格/行内代码/代码块，
  代码块带语法高亮（core + 白名单语言）与一键复制按钮
- 检测 ```mermaid 代码块并以 mermaid 渲染为流程图/时序图/状态图；
  解析失败降级为显示原始源码 + 错误提示条，不吞内容
- 流式渲染时机：text_delta 节流重渲染（约 300ms）+ 本轮文本结束时最终
  精确渲染；未闭合语法按纯文本兜底
- 用户消息保持纯文本，仅助手消息走 markdown 管线
- 所有助手 HTML 渲染前必须经 DOMPurify 白名单消毒；mermaid 以
  securityLevel: strict 运行；渲染失败一律降级纯文本（不可妥协纪律）
- 第三方库 vendored 至 `static/vendor/`（marked、DOMPurify、
  highlight.js、mermaid），零 CDN 依赖；mermaid 经 dynamic import 懒加载
- 后端为全部响应增加 Content-Security-Policy 头
  （default-src 'self'; style-src 'self' 'unsafe-inline';
  img-src 'self' data:; connect-src 'self'）
- 会话系统提示追加点（`WEBCHAT_SYSTEM_APPEND`）增加输出格式约定：
  表格用 markdown 表格语法、流程图输出 mermaid 代码块；
  SKILL.md 与 agent_assets 资源包零改动
- 移动端宽表格在气泡内横向滚动（不做全屏查看层）

## Capabilities

### New Capabilities

- `web-ui-content-security`: webchat 页面内容安全基线 —— 全部响应携带
  CSP 头（script-src 'self' 等）、第三方渲染脚本仅经同源 vendored 静态
  目录加载、渲染管线消毒纪律（DOMPurify + mermaid strict + 失败降级）
  的行为契约

### Modified Capabilities

- `web-chat-ui`: 新增助手消息富渲染相关 Requirement——纯 textContent
  追加升级为经消毒的 markdown 渲染（表格/代码高亮/mermaid/复制按钮），
  并新增流式节流渲染、渲染失败降级、用户消息保持纯文本、移动端宽表格
  横向滚动等 Requirement 与 Scenario。既有「消息流必须实时渲染完整事件
  并支持断线回看」Requirement 的场景（断线重连、刷新回看、未知事件、
  空白气泡）语义不变，故以 ADDED 而非 MODIFIED 承载
- `agent-runtime-session`: 新增 Requirement「Web 会话系统提示必须约定
  富内容输出格式」——`WEBCHAT_SYSTEM_APPEND` 追加表格用 markdown 表格、
  流程图输出 mermaid 代码块的输出约定；不动 SKILL.md 与 agent_assets
  资源包，IDE 路径与既有会话语义不受影响

## Impact

- `webchat/webchat/static/`：`index.html`（vendor 引入）、`app.js`
  （渲染管线替换 textContent 追加）、`app.css`（表格/代码块/mermaid
  容器样式）、新增 `static/vendor/`（四个 vendored 库）
- `webchat/webchat/api.py`：CSP 响应头 middleware
- `webchat/webchat/sdk_runtime/adapter.py`：`WEBCHAT_SYSTEM_APPEND`
  追加输出格式约定文本
- `webchat/tests/`：`test_static_frontend.py` 补 marker 断言；新增 CSP 头
  测试
- 不改事件契约（text_delta 等事件结构不变）、不改 MCP Server、
  不改 SKILL.md 与 agent_assets、无新后端存储
- 铁律：无失败测试不得写实现；无转绿测试不得勾 task
