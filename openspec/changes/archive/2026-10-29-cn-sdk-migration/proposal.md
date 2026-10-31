## Why

webchat 会话运行时当前依赖**全球版构建** `qoder-agent-sdk`（`SDK_BRAND=global`、
PAT 环境变量 `QODER_PERSONAL_ACCESS_TOKEN`、CLI 找 PATH 的 `qodercli`），而实际
部署使用**国内版 PAT**。品牌不匹配会使真实会话 `Control request timeout:
initialize`（CLI 握手不完成）——`SDK_BRAND` 是构建期常量，不能用环境变量切换。
用户已定调 CN-only（"改成国内版，后续都是"）。C4 验证期已用 `sys.modules` alias
证明 adapter 品牌可移植、国内版 SDK 端到端可用（V7 Part 1 实时写入拦截 PASS）。
本变更把生产 webchat 正式切到国内版构建，消除 alias 权宜与品牌不匹配风险。

## What Changes

- **依赖替换（CN-only，不并存）**：`webchat/requirements.txt` 的
  `qoder-agent-sdk==1.0.16` → `qodercn-agent-sdk==1.0.17`（导入名
  `qodercn_agent_sdk`，wheel 自带 `_bundled/qoderclicn.exe`，不依赖 PATH 的
  `qodercli`）。
- **adapter 唯一 import 点切换**：`sdk_runtime/adapter.py` 的
  `import qoder_agent_sdk as q` → `import qodercn_agent_sdk as q`。其余全部
  `q.XXX` 符号（`QoderAgentOptions`/`HookMatcher`/`access_token_from_env`/
  `DEFAULT_ACCESS_TOKEN_ENV_VAR`/`qodercli_auth`/`AssistantMessage`/`StreamEvent`
  等）经 `q.` 前缀自动解析到 CN SDK，**零改动**（品牌可移植，C4 已证）。
- **BREAKING（部署契约）PAT 环境变量名切换**：`webchat/api.py` 读取 PAT 的
  `os.environ.get("QODER_PERSONAL_ACCESS_TOKEN", "")` →
  `QODERCN_PERSONAL_ACCESS_TOKEN`。运维须改用 CN 名注入 PAT，否则鉴权失败、
  会话 initialize 超时。adapter 侧 `env[q.DEFAULT_ACCESS_TOKEN_ENV_VAR]` 与
  `q.access_token_from_env()` 在 CN SDK 下自动对齐到 `QODERCN_PERSONAL_ACCESS_TOKEN`
  （`DEFAULT_ACCESS_TOKEN_ENV_VAR` 实测 = 该名），无需改。
- **防泄漏断言更新**：`tests/test_sdk_runtime.py` 的
  `test_sdk_types_not_leaked` banned 列表 `qoder_agent_sdk` → `qodercn_agent_sdk`
  （`AssistantMessage`/`StreamEvent` 类型名 CN 版相同，保留）。
- **测试 import 同步**：`tests/test_sdk_runtime.py`、`tests/test_gate_hook.py`
  的 `import qoder_agent_sdk as q` → CN（否则 isinstance 归一化跨 SDK 类不匹配）。
- **docstring 措辞更新**：`adapter.py` 与 `sdk_runtime/__init__.py` 的
  "qoder_agent_sdk 的唯一 import 点/边界" → CN 名；`adapter.py` 中 `pat_env`
  参数文档的 `QODER_PERSONAL_ACCESS_TOKEN` → `QODERCN_PERSONAL_ACCESS_TOKEN`。
- **部署配置说明（不改代码）**：webchat 会话接入 MCP 用注册表 ide/user 级
  token（`.env` 的 admin `MCP_AUTH_TOKEN` 对运行中 MCP Server 实测 401）。
- 明确**不在本变更内**：双品牌兼容/运行时切换（CN-only，不做 alias 回退）、
  `mcp_server/` 任何改动（零）、前端确认卡片（C7）、`docs/architecture/` 历史
  V10 记述（属存档说明，非行为契约）。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `agent-runtime-session`: 新增一条 Requirement，明确 Web 会话运行时 MUST 由
  **国内版 Qoder Agent SDK 构建**驱动（导入名 `qodercn_agent_sdk`、PAT 经
  `QODERCN_PERSONAL_ACCESS_TOKEN` 注入、自带 `qoderclicn` CLI、SDK 类型名仍
  限于 adapter 边界不外泄）。其余既有 Requirement（1:1:1 绑定、事件契约 v1、
  断线重放、租约、配额、工作区、凭据解耦）行为不变。

## Impact

- **代码（仅 webchat）**：
  - `webchat/webchat/sdk_runtime/adapter.py`：import 行 + 模块 docstring +
    `pat_env` 参数文档；
  - `webchat/webchat/sdk_runtime/__init__.py`：模块 docstring；
  - `webchat/webchat/api.py`：PAT 环境变量名（`QODER_` → `QODERCN_`）；
  - `webchat/tests/test_sdk_runtime.py`：import + banned 列表；
  - `webchat/tests/test_gate_hook.py`：import。
- **依赖**：`webchat/requirements.txt` 替换 SDK 包（全球版 → 国内版）。开发
  `.venv` 当前两包并存，迁移后全球版不再被任何代码引用（可选卸载，避免误用）。
- **部署（BREAKING）**：运维须把 PAT 注入到 `QODERCN_PERSONAL_ACCESS_TOKEN`
  （原 `QODER_PERSONAL_ACCESS_TOKEN`）；CN SDK 自带 `qoderclicn.exe`，无需在
  PATH 准备 `qodercli`；MCP 接入 token 用注册表 ide/user 级有效 token。
- **品牌可移植性（零改动，已核实）**：adapter 所有 SDK 符号经 `q.` 前缀引用，
  切 import 即整体解析到 CN SDK；`DEFAULT_ACCESS_TOKEN_ENV_VAR` 在 CN SDK =
  `QODERCN_PERSONAL_ACCESS_TOKEN`，子进程 env 注入与 `access_token_from_env()`
  声明自动对齐（该函数仅声明 env_var 名、不在调用时读进程环境）。
- **测试**：webchat pytest 须全绿（防泄漏、门禁、事件归一化、会话/租约）；主
  pytest 基线零影响（`mcp_server/` 不动）；迁移后建议用**原生 CN import**（非
  alias）复跑一次真实会话冒烟，确认 initialize 成功、xlpa MCP `connected`、
  写入门禁实时拦截仍 PASS。
- **风险**：PAT 环境变量名若运维未同步改 → 鉴权失败、initialize 超时（部署
  清单明示 + 冒烟兜底）；banned 列表若漏改 → 防泄漏断言对 CN 名失效（tasks
  覆盖 + 断言自证）；两包并存期若误 import 全球版 → 由 banned 断言与 import
  切换共同消除。
- **引用规范**：本变更全部工件以**符号锚**（`DEFAULT_ACCESS_TOKEN_ENV_VAR`、
  `access_token_from_env`、`QoderAgentOptions`、`qodercn_agent_sdk`、
  `QODERCN_PERSONAL_ACCESS_TOKEN`）表述，不用行号（两仓库副本行号已分叉）。
