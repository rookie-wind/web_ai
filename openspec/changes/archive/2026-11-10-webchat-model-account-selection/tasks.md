<!-- 拆分方案须先经人工确认再实施（config.yaml 铁律）。每个 task 一个纵向切片：
     先写命中"通过标准"的失败测试并确认红，再写最小实现使其绿；未红转绿禁止勾完成。
     测试命令统一从 webchat 目录跑：cd webchat && pytest tests/<file>::<test> -->

## 1. 会话级账号绑定与 PAT 校验（内存）

- [x] 1.1 自带 PAT 建会话并绑定账号（API→runtime→adapter pat_env）
  - 前置：design D2/D3；fake_sdk_client 需支持 get_available_models（本切片内扩展）。
  - 要做：create_session 增账号来源与 PAT 入参；runtime 按会话选 PAT 喂 pat_env；仅经 env 注入。
  - 通过标准（失败测试）：`cd webchat && pytest tests/test_sessions_api.py::test_create_session_byo_pat_binds_account` 先红后绿（断言句柄 pat_env 收到该 PAT、会话绑定自带账号）。
  - 依赖：无。

- [x] 1.2 无效/过期/品牌不一致 PAT 拒绝建会话
  - 前置：1.1 的校验路径（get_available_models 失败即拒绝）。
  - 要做：校验失败返回可辨识原因，不产生可用会话；覆盖品牌不一致握手超时。
  - 通过标准（失败测试）：`cd webchat && pytest tests/test_sessions_api.py::test_create_session_rejects_invalid_pat` 先红后绿。
  - 依赖：1.1。

- [x] 1.3 默认账号向后兼容回落
  - 前置：design D2；现状全局 _pat + 配置默认模型。
  - 要做：create_session 不带账号选择时回落默认账号与配置默认模型，行为同今天。
  - 通过标准（失败测试）：`cd webchat && pytest tests/test_runtime.py::test_create_session_default_account_uses_global_pat` 先红后绿。
  - 依赖：1.1。

- [x] 1.4 默认账号不可用提示需自带
  - 前置：design D3；无 env PAT 且无本机登录态分支。
  - 要做：默认账号不可用时拒绝选默认并提示需自带 PAT。
  - 通过标准（失败测试）：`cd webchat && pytest tests/test_sessions_api.py::test_default_account_unavailable_prompts_byo` 先红后绿。
  - 依赖：1.3。

- [x] 1.5 账号会话级固定不热切
  - 前置：design D1；_build_options 构建期定型。
  - 要做：会话绑定后 pat_env/auth 不随轮次变化；无账号热切入口。
  - 通过标准（失败测试）：`cd webchat && pytest tests/test_runtime.py::test_account_bound_at_build_not_switched` 先红后绿。
  - 依赖：1.1。

## 2. 账号级模型清单与消息级选择

- [x] 2.1 账号清单只列启用模型并经 API 暴露
  - 前置：design D4；get_available_models 返回 ModelInfo。
  - 要做：过滤 isEnabled，携带 displayName/isFree/priceFactor，按会话缓存并经 API 暴露给前端。
  - 通过标准（失败测试）：`cd webchat && pytest tests/test_sessions_api.py::test_session_models_list_enabled_only` 先红后绿（含未启用项被过滤、成本字段齐全）。
  - 依赖：1.1。

- [x] 2.2 默认预选模型规则
  - 前置：design D4。
  - 要做：默认账号用配置默认；自带账号用清单首个启用模型（配置默认若在清单则优先）。
  - 通过标准（失败测试）：`cd webchat && pytest tests/test_runtime.py::test_default_model_preselect_rule` 先红后绿。
  - 依赖：2.1。

- [x] 2.3 消息级 set_model 切换不重建客户端
  - 前置：design D5；client.set_model 流式可用、_gen 代际。
  - 要做：WebSession 存 current_model；轮次边界调 set_model；不动 pat_env/auth/客户端实例。
  - 通过标准（失败测试）：`cd webchat && pytest tests/test_sdk_runtime.py::test_set_model_switches_without_rebuild` 先红后绿（客户端实例与 session_id 不变、pat_env 不变）。
  - 依赖：2.1。

- [x] 2.4 越清单模型拒绝
  - 前置：design D5；所选模型须属当前账号清单。
  - 要做：切换到清单外模型被拒绝并提示。
  - 通过标准（失败测试）：`cd webchat && pytest tests/test_runtime.py::test_switch_model_outside_list_rejected` 先红后绿。
  - 依赖：2.1。

