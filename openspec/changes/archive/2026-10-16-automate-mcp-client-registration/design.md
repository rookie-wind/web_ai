## Context

现状：`mcp_server/static/access.html` 的 `PLATFORMS` 已按平台生成正确的 MCP 配置 JSON（rootKey、`type`/`transport`/`serverUrl` 差异、`url`+`headers`），但 `generateText()` 只把 JSON 作为"复制粘贴文本"输出，对 Qoder 甚至引导"设置界面手动粘贴"。服务端仅有 install.bat 写死生成 Trae 的 `.trae/mcp.json`。经实测：Qoder 实际读取用户级 `~/.qoder/mcp.json`，且该文件当前为空 `{"mcpServers":{}}`，因此 protocol-converter 在 Qoder 中"尚未注册"。动机见 proposal.md - Why；行为契约见两份 spec。

**方案取向（用户确认）：零脚本。** 不新增随包分发的注册程序；接入由"接入页生成的文本"驱动目标工具内的 Agent 直接写它自己的配置文件。服务端与具体工具解耦。

约束：
- 不改变服务端鉴权模型、Token 语义与 `/mcp` 端点。
- 资源包打包源已是中性目录 `agent_assets/skills`，ZIP 内 arcname 仍以 `skills/` 为顶层前缀。
- Agent 在**目标工具自身环境**里运行，能感知并写入本工具的配置文件——这是"零脚本"可行的前提。

## Goals / Non-Goals

**Goals:**
- 接入文本从"给人粘贴"升级为"指示 Agent 直接、幂等地写入真实配置文件并验证"。
- 服务端产物/逻辑不与任何单一工具目录绑定。
- 平台配置路径/格式集中在接入页一处可维护定义。

**Non-Goals:**
- 不实现任何注册脚本/可执行程序，也不做 IDE 进程自动检测。
- 不改动后端业务 Token 登录/权限流程。
- 不为未支持平台臆造配置路径。

## Decisions

### D1：文本驱动、零脚本（不新增注册程序）
接入正确性由"高质量安装文本 + Agent 遵循"保证，而非随包二进制。
- 理由：Agent 运行在目标工具内，天然知道并能读写该工具的配置文件；脚本方案会把工具耦合重新引入服务端分发物，与"解耦"目标冲突，且增加 manifest/打包/跨平台路径解析负担。
- 备选：随包 `register_mcp_client.py`——**否**（用户选择零脚本；且它本身即"服务端产物绑定工具"的一种形态）。

### D2：平台配置路径/格式表落在 access.html（单一事实源）
在 `PLATFORMS` 内为每平台补 `configPath`（真实文件）与 `configLevel`（user/project），与既有条目格式同处一表，`generateText()` 据此拼装。

| 平台 | 级别 | 配置文件 | rootKey | 条目格式 |
|------|------|----------|---------|----------|
| qoder | 用户级 | `~/.qoder/mcp.json` | `mcpServers` | `{url, headers}`（无 `type`）|
| trae | 项目级 | `.trae/mcp.json` | `mcpServers` | `{url, headers}` |
| cursor | 项目级 | `.cursor/mcp.json` | `mcpServers` | `{url, headers}` |
| vscode | 项目级 | `.vscode/mcp.json` | `servers` | `{type:"http", url, headers}` |
| claude | 用户级 | Claude Desktop 配置文件 | `mcpServers` | `{type:"streamableHttp", url, headers}` |
| windsurf | 用户级 | `~/.codeium/windsurf/mcp_config.json` | `mcpServers` | `{serverUrl, headers}` |
| cline | 用户级 | `cline_mcp_settings.json` | `mcpServers` | `{type:"streamableHttp", url, headers}` |
| kimi | 用户级 | `~/.kimi/mcp.json` | `mcpServers` | `{url, transport:"http", headers}` |

- rootKey/条目格式必须与 `generateText()` 现有 JSON 生成分支逐一对齐，避免"文本 JSON"和"路径表"两套定义漂移。

### D3：安装文本内嵌读-合并-写-验证指令
`generateText()` 的安装段产出给 Agent 的自然语言 + 代码片段指令，明确：
1. 目标文件绝对/相对路径（来自 D2 表）。
2. 若文件/父目录不存在 → 创建并写入仅含 `protocol-converter` 的合法 JSON。
3. 若存在 → 先读、仅新增/更新 `protocol-converter` 键、保留其它 server、幂等（重复执行结果一致）。
4. 若既有文件非合法 JSON → 先备份（`<file>.bak.<时间戳>`）再中止并提示，不覆盖。
5. 写入后调用 `list_mcp_tools` 验证；失败则回退手动粘贴（附完整 JSON + 路径）。
- 理由：把原脚本逻辑下沉为对 Agent 的显式约束指令，行为一致且零分发物。
- 备选：给一段可粘贴的 Python 内联片段让 Agent 执行——保留为"高级兜底"可选，主路径仍是声明式指令，避免又变成"脚本"。

### D4：Token 与主机约束
文本只含 MCP 接入 Token（连接用途，写入 `headers.Authorization`），不写后端业务 Token；提示 Token 敏感、勿公开回显。端点主机沿用既有 IPv4/`localhost` 约束，不生成 IPv6。

### D5：服务端与工具解耦
- 打包源固定为中性 `agent_assets/skills`（已完成），`server.py` 不再出现工具目录硬编码。
- install.bat 不再把"生成 `.trae/mcp.json`"作为唯一/默认接入手段：改为可选（仅当用户确在 Trae 且需要预置时），或直接移除该写入，使服务端部署不预设工具。保留向后兼容说明。
- 工具侧配置写入完全交给目标工具内 Agent 依 D3 文本执行。

### D6：access.html 文本改造（与 D3 对应）
`generateText()` 安装段改为上述"直接写入/合并 + 验证 + 手动兜底"；Qoder 等 `configLocation` 文案由"设置手动粘贴"改为标注真实文件路径。

## Risks / Trade-offs

- [Agent 未严格遵循幂等/合并指令，误覆盖其它 server] → 文本用强约束祈使句并给出"仅改 `protocol-converter` 键"的明确边界与示例；提供损坏备份步骤兜底。
- [各 IDE 配置 schema 随版本漂移] → 路径/格式集中在 D2 表，改动只在一处；未知平台不臆造、走人工确认。
- [用户环境路径差异（多用户/远程/非默认安装）] → 文本提示"若你的客户端配置不在默认位置，请替换为实际路径"，并保留手动兜底。
- [移除 install.bat 的 `.trae/mcp.json` 生成影响老流程] → 分阶段：先标注为可选、保留产物兼容，验证文本驱动可用后再考虑移除。

## Migration Plan

1. 改造 access.html：补 D2 路径表 + 重写 `generateText()` 安装段（文本驱动 + 兜底）。
2. 更新 `xlpa/SKILL.md` 接入说明为文本驱动；manifest 不新增注册脚本。
3. 调整 install.bat 的 `.trae/mcp.json` 生成为可选/移除，更新部署文档。
4. 灰度：先对 Qoder、Trae 端到端验证文本驱动接入，再推广其余平台。
5. 回滚：文本改动可回退到旧"手动粘贴"版；`.trae/mcp.json` 若被删可由手动兜底重建。

## Open Questions

- Claude Desktop / Cline 配置文件绝对路径随安装位置变化：文本以"默认路径 + 请确认实际路径"方式表达，不影响契约与任务拆分。
- install.bat 是"改为可选"还是"彻底移除" `.trae/mcp.json` 写入：待实现时按兼容性偏好定，二者都满足解耦要求。
