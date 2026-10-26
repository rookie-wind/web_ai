## Context

动机见 `proposal.md - Why`。约束：`upload_device_archive_template` 现仅收单个 `file_content_base64`（[edge_tools.py L996-998](file:///e:/codeGIT/pca-mcp-server/mcp_server/edge_tools.py#L996-L998)）；远端服务器不可读客户端本地路径；分块需要服务端持有跨调用的临时缓冲。既有快照存储 `archiving/snapshot_store.py` 已管理 `file_id` 生命周期，是自然的落点。

## Goals / Non-Goals

**Goals:**
- 让单次工具调用参数体积远小于最严客户端传输上限，从而无需本地脚本回传大工作簿。
- 分块合并后与单次上传行为完全等价（校验、`file_id`、摘要、有效期）。

**Non-Goals:**
- 不引入 `file_url` 拉取与 HTTP multipart 端点。
- 不改解析/计划/执行链路与任何校验语义；不改快照有效期策略。

## Decisions

**D1 扩展现有 `upload_device_archive_template` 加分块模式参数，而非新增 `upload_begin/append/commit` 三工具。**
判定：同一工具靠 `upload_id` 缺省=单次、给定=分块续传、`is_last=true`=提交合并。*理由*：`TOOLS` 名称与计数不变、客户端迁移成本最低（贴合既定偏好）。*备选*：三工具（语义更清晰但工具面/契约膨胀）。

**D2 分片大小以"编码后 Base64 ≤ 30KB/片"为保守阈值。**
*理由*：安全低于 argv≈32,767（且整条命令行还含其它参数，留裕量）。*备选*：16KB 更稳但调用翻倍；64KB+ 省调用但逼近上限。阈值做成常量便于按最低公共客户端调。

**D3 分块缓冲归属 `owner_id`、带 `upload_id`、大小/片数上限与 TTL。**
落在 `snapshot_store` 同层的临时区分区，与已提交快照隔离；未完成即到期回收。*理由*：防缓冲堆积与跨调用者窥探。

**D4 `commit`（末片）复用单次上传的完整校验管线。**
合并字节后走同一路径：大小/真实 XLSX/宏/异常膨胀/版本/快照绑定 → 生成正式 `file_id`，保证等价性；避免分块分支自成弱校验。

## Risks / Trade-offs

- [分块缓冲被滥用/耗尽内存磁盘] → 单 `upload_id` 片数与总字节上限、owner 配额、TTL 回收。
- [中断导致半截上传] → 未末片不落地、可续传且去重，绝不产出半成品 `file_id`。
- [分块与单次结果漂移] → 测试直接比对分块合并的 `sha256`/`size` 与单次上传一致。
- [工具语义变复杂（一个工具两态）] → 参数组合互斥校验：`upload_id`/`seq`/`is_last` 必须成套出现，否则明确拒绝。

## Migration Plan

1. `snapshot_store` 增分块缓冲 API（begin/append/commit、owner、TTL）。
2. `upload_device_archive_template` 增加分块模式参数并保持单次上传默认路径不变。
3. 补分块等价/中断续传/越权/参数互斥用例；更新 server.py 工具描述与版本。
4. 回滚：新参数为可选，客户端不使用即回到旧单次上传行为，主链路无影响。

## Open Questions

- 单片阈值最终取值以最低公共客户端上限为准（实现期定，不影响规格与任务边界）。
