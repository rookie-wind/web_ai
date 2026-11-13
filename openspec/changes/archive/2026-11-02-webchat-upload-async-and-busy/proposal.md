## Why

PDF 文本提取被放在上传请求的同步返回路径上：一份 45 页、4.6MB 的说明书在本机
提取需 31~40 秒，前端没有“上传中”状态，用户点击上传后长时间看不到反馈，误以为
没有反应并反复点击，线上同一会话累积了 14 份重复 PDF（约 68MB），并发解析又把
单次耗时放大到 1.5~2.5 分钟（`_ac1_run/webchat.log` 中上传最终均为 200）。

此外，上传通道与文件类型不匹配时（把 PDF 选成「建档表格」）只会得到难以理解的
“上游 HTTP 400”。

## What Changes

- **A：上传立即返回**：`document` 通道保存 PDF 后立即返回
  `text_status=pending`；文本提取改为后台任务（线程池），完成后写
  `xlpa-input/<stem>.pdf.txt` 并产 `upload_text` 事件（成功含
  `text_path`/`text_chars`，失败含 `warning`）。
- **C：上传忙碌态与防重复**：上传期间禁用按钮并显示“上传中…”，成功后清空文件
  选择；PDF 返回 pending 时提示“文本提取在后台进行，完成后会提示”。
- **通道与类型匹配**：前端按扩展名自动选择通道（默认「文档」）；服务端拒绝
  建档表格通道接收非 Excel 文件，并给出可操作提示。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `web-artifact-delivery`: PDF 文本提取改为后台执行 + `upload_text` 事件。
- `web-chat-ui`: 上传通道自动匹配、上传忙碌态与防重复提交。
