## Why

远程客户端在"只用 server 工具"的约束下，回传 149KB 已填工作簿时 `upload_device_archive_template` 要求把整份 Base64（199,648 字符）作为单个工具参数内联传入，直接撞 Windows argv≈32,767 字符上限，且远端服务器无法读取客户端本地 `excel_path` → 被迫在本地写 `upload_template.py` 走旁路 JSON-RPC 直投。这是"用户只给文件、结果由服务端返回"目标的第一个硬缺口。

## What Changes

- 扩展 `upload_device_archive_template`：新增可选的分块模式参数 `upload_id` / `seq` / `is_last`，让客户端把大文件切成多次**小巧** Base64 片段提交；不新增独立工具名、不改单文件一次性上传的既有默认行为（向后兼容）。
- 服务端按 `upload_id` 缓冲分块、归属发起调用者、带 TTL 与大小/片数上限；末片 `is_last=true` 触发合并，套用与单次上传完全一致的全量校验（大小、真实 XLSX 格式、宏/异常膨胀拒绝、结构与版本、快照绑定），产出等价 `file_id` + 摘要。
- 未 `commit`（未收到末片或未完整）MUST NOT 生成可解析 `file_id`、不建会话、不落快照。

## Capabilities

### New Capabilities
<!-- 无 -->

### Modified Capabilities
- `xlpa-archive-template-delivery`: 新增"回传大工作簿必须支持服务端分块摄取"要求（分块模式经扩展现有 `upload_device_archive_template` 的参数实现），保持既有大小/格式/版本/快照/越权校验与凭据隔离不变；本期**不含** `file_url` 与 HTTP multipart 通道。

## Impact

- 代码：`mcp_server/edge_tools.py`（`upload_device_archive_template` 加 `upload_id/seq/is_last` 模式 + 合并/落快照）、`mcp_server/archiving/snapshot_store.py`（分块临时缓冲、owner 归属、TTL）。
- 契约/测试：`server.py` 工具描述更新（入参新增，名称与 `TOOLS` 计数不变）；`mcp_server/tests/` 新增分块上传等价/中断/越权用例。
- 版本：`mcp_server/version.json` minor bump；若纳入交付资源包则同步 `package-manifest.json` 与相关 skill `manifest.json`/`SKILL.md` frontmatter。
- 非目标：不引入 `file_url`/multipart；不改 `read_device_archive_template` 解析契约；不改快照有效期语义；不放宽任一既有校验。
