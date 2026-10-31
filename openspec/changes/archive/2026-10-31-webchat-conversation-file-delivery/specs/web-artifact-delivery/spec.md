# web-artifact-delivery Delta

## ADDED Requirements

### Requirement: mcp_server 原生 file_id 产物必须自动交付给前端

对白名单 MCP 工具（`generate_device_archive_template`、
`get_device_archive_template_download`、`save_conversion_config`、`pack_bundle`）
返回的 `file_id`，webchat 后端 MUST 在会话事件循环内立即使用该会话凭据回源
mcp_server 取产物字节，落会话工作区 `xlpa-output/` 并登记产物、产 `artifact`
事件，供前端复用既有一次性 grant 下载流程。`file_id`、owner 摘要与 Token MUST NOT
出现在事件 payload、下载 URL 或浏览器可见位置。同一会话内同一 `file_id` MUST 只
登记一次（重复的工具结果不产生重复下载卡片）。回源失败（非 200、超时或超过大小
上限）MUST 产 `error` 事件显式告知用户，MUST NOT 静默丢弃，且错误文案 MUST NOT
包含回源 URL、owner 摘要或 Token。本能力在 webchat 侧实现，MUST NOT 改动
mcp_server。

#### Scenario: 建档模板生成后可直接下载

- **WHEN** Agent 调用 `generate_device_archive_template` 并返回 `file_id`
- **THEN** 后端立即回源取模板字节落 `xlpa-output/`，前端收到 `artifact` 事件并可
  经按需铸造 grant 下载该模板
- **THEN** 即使 Agent 之后再次生成模板（服务端清理旧快照），已落盘的旧模板仍可下载

#### Scenario: 重复工具结果不重复登记

- **WHEN** Agent 对同一 `file_id` 多次调用下载信息查询工具
- **THEN** 后端只登记一次，事件流不出现重复的下载卡片

#### Scenario: 回源失败显式提示

- **WHEN** 回源请求返回非 200 或超时
- **THEN** 事件流出现 `error` 事件提示产物获取失败，不落半成品文件，
  且事件内容不含 URL/owner/Token

#### Scenario: 白名单外工具不触发回源

- **WHEN** 非白名单工具结果中出现 `file_id` 字段
- **THEN** 后端不回源、不登记产物
