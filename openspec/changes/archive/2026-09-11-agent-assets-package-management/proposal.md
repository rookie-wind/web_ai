## Why

当前分发与更新流程以 `.trae/skills/` 中的 Skill 文档为中心，无法清晰管理随 Skill 一起演进的工具脚本、模板、校验器、参考资料和 manifest 等资源。随着 `pca/tools/mcp_client.py` 等配套文件出现，如果继续用“只更新 SKILL.md”的思路，会导致首次接入、后续更新和故障备用通道之间出现版本漂移。

## What Changes

- 将现有 Skills ZIP 分发升级为兼容的“Agent 资源包”概念，继续以 `.trae/skills/` 为主要打包根目录，同时允许每个 Skill 携带 `tools/`、`templates/`、`validators/`、`references/`、`manifest.json` 等资源。
- 为资源包引入 manifest 驱动的清单与校验机制，用于声明包版本、Skill 版本、必需文件、可选文件和更新后校验规则。
- 更新接入页生成文案与 `/pca` Skill 文档，将安装/更新流程描述为“Agent 资源包”安装与更新，而不是只更新 `SKILL.md`。
- 明确 `pca/tools/mcp_client.py` 随资源包分发，并作为 IDE 原生 MCP 调用失败时的备用通道；默认不在安装后自动运行脚本。
- 统一首次接入与后续更新流程：下载资源包、备份现有 `.trae/skills`、全量覆盖、读取 manifest、校验必需文件、提示重新加载 Skill。
- 保持现有 `/api/docs/export-skills-package` ZIP 下载接口兼容，不破坏现有用户接入流程。

## Capabilities

### New Capabilities
- `agent-assets-package-management`: 定义 Agent 资源包的分发、manifest 校验、配套资源更新和备用 MCP 客户端交付行为。

### Modified Capabilities
- 无。

## Impact

- 影响 `mcp_server/server.py` 的资源打包与可选 manifest 导出逻辑。
- 影响 `mcp_server/static/access.html` 的接入文本、安装说明、更新说明和校验提示。
- 影响 `.trae/skills/pca/SKILL.md` 中的前置检查、更新流程和备用 MCP 调用说明。
- 新增或规范 `.trae/skills/**/manifest.json`、`.trae/skills/pca/tools/mcp_client.py` 等可分发资源文件。
- 不新增第三方依赖；继续使用标准库 `json`、`zipfile`、`pathlib` 等实现。