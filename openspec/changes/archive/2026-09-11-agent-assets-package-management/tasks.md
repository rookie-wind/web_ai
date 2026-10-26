## 1. 资源包 Manifest 与目录结构

- [x] 1.1 新增包级 manifest 到资源包可分发范围，并验证 ZIP 中能看到该文件
- [x] 1.2 为 `pca` Skill 新增 `manifest.json`，声明 `SKILL.md`、`agents/openai.yaml`、`tools/mcp_client.py` 等必需文件，并验证 JSON 可解析
- [x] 1.3 为其它现有 Skill 补充最小 `manifest.json`，至少声明 `SKILL.md` 和 `agents/openai.yaml`，并验证所有 manifest 的必需文件存在
- [x] 1.4 规范未来可扩展目录（`tools/`、`templates/`、`validators/`、`references/`）的打包语义，并验证空缺可选目录不阻塞打包

## 2. MCP 客户端工具分发

- [x] 2.1 将通用 MCP 客户端放入 `pca/tools/mcp_client.py`，并验证可从项目根执行 `python .trae/skills/pca/tools/mcp_client.py list_mcp_tools`
- [x] 2.2 确认备用客户端自动向上查找 `.trae/mcp.json`，并验证在 Skill 目录和项目根执行时读取同一配置
- [x] 2.3 确认备用客户端 Token 刷新后回写 `.trae/mcp.json`，并通过模拟失效 Token 验证重试逻辑
- [x] 2.4 明确服务端本机 `mcp_server/mcp_client.py` 与分发版客户端的关系，避免两份逻辑漂移，并验证两者调用 `list_mcp_tools` 输出一致或服务端版本仅作为薄封装

## 3. 服务端资源包导出

- [x] 3.1 更新 `_create_skills_zip()` 或等效打包逻辑，确保 `manifest.json`、`tools/`、`templates/`、`validators/`、`references/` 均随 `.trae/skills/` 打入 ZIP，并通过 ZIP 列表验证
- [x] 3.2 保持 `/api/docs/export-skills-package` 端点兼容，验证旧下载 URL 仍返回可解压 ZIP
- [x] 3.3 如包级 manifest 位于 `.trae/`，扩展打包逻辑将其写入 ZIP 根部；如位于 `.trae/skills/`，验证其自然进入 ZIP
- [x] 3.4 可选新增资源包信息端点或在 `list_mcp_tools` 返回资源包版本信息，并验证前置检查可读取版本来源

## 4. 接入页安装说明

- [x] 4.1 将 `access.html` 中“Skills 包”用户说明更新为“Agent 资源包”，并验证生成文本包含资源包下载地址和解压目标
- [x] 4.2 在接入文本中加入 manifest 校验步骤，验证文本列出缺失必需文件时不得声称安装完成
- [x] 4.3 在接入文本中加入 `pca/tools/mcp_client.py` 备用通道说明，验证文本不暗示安装后自动运行脚本
- [x] 4.4 保持各 IDE 的 MCP JSON 配置格式不变，验证 Trae/Cursor/VS Code/Claude/Windsurf/Cline/Kimi 示例仍生成合法 JSON

## 5. `/pca` Skill 更新流程

- [x] 5.1 将 `/pca` 前置检查中的“Skills 版本检查与更新入口”升级为“Agent 资源包版本检查与更新入口”，并验证不再只描述 `SKILL.md`
- [x] 5.2 更新 `/pca` 的资源包更新步骤：备份 `.trae/skills`、下载 ZIP、全量覆盖、读取 manifest、校验必需文件、提示重载，并验证步骤完整出现
- [x] 5.3 更新 `/pca` 的 MCP 调用策略：优先原生 MCP，失败时检查并使用 `pca/tools/mcp_client.py`，并验证文档明确 fallback 触发条件
- [x] 5.4 更新 `/pca` 的下一步建议和错误处理，确保更新失败时报告缺失项与备份路径，并验证文档包含失败分支

## 6. 验证与回归

- [x] 6.1 运行 `openspec validate agent-assets-package-management --strict` 并验证通过
- [x] 6.2 使用脚本或手工检查 ZIP 内容，验证资源包包含所有 manifest 声明的必需文件
- [x] 6.3 模拟首次接入流程，验证接入文本、解压说明、manifest 校验和 `list_mcp_tools` 探测路径闭环
- [x] 6.4 模拟后续更新流程，验证备份目录创建、全量覆盖、manifest 校验和重载提示闭环
- [x] 6.5 验证旧行为兼容：原 `/api/docs/export-skills-package` 下载、现有 IDE MCP JSON 配置和原生 MCP 调用流程不被破坏
- [x] 6.6 验证备用客户端仅在原生 MCP 调用失败时使用，原生 MCP 正常时不自动运行 Python 脚本