- [x] 2.5 执行中轮次拒绝切换模型
  - 前置：既有"同一会话轮次串行"约束。
  - 要做：turn_running 期间拒绝模型切换，仅在轮次边界生效。
  - 通过标准（失败测试）：`cd webchat && pytest tests/test_runtime.py::test_switch_model_during_turn_rejected` 先红后绿。
  - 依赖：2.3。

## 3. 前端 UI

- [x] 3.1 新建会话账号选择对话框
  - 前置：design D7；app.js 现无建会话弹窗。
  - 要做：账号单选（默认/自带）+ PAT 掩码框 + 记住勾选（默认不勾）；建会话 POST 携带账号选择。
  - 通过标准（失败测试）：`cd webchat && pytest tests/test_static_frontend.py::test_new_session_dialog_account_choice` 先红后绿。
  - 依赖：1.1、2.1。

- [x] 3.2 输入区模型选择下拉
  - 前置：design D7；compose 区已有 upload-channel 可参照。
  - 要做：下拉取自会话账号清单含成本标记，消息级切换，不改路由/会话模式。
  - 通过标准（失败测试）：`cd webchat && pytest tests/test_static_frontend.py::test_compose_model_dropdown` 先红后绿。
  - 依赖：2.1、2.3。

- [x] 3.3 校验失败提示且凭据不进 URL/不回显
  - 前置：specs web-chat-ui；1.2 的后端原因。
  - 要做：展示后端可辨识原因，PAT 掩码、不进 URL、不回显明文。
  - 通过标准（失败测试）：`cd webchat && pytest tests/test_static_frontend.py::test_byo_pat_error_no_plaintext` 先红后绿。
  - 依赖：3.1、1.2。

## 4. 记住明文存储与清除

- [x] 4.1 Account.qoder_pat 字段与记住持久化
  - 前置：design D6 / ADR-0004；账号库已 gitignore、明文 phone/code。
  - 要做：Account 增可选 qoder_pat；勾记住明文落盘 per-user；默认不勾仅内存；旧文件无字段正常加载。
  - 通过标准（失败测试）：`cd webchat && pytest tests/test_account_auth.py::test_remember_pat_persists_plaintext` 先红后绿。
  - 依赖：1.1。

- [x] 4.2 记住的 PAT 预填与失效重校验
  - 前置：4.1、1.2。
  - 要做：下次建会话预填（掩码）；记住 PAT 失效则校验失败提示重新输入。
  - 通过标准（失败测试）：`cd webchat && pytest tests/test_sessions_api.py::test_remembered_pat_prefill_and_revalidate` 先红后绿。
  - 依赖：4.1、1.2。

- [x] 4.3 清除已记住的 PAT
  - 前置：4.1。
  - 要做：清除入口删账号库 qoder_pat，下次需重新输入。
  - 通过标准（失败测试）：`cd webchat && pytest tests/test_account_auth.py::test_clear_remembered_pat` 先红后绿。
  - 依赖：4.1。

- [x] 4.4 PAT 不进日志/命令行护栏
  - 前置：design D6；既有 env 注入范式。
  - 要做：确保 PAT 仅经 env，日志与 subprocess 命令行不含明文。
  - 通过标准（失败测试）：`cd webchat && pytest tests/test_sdk_runtime.py::test_pat_never_in_log_or_cmdline` 先红后绿。
  - 依赖：1.1、4.1。

## 5. 集成验收与回归（跨任务验证）

- [x] 5.1 端到端真实演练取证
  - 前置：1–4 全绿。
  - 要做：登录→新建会话选账号/模型→发消息收事件流→消息级切模型→断线重连补齐，全程取证。
  - 通过标准（可执行判据）：e2e 演练脚本/记录 PASS（含切模型后 session_id 不变、凭据不变、事件流连续）。
  - 依赖：1–4。

- [x] 5.2 全量回归绿 + code-review 双轴 + IDE 回归
  - 前置：5.1。
  - 要做：跑回归并做双轴评审。
  - 通过标准（可执行判据）：`cd webchat && pytest` 全绿 + 主 `pytest` 基线全绿 + IDE 回归（/mcp 与接入页行为不变）；code-review Standards（.qoder/rules PEP8/257/484）与 Spec（忠实实现本 change Requirement/Scenario）双轴均过。
  - 依赖：5.1。