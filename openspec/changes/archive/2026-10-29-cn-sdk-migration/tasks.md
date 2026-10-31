## 1. 依赖切换

- [x] 1.1 `webchat/requirements.txt`：`qoder-agent-sdk==1.0.16` → `qodercn-agent-sdk==1.0.17`；验证：`webchat\.venv\Scripts\python -m pip install -r requirements.txt` 成功，`pip show qodercn-agent-sdk` 返回 1.0.17
- [x] 1.2 （可选，D5）卸载开发 `.venv` 全球版 `qoder-agent-sdk` 防误用；验证：`pip list | Select-String qoder` 仅剩 `qodercn-agent-sdk`——若决定保留并存（回滚零成本），在证据中记录该决定即可。**决定：保留共存**（两包并存 qoder 1.0.16 + qodercn 1.0.17，回滚零安装成本；生产按 requirements 仅装 CN；grep 已证无代码引用全球版），见 evidence-index §5

## 2. 生产代码切换（adapter 业务逻辑零改动，仅 import/字符串/docstring）

- [x] 2.1 `webchat/webchat/sdk_runtime/adapter.py`：`import qoder_agent_sdk as q` → `import qodercn_agent_sdk as q`；模块 docstring 的"qoder_agent_sdk 的唯一 import 点"与"不得出现 qoder_agent_sdk"、`pat_env` 参数文档的 `QODER_PERSONAL_ACCESS_TOKEN` 一并改 CN 名；验证：`python -c "import webchat.sdk_runtime.adapter"` 无错，且 grep adapter.py 无 `qoder_agent_sdk`/`QODER_PERSONAL`
- [x] 2.2 `webchat/webchat/sdk_runtime/__init__.py`：docstring"qoder_agent_sdk 的唯一 import 边界" → CN 名；验证：grep `__init__.py` 无 `qoder_agent_sdk`
- [x] 2.3 `webchat/webchat/api.py`：`os.environ.get("QODER_PERSONAL_ACCESS_TOKEN", "")` → `QODERCN_PERSONAL_ACCESS_TOKEN`（D2，边界外硬编码 CN 名）；验证：grep api.py 仅含 `QODERCN_PERSONAL_ACCESS_TOKEN`、无 `QODER_PERSONAL`

## 3. 测试切换

- [x] 3.1 `webchat/tests/test_sdk_runtime.py`：`import qoder_agent_sdk as q` → CN；`test_sdk_types_not_leaked` 的 banned `qoder_agent_sdk` → `qodercn_agent_sdk`（保留 `AssistantMessage`/`StreamEvent`，D4）；验证：该测试 PASS（断言 events.py 不含 CN 模块名/类型名）
- [x] 3.2 `webchat/tests/test_gate_hook.py`：`import qoder_agent_sdk as q` → CN；验证：门禁用例全 PASS（isinstance 归一化对齐 CN 类）

## 4. 验证

- [x] 4.1 webchat pytest 全绿；验证：`cd webchat; .venv\Scripts\python -m pytest -q` exit=0（防泄漏、门禁、事件归一化、会话/租约全过）
- [x] 4.2 原生 CN import 真实会话冒烟（去掉 C4 的 `sys.modules` alias，直接 `import qodercn_agent_sdk`，D7）：会话 initialize 成功、xlpa MCP `connected`、写入门禁实时拦截 PASS（`hook_fired`/`denied`/`gate_blocked`/审计落盘）；验证：冒烟输出 PASS（`native_sdk_module=qodercn_agent_sdk`、`alias_present=false`、Part0 initialized=true “就绪”、Part1 hook_fired=true / denied_add_brand=true / gate_blocked 入流 / audit=1 / dsml_leaked=false），证据落 `validation/cn-sdk-migration/`
- [x] 4.3 主 pytest 基线零影响 + `mcp_server/` 零改动；验证：主基线全绿（729 tests, 1 skipped, exit=0）。**验证方法修正**：`webchat/` 整目录未被 git 跟踪（`?? webchat/`），本变更编辑文件无一在 `mcp_server/` 下；`git diff -- mcp_server/` 的既存改动（server.py 等）属本变更**之前**的未提交工作，与本变更无关——故“本变更对 mcp_server 零改动”按意图成立（原“git diff 为空”判据在脏工作树下不适用）
- [x] 4.4 防残留自证：grep webchat（排除 `.venv`）无 `import qoder_agent_sdk` 与 `QODER_PERSONAL_ACCESS_TOKEN`（banned 历史 token 与注释除外）；验证：grep 输出为空或仅余允许项

## 5. 部署交接（BREAKING 部署契约，见 design Migration Plan）

- [x] 5.1 记录运维交接清单于变更证据或部署文档：① PAT 注入 `QODERCN_PERSONAL_ACCESS_TOKEN`（替换原 `QODER_...`）；② webchat 会话接入 MCP 用注册表 ide/user 级有效 token（`.env` admin token 实测 401）；③ CN SDK 自带 `qoderclicn`，无需 PATH 备 `qodercli`；④ 回滚路径（git revert + requirements 回退 + PAT 名改回）；验证：交接清单四项齐备且可执行——已落 `validation/cn-sdk-migration/evidence-index.md` §6
