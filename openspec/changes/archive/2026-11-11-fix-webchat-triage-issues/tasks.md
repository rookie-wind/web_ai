<!-- 拆分方案已经 ⟨skill:grill-me⟩ 全分支对齐（用户逐题确认）。每 task 一个纵向切片：
     先写命中"通过标准"的失败测试确认红，再最小实现转绿；未红转绿禁止勾完成。
     前端为静态标记约定（test_static_frontend.py）；iOS 真机行为另行人工取证。
     测试命令：cd webchat && pytest tests/<file>::<test> -->

## 0. 前置（流程，非代码）

- [x] 0.1 归档 webchat-ui-refine
  - 前置：其 tasks 全勾、回归绿（已满足），用户确认归档。
  - 要做：⟨opsx:archive⟩ 同步其 web-chat-ui delta 到主 spec（本变更的
    「移动端必须全视口沉浸布局」等 MODIFIED 基线依赖归档后的主 spec）。
  - 通过标准：openspec/specs/web-chat-ui/spec.md 含改名后 requirement 且
    webchat-ui-refine 进入 archive。
  - 依赖：无。

## 1. 移动端布局根治（D1）

- [x] 1.1 #view-app 改 fixed 沉浸 + 切视图复位滚动/失焦
  - 前置：0.1；app.css `#view-app{height:100vh;height:100dvh}`、app.js
    enterAppView/doLogout 无复位。
  - 要做：app.css 改 `position:fixed; inset:0`；enterAppView 复位 scrollTo(0,0)
    并 blur activeElement；doLogout 同样复位。
  - 通过标准（失败测试）：`cd webchat && pytest
    tests/test_static_frontend.py::test_view_app_fixed_immersive
    tests/test_static_frontend.py::test_view_switch_resets_scroll` 先红后绿
    （CSS 含 fixed 标记；enterAppView/doLogout 含复位与失焦调用标记）。
  - 依赖：0.1。

## 2. 异步会话创建状态机（D2）

- [x] 2.1 WebSession 状态字段 + create 拆快路
  - 前置：runtime.create 同步完成全部初始化；WebSession 无 status。
  - 要做：增 status/status_error/init_task；create 只做配额/mint/工作区/注册/
    session_started/启动慢路任务即返回；初始化逻辑抽为 initialize_session()
    （生产后台调用，测试显式 await）。
  - 通过标准（失败测试）：`cd webchat && pytest
    tests/test_runtime.py::test_create_returns_fast_creating
    tests/test_runtime.py::test_initialize_session_ready` 先红后绿（create 后
    status=creating 且模型清单未就绪；显式 initialize 后 ready 且 models 填充）。
  - 依赖：无。

- [x] 2.2 慢路并行 + session_ready/session_failed 事件
  - 前置：2.1；现状激活与连接串行。
  - 要做：gather 并行「激活」与「connect+list_models」，成功 set_model 预选并写
    session_ready；失败按 account_source 映射错误语义并写 session_failed（payload
    含原因、不含凭据）。
  - 通过标准（失败测试）：`cd webchat && pytest
    tests/test_runtime.py::test_initialize_emits_ready_event
    tests/test_runtime.py::test_initialize_activation_failure_emits_failed` 先红后绿。
  - 依赖：2.1。

- [x] 2.3 失败回滚单点回收
  - 前置：2.2；现状失败路径直接 release 槽位。
  - 要做：慢路失败回滚收敛为单点 ``_rollback_failed_init``（撤销注册/配额/凭据/
    工作区/槽位各一次）；"记住 PAT"持久化移至就绪分支。
    注（实现顺序调整）：同步串联过渡期（2.1–2.4 期间 API 层仍同步 await
    initialize_session）下沿用"失败=无残留"语义；"失败会话记录保留 +
    close(reason="init_failed")"随 2.5 API 异步化一并切换并适配存量断言
    （spec 终态不变）。
  - 通过标准（失败测试）：`cd webchat && pytest
    tests/test_runtime.py::test_failed_session_releases_once
    tests/test_runtime.py::test_failed_then_recreate_succeeds` 先红后绿（失败后
    max_instances/user_counts 与初值一致、工作区目录不存在、立即再创建成功）。
  - 依赖：2.2。

- [x] 2.4 初始化中删除/关闭的竞态守卫
  - 前置：2.2。
  - 要做：close/delete 先 cancel+await init_task；慢路每个 await 后检查
    closed/存在性，已删不写事件；60s 总超时（wait_for）转 failed。
  - 通过标准（失败测试）：`cd webchat && pytest
    tests/test_runtime.py::test_delete_during_init_no_stray_events
    tests/test_runtime.py::test_initialize_timeout_fails` 先红后绿（删除后事件
    文件不含 session_ready/failed；超时转 failed 且资源释放）。
  - 依赖：2.2。

- [x] 2.5 写路径守卫 + 列表 status
  - 前置：2.1；send_message/set_model/upload 无状态校验；列表无 status。
  - 要做：非 ready 时 send_message/set_model/upload 返回 409「会话初始化中，
    请稍候」；GET /api/sessions 增 status/status_error。
  - 通过标准（失败测试）：`cd webchat && pytest
    tests/test_sessions_api.py::test_write_paths_rejected_while_creating
    tests/test_sessions_api.py::test_list_sessions_includes_status` 先红后绿。
  - 依赖：2.1。

