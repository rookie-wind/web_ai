## Why

C5 归档时明确"来源 B（mcp_server 原生 file_id 产物）自动检测一期不做、降级二期"
（tasks 4.5），C7 演练 tasks 6.1 进一步记录了该缺口导致的实测后果：AC-1 建档闭环的
"下载"腿需要 by-agent 产物，而 write-gate-isolation 主 spec 要求工具面收敛为 MCP、
内置文件/命令工具关闭，当前架构不可达。

实测确认两处断点：

1. **模板/原生产物拿不到**：`generate_device_archive_template` 只返回
   `file_id/file_name/size/sha256`，字节存在 mcp_server 私有快照库；下载端点
   `/api/archive/templates/<id>?owner=` 需由 Token 派生的 owner 参数。webchat 没有
   回源端点，前端也没有可用入口——用户只能看到一段 file_id 文本。`save_conversion_config`
   的 JSON 与 `pack_bundle` 的 ZIP 同理。
2. **Agent 写不了本地文档**：SDK 层仅禁用 Bash，但写入门禁对所有非 MCP 工具
   （除 Skill）一律 Fail-Closed 拒绝，`Write`/`Edit` 也在其中且有锁定测试。技能文档
   里"把产物写 `<会话工作区>/xlpa-output/`"在真实 Web 会话中会被直接拦截；现有 e2e
   测试用伪造句柄直接写盘，绕过了门禁。

## What Changes

- **来源 B 桥接（webchat 侧，mcp_server 零改动）**：在会话事件循环中识别白名单工具
  结果里的 `file_id`，后端用该会话 `mcp_token` 立即回源 mcp_server 取字节，落会话
  工作区 `xlpa-output/` 并登记产物、产 `artifact` 事件。`file_id`、owner 摘要、
  Token MUST NOT 进入事件 payload、下载 URL 或浏览器历史。同一会话同一 `file_id`
  只登记一次。回源失败 MUST 产 `error` 事件显式告知，MUST NOT 静默丢弃。
- **内置写入受限放行**：`Write`/`Edit`/`MultiEdit`/`NotebookEdit` 允许执行，但目标
  路径经 `resolve()` 后 MUST 位于 `${会话工作区}/xlpa-output/` 内，且扩展名 MUST 为
  文本类文档（md/txt/csv/tsv/json/jsonl/html/htm/xml/yaml/yml/log/sql）。越界路径、
  缺失 `file_path`、非白名单扩展名与工作区未配置一律 deny（不可经确认解除）。
  `Bash` 及其他内置工具面继续 deny。
- **契约与接口不变**：不新增下载端点、不新增配置项；下载仍走既有"一次性 grant +
  代理下载"流程，前端复用既有 `artifact` 事件卡片。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `web-artifact-delivery`: 新增"mcp_server 原生 file_id 产物必须自动交付"要求；
  产物来源 A（工作区扫描）与来源 B（file_id 回源）并存。
- `write-gate-isolation`: "运行时工具面 MUST 收敛为 MCP、内置文件工具关闭"修订为
  "内置写入工具仅在会话产物目录内、且仅文本类文档时放行；其余内置工具面仍关闭"。
- `agent-runtime-session`: "产物就绪事件"场景由"来源 B 一期不做"更新为已支持来源 B
  自动交付。

## Impact

- **webchat 后端**：`runtime.py`（回源、登记、去重、失败事件）、`grants.py`（内置写入
  路径裁决）、`artifacts.py`（`unique_path` 公共化）。
- **mcp_server**：零改动（复用既有 `/api/archive/templates/<id>?owner=` 回源）。
- **前端**：零改动（复用既有 artifact 卡片与 grant 下载）。
- **配置/依赖**：不新增配置与依赖。
- **测试**：新增来源 B 回源/去重/失败用例；修订内置工具锁定用例（Write 在
  `xlpa-output/` 内放行、越界/扩展名/缺参拒绝）；webchat 全量 + 主 pytest 基线全绿。
- **安全语义**：内置写入被收敛到会话工作区产物目录，不触及平台写入与门禁票据；
  Bash/命令执行仍关闭。
