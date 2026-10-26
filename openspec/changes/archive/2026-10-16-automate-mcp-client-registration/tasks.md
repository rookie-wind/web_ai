## 1. 接入页平台路径表与文本改造（access.html）

- [x] 1.1 在 `PLATFORMS` 为每个平台补 `configPath`（真实配置文件）与 `configLevel`（user/project），值取自 design D2 表（验证：逐平台与 D2 表一致，无遗漏）
- [x] 1.2 让 `configPath`/条目格式与 `generateText()` 现有 JSON 生成分支共用同一处定义，避免路径表与实际 JSON 漂移（验证：同一平台路径表 rootKey 与其 JSON 片段 rootKey 一致）
- [x] 1.3 重写 `generateText()` 安装段为文本驱动：指示 Agent 按 D3 的"不存在则创建 / 存在则先读只改 `protocol-converter` 键并保留其它 server / 非法 JSON 先备份再中止 / 幂等"写入 `configPath`（验证：Qoder 文本含 `~/.qoder/mcp.json` 与"保留其它 server、幂等"约束语句，且不含运行脚本的命令）
- [x] 1.4 在安装段加入"写入后调用 `list_mcp_tools` 验证、失败回退手动"的步骤（验证：文本含验证与回退两步）
- [x] 1.5 保留手动兜底：继续输出该平台完整可粘贴 JSON 与目标文件路径（验证：Qoder 段落含无 `type` 字段的 JSON 片段与路径）
- [x] 1.6 更新 Qoder 等 `configLocation` 文案由"设置手动粘贴"改为标注真实文件路径（验证：页面显示 `~/.qoder/mcp.json`）
- [x] 1.7 端点主机 IPv4/`localhost` 约束：文本生成的 url 不含 IPv6（验证：审查生成文本；构造 IPv6 场景不产出）
- [x] 1.8 凭据约束：文本仅含接入 Token 且提示敏感、不含后端业务 Token（验证：审查生成文本）

## 2. 服务端与工具解耦

- [x] 2.1 复核 `mcp_server/server.py` 无写死工具目录（打包源为 `agent_assets/skills`）（验证：grep 无 `.trae`/具体 IDE 目录硬编码路径）
- [x] 2.2 将 `mcp_server/install.bat` 生成 `.trae/mcp.json` 改为可选或移除，使服务端部署不预设工具，并保留兼容说明（验证：默认执行不再写工具专属配置，或写入明确标注为可选）

## 3. Skill 文档与资源包

- [x] 3.1 更新 `agent_assets/skills/xlpa/SKILL.md`：接入说明改为文本驱动直接写入 + 验证 + 手动兜底；**不新增**注册脚本小节（验证：文档不含 `register_mcp_client.py`，含直接写配置指引）
- [x] 3.2 确认 `package-manifest.json` 与 `xlpa/manifest.json` 未把任何注册脚本列为必需文件，且 `_validate_package_manifest()` 通过（验证：校验返回 `ok=true`，requiredFiles 不含注册脚本）
- [x] 3.3 运行 `_create_skills_zip()` 确认打包正常、ZIP 顶层仍为 `skills/`（验证：namelist 命中现有必需文件、无缺文件）

## 4. 文档与端到端验证

- [x] 4.1 更新 `mcp_server/README.md` 与 `mcp server部署.md`：文本驱动自动注册、服务端解耦、各平台真实配置文件路径（验证：文档审查含路径表与 Qoder `~/.qoder/mcp.json` 说明）
- [x] 4.2 端到端冒烟（Qoder）：按新接入文本让 Agent 写入 `~/.qoder/mcp.json`，确认合并保留其它 server、`list_mcp_tools` 验证通过（验证：文件出现 protocol-converter 且工具可调用）
- [x] 4.3 端到端冒烟（Trae 项目级）：验证文本驱动写入 `.trae/mcp.json` 合并正确（验证：其它 server 保留、验证通过）
- [x] 4.4 回归 `mcp_server/tests`（skills/manifest 相关）（验证：`pytest -k "skills or package or manifest"` 全绿）
- [x] 4.5 `openspec validate automate-mcp-client-registration --strict` 通过（验证：命令零告警退出）