- [x] 2.6 空闲回收跳过 creating
  - 前置：2.1；sweep_idle 仅跳过 closed/turn_running。
  - 要做：sweep_idle 跳过 status=="creating"。
  - 通过标准（失败测试）：`cd webchat && pytest
    tests/test_runtime.py::test_sweep_skips_creating_session` 先红后绿。
  - 依赖：2.1。

## 3. 截图通道双落盘（D3）

- [x] 3.1 原图落盘 + OCR 成功双文件
  - 前置：artifacts.upload screenshot 通道原图丢弃、仅写 .ocr.txt。
  - 要做：先 unique_path 落原图到 xlpa-input/（原扩展名），再读字节 OCR 成功写
    `<stem>.ocr.txt`；响应含原图 path/name 与 ocr_path/text/confidence。
  - 通过标准（失败测试）：`cd webchat && pytest
    tests/test_artifacts_upload.py::test_screenshot_saves_original_and_ocr` 先红后绿
    （两文件存在、响应含两路径、原图字节与上传一致）。
  - 依赖：无。

- [x] 3.2 OCR 失败/依赖缺失降级为仅原图
  - 前置：3.1；现状 OcrFailed→422、OcrUnavailable→503。
  - 要做：两类失败改为 200 + 原图保留 + ocr_error 告警，不生成 OCR 文件；响应
    仍显式、MUST NOT 伪造文本。
  - 通过标准（失败测试）：`cd webchat && pytest
    tests/test_artifacts_upload.py::test_screenshot_ocr_failure_degrades
    tests/test_artifacts_upload.py::test_screenshot_ocr_unavailable_degrades` 先红后绿
    （改写原 422/503 断言：原图存在、无 ocr.txt、ocr_error 非空）。
  - 依赖：3.1。

## 4. 前端初始化反馈 + price_factor（D5/D4）

- [x] 4.1 session_ready/failed 事件处理 + 初始化禁用徽标
  - 前置：app.js applyEvent 无新事件分支；创建表单同步等待返回。
  - 要做：applyEvent 增 session_ready（解锁+loadModels+notify）与
    session_failed（横幅+刷新列表）；openSession 按列表 meta.status 设初始态；
    初始化中禁用 textarea/发送/附件/模型下拉 + sticky 提示；setTurnActive 尊重
    initLock。
  - 通过标准（失败测试）：`cd webchat && pytest
    tests/test_static_frontend.py::test_session_ready_unlocks_composer
    tests/test_static_frontend.py::test_session_failed_shows_banner
    tests/test_static_frontend.py::test_creating_state_locks_composer` 先红后绿
    （事件分支与禁用标记）。
  - 依赖：2.1–2.5（事件与 status 字段已交付）。

- [x] 4.2 自带 PAT 失败回弹弹窗
  - 前置：4.1；现状创建失败仅在会话横幅展示。
  - 要做：记录最近创建 {session_id, account_source, pat, remember}；session_failed
    命中且 byo 时重开对话框、回填原因与输入（PAT 掩码保持）；列表 failed 态仅留删除。
  - 通过标准（失败测试）：`cd webchat && pytest
    tests/test_static_frontend.py::test_failed_byo_reopens_dialog
    tests/test_static_frontend.py::test_failed_session_row_delete_only` 先红后绿。
  - 依赖：4.1。

- [x] 4.3 模型成本标记 price_factor 优先
  - 前置：loadModels 以 is_free 渲染「免费」。
  - 要做：改为 price_factor != null ? "×N" : (is_free ? "免费" : "")。
  - 通过标准（失败测试）：`cd webchat && pytest
    tests/test_static_frontend.py::test_model_cost_price_factor_first` 先红后绿。
  - 依赖：无。

## 5. 文档、回归与真机验收

- [x] 5.1 文档补记
  - 前置：1–4 完成。
  - 要做：webchat/README.md 更新（异步创建语义、status 字段、新事件、截图双落盘、
    成本口径）；docs/architecture 对应设计文档补变更记录（不新开 ADR）。
  - 通过标准：文档与代码行为一致，无过时的"同步创建/仅 OCR 文本"描述。
  - 依赖：1–4。

- [x] 5.2 全量回归 + 探针复测 + 双轴评审
  - 前置：1–4 完成。
  - 要做：cd webchat && pytest 全绿（存量断言适配不降低覆盖）；重跑
    _probe_session_timing.py 验证快路 <2s；code-review Standards/Spec 双轴。
  - 通过标准（可执行判据）：webchat pytest 全绿；主基线无新增失败；探针输出
    create < 2000ms；评审无未处置发现。
  - 依赖：5.1。

- [x] 5.3 真机人工验收 + 模型读图实测
  - 结果：用户确认 iPhone 实机验收通过（顶栏完整、异步创建反馈、双落盘、
    成本口径等清单逐项实测 OK）。
  - 前置：5.2。
  - 要做：用户 iPhone 清单——登录后顶栏完整、键盘收起无残留；创建即进会话+初始化
    徽标+就绪解锁；传 jpg 后工作区原图与 .ocr.txt 双落盘、引用文案正确；下拉
    Qwen3.8-Flash 显示 ×0.1；并开真实会话实测 Agent Read 直读原图（不支持则引用
    文案降为 OCR 优先——仅改文案顺序，不改 spec）。
  - 通过标准：清单逐项留证（截图/会话记录）；读图实测结论记录在案。
  - 依赖：5.2。
