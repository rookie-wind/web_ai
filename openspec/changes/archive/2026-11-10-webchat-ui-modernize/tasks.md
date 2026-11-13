<!-- 拆分方案须先经人工确认再实施。每个 task 一个纵向切片：先写命中"通过标准"的
     失败测试并确认红，再最小实现转绿；未红转绿禁止勾完成。前端测试为静态标记约定
     （test_static_frontend.py，GET / 与 /static 资源断言标记）；真实浏览器演练另行人工取证。
     测试命令：cd webchat && pytest tests/test_static_frontend.py::<test> -->

## 1. 品牌与设计 token

- [x] 1.1 品牌改名"XLPA 智体"
  - 前置：design D4；index.html:6/14/31 三处品牌文案。
  - 要做：title/登录 h1/topbar 改"XLPA 智体"；消息泛称"助手"保留。
  - 通过标准（失败测试）：`cd webchat && pytest tests/test_static_frontend.py::test_brand_xlpa_zhiti` 先红后绿（含"XLPA 智体"、topbar 不含"XLPA 助手"）。
  - 依赖：无。

- [x] 1.2 形式化设计 token
  - 前置：design D6；现有 :root 色板。
  - 要做：扩展 spacing/type/radius/shadow token（--space-*/--text-*/--radius-*/--shadow-*）。
  - 通过标准（失败测试）：`cd webchat && pytest tests/test_static_frontend.py::test_design_tokens` 先红后绿。
  - 依赖：无。

## 2. 一体化 composer 与上传重构

- [x] 2.1 composer 卡片结构重构
  - 前置：design D1；现两行 composer。
  - 要做：index.html 重构为 #attachment-chips + #msg-input + .compose-toolbar（#btn-attach/#model-select/#btn-abort/#btn-send）；移除 #upload-channel 与 #btn-upload。同步更新既有 test_upload_channel_auto_detect_and_default_document 的手动下拉断言（保留 channelForFile 断言）。
  - 通过标准（失败测试）：`cd webchat && pytest tests/test_static_frontend.py::test_composer_card_structure` 先红后绿（含 attachment-chips/compose-toolbar/btn-attach，不含 upload-channel/btn-upload）。
  - 依赖：1.2。

- [x] 2.2 上传并入［＋］纯自动通道
  - 前置：design D2；channelForFile/uploadFile 复用。
  - 要做：btn-attach 触发隐藏 upload-file，change 时 channelForFile 自动定通道上传，上传期间禁用 btn-attach；移除手动通道读取。
  - 通过标准（失败测试）：`cd webchat && pytest tests/test_static_frontend.py::test_attach_button_auto_channel` 先红后绿（btn-attach 关联 channelForFile，无 upload-channel.value 读取）。
  - 依赖：2.1。

- [x] 2.3 附件 chip 呈现与删除
  - 前置：design D3；state.pendingAttachments。
  - 要做：上传成功推入 pendingAttachments 并渲染 chip（文件名+✕）；✕ 移除该引用重渲染。
  - 通过标准（失败测试）：`cd webchat && pytest tests/test_static_frontend.py::test_attachment_chip_delete` 先红后绿（pendingAttachments + chip 删除处理器标记）。
  - 依赖：2.2。

- [x] 2.4 发送合并附件引用
  - 前置：design D3；sendMessage。
  - 要做：sendMessage 合并文本与 pendingAttachments 引用送出后清空；引用不再追加进 textarea。
  - 通过标准（失败测试）：`cd webchat && pytest tests/test_static_frontend.py::test_send_merges_attachments` 先红后绿。
  - 依赖：2.3。

## 3. 移动端全视口与能力全屏

- [x] 3.1 全视口 app-like 布局
  - 前置：design D5；现有 @media。
  - 要做：#view-app 占满 100dvh（100vh 兜底）、#messages flex:1 滚动、composer 吸底、safe-area 适配。
  - 通过标准（失败测试）：`cd webchat && pytest tests/test_static_frontend.py::test_mobile_full_viewport` 先红后绿（100dvh + safe-area-inset 标记）。
  - 依赖：2.1。

- [x] 3.2 登录手势能力检测全屏
  - 前置：design D5；登录 submit 手势。
  - 要做：登录手势内 if(document.fullscreenEnabled) requestFullscreen().catch(降级)；不按 OS 分支。
  - 通过标准（失败测试）：`cd webchat && pytest tests/test_static_frontend.py::test_capability_fullscreen_on_login` 先红后绿（fullscreenEnabled + requestFullscreen 标记）。
  - 依赖：3.1。

## 4. 状态覆盖与回归

- [x] 4.1 组件状态与焦点/对比覆盖
  - 前置：design D6；ui-ux-pro-max 状态覆盖。
  - 要做：hover/focus-visible/disabled 态、empty/loading/error 提示、focus-visible 描边、对比度 AA。
  - 通过标准（失败测试）：`cd webchat && pytest tests/test_static_frontend.py::test_component_states_focus` 先红后绿（focus-visible + disabled 标记）。
  - 依赖：1.2、2.1。

- [x] 4.2 全量回归绿 + code-review 双轴 + 浏览器冒烟
  - 前置：1–4.1 全绿。
  - 要做：跑回归并双轴评审；人工浏览器冒烟（桌面 composer + 手机全视口/全屏）。
  - 通过标准（可执行判据）：`cd webchat && pytest` 全绿 + 主 pytest 基线无新增失败；code-review Standards（.qoder/rules）与 Spec（忠实实现本 change）双轴过；浏览器冒烟取证（附件 chip 删除、发送、中止、手机全屏降级）。
  - 依赖：4.1。