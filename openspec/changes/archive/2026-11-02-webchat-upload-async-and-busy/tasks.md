## 1. A：上传立即返回 + 后台提取

- [x] 1.1 `artifacts.py`：`upload` 注入 `BackgroundTasks`；PDF 落盘后返回
  `text_status=pending`，不再同步等待解析。
  验证：真实 HTTP 上传 4.6MB PDF 响应 **0.24s**（改造前 31~40s）。
- [x] 1.2 新增 `_build_pdf_text_result`（纯函数，供线程池调用），成功写
  `<stem>.pdf.txt`，失败/无文本/写盘失败返回 `warning`。
- [x] 1.3 后台完成后向事件流追加 `upload_text`；会话已删除则跳过。
  验证：真实 HTTP 上传后 **35.56s** 收到
  `payload={text_path, text_chars:39878}`。
- [x] 1.4 前端新增 `upload_text` 渲染：成功显示“已提取 PDF 文本：<path>（N 字）”，
  失败显示“PDF 文本提取失败：<warning>”。

## 2. C：上传忙碌态与防重复

- [x] 2.1 点击上传立即禁用按钮、文案改“上传中…”、提示“正在上传 <文件名>…”。
- [x] 2.2 `finally` 恢复按钮；仅成功后清空文件选择，失败保留以便重试。
- [x] 2.3 PDF pending 响应提示“文本提取在后台进行，完成后会提示”。
  验证：`test_static_frontend.py` 断言 `btn.disabled = true`、`上传中…`、
  `res.text_status === "pending"`、`case "upload_text"`。

## 3. 通道与类型匹配（承接上一次修复）

- [x] 3.1 前端默认通道「文档」，选文件按扩展名自动切换。
- [x] 3.2 服务端建档表格通道拒绝非 Excel 文件，返回可操作 400，不代理上游。
  验证：`test_archive_table_rejects_pdf_with_actionable_hint`。

## 4. 回归

- [x] 4.1 webchat 全量：**170 passed, 0 failed**。
- [x] 4.2 真实 HTTP 验证：上传 0.24s、后台事件 35.56s、文本 39,878 字符。
- [x] 4.3 `openspec validate --all --strict` 通过后归档。
