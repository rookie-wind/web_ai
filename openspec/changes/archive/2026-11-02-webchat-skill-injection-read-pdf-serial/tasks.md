## 1. 技能加载（B+C）

- [x] 1.1 新增 `webchat/skills.py`：解析 canonical `agent_assets/skills/*/SKILL.md`
  frontmatter（name/description/when_to_use），提供索引渲染与 `/技能名` 前缀
  匹配；目录缺失/单文件损坏时安全降级。
  验证：`test_skills.py::test_catalog_index_and_prefix_match`、`test_empty_or_missing_root_is_safe`。
- [x] 1.2 配置：`Settings.skills_root` + `WEBCHAT_SKILLS_ROOT`（默认仓库
  `agent_assets/skills`）；`create_app` 启动时加载目录并注入 SessionRuntime。
- [x] 1.3 adapter：技能索引追加进系统提示；`_prepare_prompt` 在 `/技能名` 消息
  前注入 SKILL.md 全文；不匹配前缀按普通文本。
  验证：`test_skills.py::test_adapter_index_in_system_prompt_and_prefix_injects`。
- [x] 1.4 运行时装配：session 句柄收到索引/全文，Read 白名单含技能目录。
  验证：`test_skills.py::test_runtime_wires_catalog_into_handle_and_read_gate`。

## 2. 内置 Read 放开

- [x] 2.1 `grants.py` 新增 `READ_TOOL_NAMES` 与 `WriteGate(read_roots=...)`；
  `check_read` 按 `resolve()` 校验，越界/缺参/无根目录一律拒绝，拒绝事件带
  `guard=read_path`、`confirmable=false`。
  验证：`test_grants.py::test_read_only_within_workspace_and_skills_root`、
  `test_read_denied_without_roots_and_emits_guard_event`。
- [x] 2.2 adapter 工具面加入 `Read`，`can_use_tool` 复用 `check_read`。
  验证：`test_gate_hook.py::test_builtin_tool_surface_includes_read`、
  `test_permission_callback_answers_without_prompt`。

## 3. PDF → 文本

- [x] 3.1 `requirements.txt` 增加 `pypdf`，安装到 webchat venv（6.21.4）。
- [x] 3.2 `document` 通道落盘 PDF 后提取文本写 `xlpa-input/<stem>.pdf.txt`，
  响应含 `text_path`/`text_chars`；失败/空文本写显式 `warning`，保留原文件。
  前端上传提示展示 warning 或已提取路径。
  验证：`test_artifacts_upload.py::test_pdf_document_extracts_text_sidecar`、
  `test_invalid_pdf_returns_explicit_warning_without_blocking`。

## 4. 同会话轮次串行化

- [x] 4.1 `send_message` 在 `turn_running` 时 409「上一轮仍在执行，请稍候」。
  验证：`test_sessions_api.py::test_message_rejected_while_turn_running`。
- [x] 4.2 `/confirm` 响应带 `turn_running`；前端执行中不自动续跑，提示
  「助手将在当前轮重试」。
  验证：`test_sessions_api.py::test_confirm_reports_turn_running`。

## 5. 工具契约（按技能、不硬编码）

- [x] 5.1 canonical `modbus-conversion/SKILL.md` 增加「平台工具入参契约」：
  先读 `list_mcp_tools` schema、先查 `get_script_list`/`get_json_detail`；记录
  `gen_script` 实测必填 `query`/`cusstr`/`dataItemId`（仅参考，不是固定签名）。
- [x] 5.2 canonical `xlpa/SKILL.md` 全局约束新增「工具契约以 schema 为准」。
- [x] 5.3 不修改 `mcp_server` 工具签名、不新增硬校验（避免锁死其他协议）。

## 6. 回归与归档

- [x] 6.1 webchat 全量：**167 passed**。
- [x] 6.2 主项目基线：**771 tests / 0 failures / 1 skipped**。
- [x] 6.3 `openspec validate --all --strict` 通过后归档本变更。
