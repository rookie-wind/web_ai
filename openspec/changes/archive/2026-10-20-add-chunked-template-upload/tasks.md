## 1. 分块缓冲存储

- [x] 1.1 在 `archiving/snapshot_store.py` 增设按 `upload_id` 归属 `owner_id` 的临时分块缓冲 API（建会话/追加片/取已收序/合并/丢弃），带单上传总字节与片数上限和 TTL；单测覆盖顺序追加、缺口可判定、到期回收

## 2. upload 工具分块模式

- [x] 2.1 给 `upload_device_archive_template` 增加可选 `upload_id`/`seq`/`is_last` 参数并做互斥成套校验（三者必须齐备或全缺省为单次上传）；保持缺省单次上传行为与返回结构不变（跑既有上传用例 `TestUploadDeviceArchiveTemplate` 全绿）
- [x] 2.2 非末片：仅追加缓冲并回 `{upload_id, next_seq, received_bytes}`，MUST NOT 生成 `file_id`；测试断言未 `is_last` 时无可解析 `file_id`、无会话
- [x] 2.3 末片 `is_last=true`：合并全部分片后复用单次上传的完整校验管线（大小/真实 XLSX/宏/异常膨胀/版本/快照）产出 `file_id`+摘要；测试比对分块合并的 `sha256`/`size` 与整体单次上传一致

## 3. 安全与边界

- [x] 3.1 分块归属隔离：以他人 `upload_id` 追加/提交被拒且不泄露存在性；补越权拒绝用例
- [x] 3.2 资源上限用例：超片数/总字节上限、非 XLSX/宏/异常膨胀在末片校验时被拒；确认无半成品 `file_id` 落地

## 4. 契约、文档与版本

- [x] 4.1 更新 `server.py` 中 `upload_device_archive_template` 描述与能力矩阵说明（新增分块入参；工具名与 `TOOLS` 计数不变）
- [x] 4.2 版本按 minor bump `mcp_server/version.json`；若纳入交付资源包则同步 `package-manifest.json` 与相关 skill `manifest.json`+`SKILL.md` frontmatter 一致升版
- [x] 4.3 跑 `python -m pytest mcp_server/tests`（不含浏览器用例）全绿，回归既有上传/解析/交付契约
