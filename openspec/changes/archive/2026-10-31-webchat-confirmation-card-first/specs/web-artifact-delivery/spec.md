# web-artifact-delivery Delta

## ADDED Requirements

### Requirement: 产物必须由显式请求或原生产物产生

系统 MUST NOT 仅因工具结果体积超过某个阈值就自动生成并登记下载产物。产物来源
MUST 限于：Agent 在会话工作区 `xlpa-output/` 显式写入的文件，以及白名单 MCP
工具（`generate_device_archive_template`、`get_device_archive_template_download`、
`save_conversion_config`、`pack_bundle`）返回 `file_id` 的原生产物。用户未要求
生成文档时，MUST NOT 出现额外的下载卡片或落盘文件。

#### Scenario: 大体积工具结果不产生产物

- **WHEN** 一次只读工具调用（如 `list_mcp_tools`）返回超过 8000 字的结果，
  用户并未要求生成文档
- **THEN** 不产生落盘文件，不产 `artifact` 事件，也不出现下载卡片

#### Scenario: 显式写入仍产生产物

- **WHEN** Agent 因用户请求在 `xlpa-output/` 生成文本类文档
- **THEN** turn 收尾扫描登记该文件并产 `artifact` 事件

#### Scenario: 原生产物仍自动交付

- **WHEN** 白名单 MCP 工具返回 `file_id`（如建档模板）
- **THEN** 后端回源落盘并产 `artifact` 事件，用户可直接下载
