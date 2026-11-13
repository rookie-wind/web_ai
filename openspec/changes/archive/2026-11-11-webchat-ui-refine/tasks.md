<!-- 拆分方案须先经人工确认再实施。每 task 一个纵向切片：先写命中"通过标准"的失败
     测试确认红，再最小实现转绿；未红转绿禁止勾完成。前端为静态标记约定
     （test_static_frontend.py）；真实浏览器冒烟另行人工取证。
     测试命令：cd webchat && pytest tests/test_static_frontend.py::<test> -->

## 1. 移除自动全屏

- [x] 1.1 删除登录自动全屏
  - 前置：design D1；app.js tryImmersiveFullscreen + 登录调用。
  - 要做：删除 tryImmersiveFullscreen 函数与登录 submit 内调用；保留全视口 CSS。
  - 通过标准（失败测试）：`cd webchat && pytest tests/test_static_frontend.py::test_no_auto_fullscreen` 先红后绿（app.js 不含 requestFullscreen/tryImmersiveFullscreen）。
  - 依赖：无。

## 2. 先暂存后上传与 chip 修复

- [x] 2.1 暂存不立即上传 + chip ✕ 可见
  - 前置：design D2/D3；现即时上传 + chip ✕ 被裁。
  - 要做：upload-file change 改为暂存 {name, file}（不调 uploadFile）；renderAttachments 用 chip-name span + ✕ flex-shrink:0；CSS chip-name ellipsis、chip-delete flex-shrink:0。
  - 通过标准（失败测试）：`cd webchat && pytest tests/test_static_frontend.py::test_stage_before_upload tests/test_static_frontend.py::test_chip_delete_visible` 先红后绿（uploadStagedAttachments + chip-name 标记）。
  - 依赖：无。

- [x] 2.2 发送时上传暂存并合并引用
  - 前置：design D2；compose submit。
  - 要做：submit 时调 uploadStagedAttachments 上传暂存 File→构建 ref→合并文本送出→成功清空 chip；失败保留 chip + 报错。
  - 通过标准（失败测试）：`cd webchat && pytest tests/test_static_frontend.py::test_send_uploads_staged` 先红后绿。
  - 依赖：2.1。

## 3. 发送/停止切换按钮

- [x] 3.1 合一为切换按钮
  - 前置：design D4；现 btn-send + btn-abort 分离。
  - 要做：移除 #btn-abort；#btn-send 兼作切换（setTurnActive 控制发送/停止态）；submit 时 turnActive 走中止（二次确认 + /abort）否则发送；重载按 turn_running 恢复。更新既有 test_frontend_turn_serial 的 btn-abort 断言为 btn-send 切换。
  - 通过标准（失败测试）：`cd webchat && pytest tests/test_static_frontend.py::test_send_stop_toggle` 先红后绿（body 无 btn-abort，btn-send 切换标记）。
  - 依赖：2.2。

## 4. 移动端根治聚焦放大

- [x] 4.1 移动端 16px + select 占位
  - 前置：design D5；现 14px/13px 控件触发 Safari 放大。
  - 要做：@media(max-width:640px) 内 composer textarea/模型 select/确认卡 input font-size:16px；模型 select 加 disabled 占位 option + min-width；修 shrink:0→flex-shrink:0。
  - 通过标准（失败测试）：`cd webchat && pytest tests/test_static_frontend.py::test_mobile_16px_antizoom` 先红后绿（font-size:16px + 占位 option 标记）。
  - 依赖：无。

## 5. 回归与验收

- [x] 5.1 全量回归绿 + code-review 双轴 + 浏览器冒烟
  - 前置：1–4 全绿。
  - 要做：跑回归 + 双轴评审；人工浏览器冒烟（上传前删 chip、发送/停止切换、iPhone 聚焦不放大、文件 picker 不再退出全屏）。
  - 通过标准（可执行判据）：`cd webchat && pytest` 全绿 + 主基线无新增失败；code-review Standards 与 Spec 双轴过；浏览器冒烟取证。
  - 依赖：1–4。
  - 结果：webchat 243 全绿（+2 新增失败保留/sticky 测试）；主基线 12 failed/763 passed 与既有基线一致无新增。双轴评审发现 D2 失败保留缺陷与 10 行超长/31 处缺注解/若干缺 docstring，均按 TDD 修复转绿；冒烟取证见 C:\Users\song\AppData\Local\Temp\smoke_refine_evidence\（登录后 fullscreenElement=null、chip ✕ 可见且删除生效、发送时才上传、失败 chip 保留可重试、停止态/二次确认/中止提示/重载恢复、移动端 textarea/select 16px）。