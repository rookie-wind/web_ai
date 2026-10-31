## Context

webchat 已有完整产物交付链路：`xlpa-output/` 扫描 → `ArtifactRegistry` 登记 →
`artifact` 事件 → 按需铸造一次性 `DownloadGrantStore` 票据 → 代理下载。缺的是
"产物如何进入工作区"：mcp_server 原生产物是 `file_id`（私有快照库），agent 则没有
任何被允许的本地写入工具。本变更只补这两条进入路径，不改变既有下载/上传/保留期语义。

## Decisions

### D1 来源 B 在事件时立即回源落盘（而非下载时按需代理）

- 工具结果返回 `file_id` 时，后端立即用会话 `mcp_token` 回源取字节、写
  `xlpa-output/`、登记并产 `artifact` 事件。
- 理由：mcp_server 快照对同一 owner 只保留最新一份（`purge_old_for_owner`）且有
  30 天 TTL；若下载时才回源，Agent 再次生成模板后旧卡会 404。立即落盘使产物归属
  会话工作区，复用既有 result 分类保留期，下载流程零改动。
- 代价：每次生成多一次内网请求（超时 60s，失败不影响本轮事件流）。

### D2 白名单工具与 file_id 幂等

- 触发工具：`generate_device_archive_template`、
  `get_device_archive_template_download`、`save_conversion_config`、`pack_bundle`。
  这些工具结果含 `file_id`（前两个与后两个均如此），且均属只读/执行类，不涉门禁。
- `WebSession` 维护 `remote_files: file_id -> artifact_id`；已登记的 `file_id` 直接
  跳过（避免 Agent 重复查下载信息产生重复卡片）。
- 文件名优先取结果 `file_name`/`template_name` 的 basename，空则回退 `<file_id>.bin`；
  同名文件用 `unique_path` 追加后缀，不覆盖既有产物。

### D3 owner 摘要派生

- mcp_server 下载端点要求 `owner=sha256(mcp_token)`。webchat MUST NOT import
  mcp_server，因此在 webchat 内复制同一 6 行派生逻辑（仅用于回源查询参数）。
- owner 摘要、`file_id`、Token MUST NOT 写进事件 payload 或浏览器 URL；回源请求在
  后端完成，前端只看到已落盘的 artifact_id。

### D4 内置写入收敛到会话产物目录

- 放行工具：`Write`/`Edit`/`MultiEdit`/`NotebookEdit`。
- 裁决顺序：缺 `file_path` → deny；未注入工作区 → deny；`resolve()` 后必须
  `is_relative_to(workspace/xlpa-output)`；扩展名必须在文本白名单内。
- deny 一律 `confirmable=False`（策略禁止，确认无法解除）；deny 仍走既有
  `gate_blocked` 事件与审计台账，便于回看。
- `Bash` 及所有其他非 MCP 工具（除 Skill）保持 deny。`WriteGate` 未注入
  `workspace_dir` 时（存量测试/无工作区场景）内置写入保持全 deny（Fail-Closed）。

### D5 失败显式但不泄漏

- 回源失败（非 200/超时/超限）只产一条 `error` 事件，文案含产物名与 file_id，
  MUST NOT 含 URL、owner 摘要或 Token；服务端日志同样不打 URL。

### D6 不新增配置与端点

- 回源超时与单文件上限用模块常量；下载端点/前端卡片复用既有实现。

## Risks

- 内置写入放行扩大了 agent 的本地能力，但半径限定在会话产物目录与文本扩展名，
  不影响平台写入与门禁票据；需在 spec 中明确写死。
- 来源 B 回源依赖 mcp_server 可达；失败时用户收到 error 事件，不影响对话继续。
- 不能 import mcp_server，owner 派生逻辑存在两处副本；以注释锚定来源，防漂移。

## Migration

- 无数据迁移；存量会话工作区与登记表语义不变。
