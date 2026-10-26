## Why

当前 `/pca` 入口与协议转换交付记录仍存在几类可用性问题：用户不知道何时需要提供后端登录参数，本地 Skill 可能落后于 MCP Server 导出的新版本，接入配置仍可能出现不友好的 IPv6 地址，协议转换记录对字段语义、差异决策、歧义确认、测试与未验证项的表达不够稳定。需要将这些约定沉淀为可执行、可验证的 PCA 入口与交互记录工作流规范。

## What Changes

- 为 `/pca` 入口新增前置状态检查：探测 MCP 连接、显示 access level、检查本地是否已有后端业务 Token；有 Token 时不提示登录，无 Token 时提示用户提供 `phoneNum`/`code`，获取一次后保存到本地。
- 明确后端业务 Token 的本地保存只用于后端 API 工具参数，不得与 MCP 接入 Token 混用；Token 失效或缺失时重新提示登录。
- 为 `/pca` 增加更新本地 Skills 的操作：检查版本、从 MCP Server 下载全部 Skills、更新前备份、用户确认后允许覆盖全部本地 Skills，并提示重新加载会话。
- 明确接入页面、配置生成、交互输出优先使用 IPv4，不展示 IPv6 地址；服务端内部仍可识别 IPv6 localhost 以保持兼容。
- 增强协议转换交互记录输出：增加结论摘要、下一步建议、阶段化命名、字段语义拆分表、点表 Hex/Dec/寄存器跨度/单位、歧义项确认表、平台暂无数据项策略、最小冒烟测试清单、未验证项清单。
- 明确 `func_code` 来自协议文档；协议文档无说明或存在不确定/多选值时必须列出歧义并由用户确认。
- 明确 `data_type` 优先使用 Skill 规范（如 `[FLOAT32]`），平台历史写法差异需标注但不得自动覆盖 Skill 规范。
- 明确来源标记需精确到字段级，例如 `MCP:get_model_list.rows[i].brandId`，而不是仅标记到工具名。
- 本次只规划 `/pca` 与 MODBUS 协议转换交互输出规则，不实现 HTTP/MQTT 专属协议转换流程重构。

## Capabilities

### New Capabilities
- `pca-entry-workflow`: 定义 `/pca` 入口的 MCP 探测、业务 Token 本地缓存、Skills 全量更新、IPv4 接入展示与权限提示行为。

### Modified Capabilities
- `modbus-mcp-workflow`: 增强 MODBUS 协议转换中的歧义确认、字段来源精确标记、最终交互记录输出、测试清单和未验证项规则。

## Impact

- 影响 Skill 文档：`.trae/skills/pca/SKILL.md`、`.trae/skills/modbus-conversion/SKILL.md`，用于落地入口前置检查、业务 Token 提示/缓存、Skill 更新引导、协议转换记录模板与字段决策规则。
- 影响 MCP 服务实现：`mcp_server/server.py`、`mcp_server/static/access.html`，用于提供或展示 Skills 版本信息、Skills ZIP 下载、IPv4 优先接入信息；如实现本地更新辅助脚本，可能新增脚本或工具但不得直接暴露 Token。
- 影响运行时约定：本地业务 Token 缓存位置、失效检测、更新前备份目录、更新后重载提示需要明确实现和验证。
- 影响 OpenSpec 规格：新增 `pca-entry-workflow`，并增补 `modbus-mcp-workflow` 的输出与歧义确认要求。
- 不影响已归档的 MODBUS MCP 原子工具实现边界；不改变“平台写入必须 system 权限 + 用户确认”的规则；不要求服务端拒绝 IPv6 请求，仅要求用户可见配置不展示 IPv6。