## Why

当前接入页对不同 AI 工具（Qoder / Trae / Cursor / VS Code / Claude / Windsurf / Cline / Kimi）只生成一段"复制粘贴用"的配置文本，且对 Qoder 明确写的是"打开设置 → MCP → 手动粘贴"。结果是：用户把接入文本交给 Agent 后，protocol-converter 并不会被真正写入该工具实际读取的配置文件（例如 Qoder 只读用户级 `~/.qoder/mcp.json`，而项目仅生成了 Trae 的 `.trae/mcp.json`），导致"尚未注册"、配置缺失、需要人工兜底。同时服务端存在与具体工具目录绑定的痕迹（资源包打包源、install.bat 写死 `.trae/mcp.json`），使"用哪个工具"渗透到服务端。接入流程需要做到：选定工具即由该工具内的 Agent 自动把配置写进它自己的真实文件、不缺文件、幂等可重跑，而服务端保持与任何工具解耦。

## What Changes

- 接入页安装文本从"给人手动粘贴"升级为**指示 Agent 直接把 `protocol-converter` 条目写入目标客户端实际读取的 MCP 配置文件**（不存在则创建、存在则合并、保留其它 server）——**零脚本**，不新增随包分发的注册程序。
- 文本必须写明该平台的真实配置文件路径与符合该客户端格式的条目，并**内嵌幂等/合并/备份约束**（写入前先读、非法 JSON 先备份、原子替换思路），供 Agent 遵循。
- 文本必须要求 Agent 写入后调用 `list_mcp_tools` 验证连通与鉴权，验证通过才声明接入完成；失败回退到"手动粘贴 JSON"兜底。
- **服务端与工具解耦**：服务端资源包保持从中性目录（`agent_assets/skills`）打包，服务端产物与逻辑 MUST NOT 写死或生成任何单一工具（Trae/Qoder 等）专属的目录或配置文件；工具侧路径只出现在面向客户端的安装说明文本中。
- 保留现有手动粘贴 JSON 能力与 `.trae/mcp.json`（供已用 Trae 的用户），但服务端不再默认生成工具专属配置。
- 不改变服务端鉴权模型与 Token 语义；接入 Token 仍仅作 `Authorization: Bearer` 连接用途。

## Capabilities

### New Capabilities
- `mcp-client-auto-registration`: 通过接入说明文本驱动目标客户端内 Agent 自动、幂等地把 protocol-converter 注册到其真实配置文件并完成验证的行为契约；同时约束服务端与具体工具解耦。

### Modified Capabilities
- `agent-assets-package-management`: 接入页安装说明必须引导 Agent 直接写入真实配置文件（零脚本），并保证服务端资源包不与具体 IDE 目录绑定。

## Impact

- `mcp_server/static/access.html`：`PLATFORMS` 增加各平台真实配置文件路径与格式；`generateText()` 安装步骤改为"指示 Agent 直接写入/合并配置文件 + 写入后验证 + 手动兜底"。
- `agent_assets/skills/xlpa/SKILL.md` 与 `manifest.json`、`package-manifest.json`：更新接入说明为文本驱动（**不新增**注册脚本，不将其列为必需文件）。
- `mcp_server/install.bat`：不再默认生成工具专属 `.trae/mcp.json`（改为可选/移除，避免服务端与 Trae 绑定），具体在 design 决策。
- `mcp_server/server.py`：打包源已迁 `agent_assets/skills`，确认无其它写死工具目录的路径。
- 文档：`mcp_server/README.md`、`mcp server部署.md` 增补"文本驱动自动注册 + 服务端解耦"说明。
- 兼容性：现有 `.trae/mcp.json`（Trae）与手动粘贴方式继续可用，非破坏性。
