## Why

`webchat-ui-modernize` 落地后真实浏览器冒烟暴露四个体验缺陷：①登录自动全屏与上传
冲突——原生文件 picker 必退出全屏（浏览器硬限制），体验跳动；②附件附加即上传解析，
用户来不及删除（且 chip ✕ 被 overflow 裁剪看不见）；③发送与停止是两个按钮，移动端
占空间且不符"点发送变转圈、再点停止"的直觉；④移动端 Safari 对 font-size<16px 的表单
控件聚焦时自动放大页面且不复原，导致登录后页面"不完整、需手动捏合缩小"。

## What Changes

- **移除登录自动全屏**：删除 `tryImmersiveFullscreen` 及登录手势调用；保留全视口
  app-like 布局（"小程序感"靠布局占满，不隐藏浏览器 chrome）。
- **先暂存后上传**：＋选文件先暂存为 chip（**不上传/不解析**），✕ 在上传前真正移除；
  **发送时**才上传+解析+引用。修 chip ✕ 裁剪：文件名改 `chip-name` span
  （`flex:1;min-width:0;ellipsis`），✕ `flex-shrink:0` 始终可见。
- **发送/停止合一为切换按钮**：空闲＝发送；执行中＝转圈/停止图标，点击＝中止
  （保留既有二次确认）。`turn_done`/`turn_aborted`/`session_closed` 恢复发送态。
- **移动端根治聚焦放大**：`@media(max-width:640px)` 内 composer textarea/模型 select/
  确认卡 input 设 `font-size:16px`（iOS 不触发自动放大阈值，不用 maximum-scale 保无障
  碍）；模型 select 加 disabled 占位 option + min-width；修 `shrink:0`→`flex-shrink:0`。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `web-chat-ui`: MODIFIED「移动端必须全视口沉浸并按浏览器能力全屏」（移除登录自动全屏，
  保留全视口布局，更名为「移动端必须全视口沉浸布局」）、「产物必须可在页面上传与下载
  且凭据不进 URL」（先暂存后上传）、「输入区必须为一体化 composer 且附件可删除」（chip
  暂存语义 + ✕ 可见）、「执行中必须提供停止入口」（发送/停止切换按钮）、「前端必须可在
  移动浏览器正常使用」（16px 防聚焦放大）。保留各既有 Scenario 行为。

## Impact

- 代码：`webchat/webchat/static/index.html`、`static/app.css`、`static/js/app.js`
  （移除 fullscreen、stage-then-upload 状态、send/stop 切换、16px 媒体查询、chip-name）。
- 测试：`webchat/tests/test_static_frontend.py`（静态标记约定）；全屏/上传相关断言调整。
- 不变：后端 API、上传通道自动匹配、凭据不进 URL、写门禁/确认卡片二次确认、SSE、
  模型/账号选择、品牌"XLPA 智体"。
- 基线：modernize 已归档同步，本变更基于更新后的主 spec。