## Context

- 实测数据：45 页 / 4.6MB PDF 单次提取 31.21s~40.47s；线上 14 次重复上传的
  sidecar 比 PDF 落盘晚 55~152 秒完成。
- `document` 通道此前 `await asyncio.to_thread(_extract_pdf_sidecar, ...)` 后
  才 `return body`，只是把 CPU 从事件循环挪走，HTTP 响应仍要等解析完成。
- 前端点击处理没有禁用按钮/进度提示；浏览器同源连接被长请求占满，后续点击
  在浏览器侧排队，用户感知为“点击无反应”。

## Decisions

### D1 上传响应与文本提取解耦

`upload` 接收 `BackgroundTasks`；PDF 落盘后立即返回
`{"path": ..., "text_status": "pending"}`，并把
`_build_pdf_text_result(workspace, pdf_path)` 投递到后台任务。后台任务再用
`asyncio.to_thread` 执行 pypdf，完成后向会话事件流追加 `upload_text`：

- 成功：`{name, text_path, text_chars}`
- 失败/无文本/写盘失败：`{name, warning}`

会话被物理删除（`runtime.get(sid) is None`）时不再写事件，避免向已删除会话
追加孤儿事件。

### D2 前端忙碌态与防重复

点击上传后立即：`btn.disabled = true`、按钮文案改为“上传中…”、提示
“正在上传 <文件名>…”。请求结束（成功或失败）在 `finally` 恢复按钮，避免
异常路径把按钮永久禁用。成功后才清空 `fileEl.value`；失败保留文件以便重试。

### D3 通道与类型匹配

前端选文件时按扩展名切换通道（xlsx/xls/xlsm→建档表格；图片→截图；其余→
文档），默认通道为「文档」。服务端建档表格分支校验扩展名，不匹配直接 400
并提示改用「文档」或「截图(OCR)」，不再把 PDF 代理到建档端点。

## Risks / Trade-offs

- 后台任务不随客户端断线取消，重复上传仍会并发解析；本变更通过前端防重复
  降低触发概率，未做服务端去重（后续可按 sha256 去重）。
- `upload_text` 是新增事件类型，旧前端会按 unknown 忽略（向后兼容）。
- 上传响应不再包含 `text_path`，调用方需从 `upload_text` 事件获取；本仓库
  唯一消费方是 webchat 前端，已同步更新。
