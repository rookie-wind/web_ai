## Context

动机见 proposal.md - Why。此处只补充塑造方案的现状与约束：

- **品牌可移植性已证**：C4 验证期用 `sys.modules["qoder_agent_sdk"] = qodercn_agent_sdk`
  alias 跑通 V7 Part 1（真实 CN 会话 + 运行中 MCP Server，写入门禁实时拦截
  PASS）。adapter 全部 SDK 符号经 `q.` 前缀引用，切 import 即整体解析到 CN。
- **架构边界约束**：SDK 类型只允许出现在 `webchat/webchat/sdk_runtime/`
  单层（adapter 是唯一 import 点）；`api.py` 在边界外，**不能** import SDK，
  故其读取 PAT 的环境变量名是硬编码字符串。
- **PAT 注入范式（V10 已验）**：PAT 仅经环境变量注入、绝不出现在子进程命令行。
  adapter 用 `env[q.DEFAULT_ACCESS_TOKEN_ENV_VAR] = pat_env` 给 CLI 子进程注入，
  `auth=q.access_token_from_env()` 仅**声明** env_var 名（不在调用时读进程环境，
  实际读取在子进程）。CN SDK 的 `DEFAULT_ACCESS_TOKEN_ENV_VAR` 实测 =
  `QODERCN_PERSONAL_ACCESS_TOKEN`，故子进程侧自动对齐。
- **依赖现状**：`webchat/requirements.txt` pin `qoder-agent-sdk==1.0.16`；开发
  `.venv` 当前两包并存（`qoder-agent-sdk 1.0.16` + `qodercn-agent-sdk 1.0.17`，
  模块名不同不冲突）。无 pyproject.toml。
- **MCP 接入实测**：运行中 MCP Server（8765）拒绝 `.env` 的 admin
  `MCP_AUTH_TOKEN`（401），只接受 `.token_registry.json` 中 ide/user 级有效
  token（200）。门禁是客户端 PreToolUse Hook，user 级足以验证与运行。

## Goals / Non-Goals

**Goals:**

- 生产 webchat 由国内版 SDK 构建驱动，消除 alias 权宜与品牌不匹配风险。
- 切换面最小化：仅改 import、PAT 环境变量名、防泄漏 banned、依赖 pin、
  docstring 措辞；adapter 业务逻辑零改动。
- 迁移后可验证：webchat pytest 全绿 + 原生 CN import 真实会话冒烟 PASS。
- 部署契约明确：运维 PAT 注入名、MCP 接入 token 来源、回滚路径。

**Non-Goals:**

- 双品牌兼容 / 运行时品牌切换（CN-only；`SDK_BRAND` 是构建期常量，运行时
  不可切，引入抽象层属 YAGNI）。
- `mcp_server/` 任何改动（零）。
- 前端确认卡片（C7）、路径/命令白名单（C6）。
- `docs/architecture/` 历史 V10 记述改写（存档说明，非行为契约）。

## Decisions

- **D1 CN-only，不做双品牌/alias 回退**：用户定调"后续都是国内版"。alias 仅
  C4 验证期权宜，生产不保留。*备选*：保留全球版 + 运行时切换——否决，
  `SDK_BRAND` 构建期常量不可运行时切，双 import/双依赖招致漂移与测试矩阵翻倍。
- **D2 `api.py` PAT 名改硬编码 CN 字符串**：`api.py` 在 SDK 边界外不能 import
  SDK 常量，单点引用下硬编码 `QODERCN_PERSONAL_ACCESS_TOKEN` 是最小正确改动。
  *备选*：① 在 api.py import SDK 常量——违反边界；② 新建共享配置常量模块——
  为单处引用引入新模块属过度设计。
- **D3 adapter 仅切 import 行**：所有 `q.XXX`（`QoderAgentOptions`/`HookMatcher`/
  `access_token_from_env`/`DEFAULT_ACCESS_TOKEN_ENV_VAR`/`qodercli_auth`/
  `AssistantMessage`/`StreamEvent` 等）经前缀自动解析到 CN，业务逻辑零改动。
  子进程 env 注入与 auth 声明因 `DEFAULT_ACCESS_TOKEN_ENV_VAR` 自动对齐。
- **D4 防泄漏 banned 列表换 CN 名**：`"qodercn_agent_sdk"` **不含**子串
  `"qoder_agent_sdk"`，旧 token 抓不到 CN 泄漏，必须替换；`AssistantMessage`/
  `StreamEvent` 类型名 CN 版相同，保留。
- **D5 依赖替换而非并存**：`requirements.txt` 用 CN pin 替换全球版 pin（版本
  `==1.0.17`，与已验一致）。`.venv` 全球版迁移后无引用，**可选**卸载（并存
  无害，卸载防误用，低优先）。
- **D6 MCP 接入 token 用注册表 ide/user 级**：部署配置项（非代码）。`.env`
  admin token 对运行中 MCP Server 401；门禁客户端性质，user 级足够。
- **D7 验证用原生 CN import 复跑冒烟**：沿用 V7 探针思路，但去掉 alias、直接
  `import qodercn_agent_sdk`，确认 initialize 成功、xlpa MCP `connected`、
  写入门禁实时拦截仍 PASS；webchat pytest 全绿；主基线零影响。

## Risks / Trade-offs

- [运维未同步改 PAT 环境变量名] → 鉴权失败、initialize 超时 → 部署清单明示
  `QODERCN_PERSONAL_ACCESS_TOKEN`，部署后立即冒烟验 initialize，失败即回滚。
- [banned 列表漏改致防泄漏断言对 CN 名失效] → tasks 含断言更新条目，且断言
  自证（评审可见 banned 是否含 CN 名）。
- [两包并存期误 import 全球版] → import 全量切换 + grep 自证 webchat 无残留
  `qoder_agent_sdk` 引用（banned 历史 token 除外）。
- [CN SDK 版本漂移] → requirements pin `==1.0.17`（与已验版本锁定）。
- **Trade-off**：CN-only 放弃全球版兼容 → 符合用户定调，简化依赖与测试矩阵；
  未来若需双品牌，再开变更引入品牌抽象层（当前 YAGNI）。

## Migration Plan

1. **部署前准备（运维）**：备好国内版 PAT，注入到 `QODERCN_PERSONAL_ACCESS_TOKEN`
   （替换原 `QODER_PERSONAL_ACCESS_TOKEN`）；确认 webchat 会话接入 MCP 用注册表
   ide/user 级有效 token。
2. **代码切换**：`requirements.txt` → CN pin；`adapter.py`/`__init__.py`/`api.py`/
   `test_sdk_runtime.py`/`test_gate_hook.py` 的 import、PAT 名、banned、docstring
   切换；`pip install -r requirements.txt`（装 CN，可选卸载全球版）。
3. **验证**：webchat pytest 全绿；原生 CN import 真实会话冒烟（initialize 成功 /
   xlpa `connected` / 写入门禁实时拦截 PASS）；主 pytest 基线零影响、git diff
   证 `mcp_server/` 零改动。
4. **回滚策略**：若 CN 会话异常——`git revert` 代码改动 + `requirements.txt`
   回退全球版 pin + 运维改回 `QODER_PERSONAL_ACCESS_TOKEN`。全球版 SDK 仍在
   `.venv`（未卸载时），回滚零安装成本。
