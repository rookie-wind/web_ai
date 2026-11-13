## Context

动机见 proposal.md「Why」；契约见 specs/web-chat-ui delta。当前代码（modernize 已落地）：

- `app.js:122` `tryImmersiveFullscreen()` 在登录 submit 手势内调 `requestFullscreen`。
- 上传（`app.js` upload-file change）：选文件即 `uploadFile` 上传解析→推 `pendingAttachments`
  {name, ref}→渲染 chip；发送合并 ref。chip 文件名直接作 textContent，✕ 被 overflow 裁剪。
- 发送/停止分离：`#btn-send`（submit）+ `#btn-abort`（hidden，`setTurnActive` 控制显隐）。
- 表单控件字号：composer textarea 14px、模型 select 13px、确认卡 input 13px（iOS 聚焦放大）。
- 主 spec 已含 modernize 同步后的要求（本变更基于更新基线）。

## Goals / Non-Goals

**Goals:**

- 移除登录自动全屏；先暂存后上传（✕ 上传前可删、始终可见）；发送/停止切换按钮；
  移动端 16px 根治聚焦放大。

**Non-Goals:**

- 不改后端 API、通道自动匹配、凭据不进 URL、二次确认、SSE、模型/账号选择、品牌。
- 不引框架；不做 PWA/手动全屏按钮（沉浸靠布局）。

## Decisions

**D1 — 移除自动全屏。** 删除 `tryImmersiveFullscreen` 函数与登录 submit 内的调用；
保留全视口 CSS（`100dvh`/safe-area）。*理由*：文件 picker 必退出全屏（浏览器硬限制），
自动全屏与上传冲突。*否决*：picker 关闭后重请求全屏（仍跳动）；maximum-scale（伤无障碍）。

**D2 — 先暂存后上传状态机。** `pendingAttachments` 改存 `{name, file}`（File 对象，
**不含 ref**）。＋选文件→暂存+渲染 chip（不调 uploadFile）；✕→移除暂存 File；
**compose submit 发送时**遍历暂存 File 调 `uploadFile`（channelForFile 自动通道）→
构建 ref→与文本合并送出→成功后清空 chip。上传失败：保留该 chip + 报错（可重试发送或✕移除）。
*理由*：解决"直接解析了"，删除在上传前有意义。*否决*：即时上传（删除只移引用，文件已解析）。

**D3 — chip ✕ 可见。** `renderAttachments` 改为 chip 内先 append `<span class="chip-name">`
（文件名）再 append ✕；CSS `.chip-name{flex:1;min-width:0;overflow:hidden;white-space:nowrap;
text-overflow:ellipsis}`、`.chip-delete{flex-shrink:0}`；移除 chip 容器 overflow/ellipsis。
*理由*：匿名 flex 文本项 min-width:auto 不收缩，✕ 被裁。*否决*：仅缩 max-width（长名仍裁 ✕）。

**D4 — 发送/停止切换按钮。** 移除 `#btn-abort`，`#btn-send` 兼作切换：`setTurnActive(true)`
→按钮变停止态（停止图标/转圈 + class），`false`→发送态。compose submit：`state.turnActive`
为真→走中止（二次确认 + `/abort`），否则发送。`turn_done`/`turn_aborted`/`session_closed`
经 setTurnActive(false) 恢复。重载按 `turn_running` 恢复态。*否决*：保留双按钮（占空间、不符直觉）。

**D5 — 移动端 16px 防放大。** `@media(max-width:640px)` 内 `.compose textarea,
.compose-toolbar select, .card-gate input, .card-ask input { font-size:16px }`（iOS 阈值）；
模型 select 加 `<option value="" disabled selected>模型</option>` 占位 + min-width；
修 `.sidebar` `shrink:0`→`flex-shrink:0`。*理由*：Safari 对 <16px 控件聚焦自动放大不复原。
*否决*：`maximum-scale=1`（禁用用户缩放，伤无障碍）。

## Risks / Trade-offs

- [既有测试断言 btn-abort/即时上传] → 更新 `test_static_frontend.py`：停止入口断言改
  btn-send 切换态；上传断言改"暂存不立即上传"标记。
- [发送时上传失败] → 保留 chip + 报错，用户重试发送或✕移除；不静默丢弃。
- [移除 btn-abort 影响中止测试] → 中止逻辑复用（二次确认 + /abort 不变），仅入口改为 btn-send。
- [16px 改变移动端观感] → 仅移动端媒体查询内，桌面不变；字号略增换取不放大。

## Migration Plan

- 后端零改动。前端 DOM/JS/CSS 调整；既有静态测试断言随 btn-abort 移除/上传语义变化更新。
- 回滚：还原 app.js/app.css/index.html 即回到自动全屏/即时上传/双按钮/14px。