## Why

现有 PDF 文档通道用 `pypdf` 逐页 `extract_text()` 落 `<stem>.pdf.txt`，对
工业协议说明书这类**表格型 PDF** 会丢失表格结构（列错位、多列串成一行）。
实测（AMC_V3.10 说明书 45 页）该旁路产物无法用于 `modbus-conversion` 生成
可追溯的点表配置，导致客户端调用流程"跑得通、给的是坏数据"。已验证
PyMuPDF `find_tables()` 能按线条还原寄存器表并以 GFM 表格输出（0 列错位）。

## What Changes

- PDF 文本提取由 `pypdf` 逐页纯文本改为 **PyMuPDF 结构化抽取**：逐页正文块
  + 表格转 GFM + `## 第 N 页` 锚点，产出 Markdown。
- 旁路文件后缀由 `<stem>.pdf.txt` 改为 **`<stem>.pdf.md`**（BREAKING：历史
  会话工作区仍留存 `.pdf.txt`，新上传不再产出该后缀）。
- 三处 `.pdf.txt` 引导文案同步改为 `.pdf.md`：后端读取护栏
  （`grants.py` `pdf_binary` 重定向）、Agent 系统提示
  （`sdk_runtime/adapter.py` `WEBCHAT_SYSTEM_APPEND`）、前端上传回执与
  拦截提示（`static/js/app.js`）。
- 抽取逻辑从仓库根临时脚本 `_pdf_to_md.py` **正式化**进 webchat 包内模块，
  补依赖声明（`requirements.txt`：`pypdf` → `PyMuPDF`）。
- 失败降级语义不变：依赖缺失/解析失败/无文本层/写盘失败仍落显式
  `warning`，MUST NOT 伪造"已提取"。

## Capabilities

### New Capabilities

- `pdf-structured-markdown-extraction`: PDF 到 Markdown 的结构化抽取契约
  （表格保真、页锚点可追溯、降级显式、依赖可插拔）。

### Modified Capabilities

- `web-artifact-delivery`: "PDF 文档必须提取文本且失败显式降级" 要求中，
  抽取产物由 `pypdf` 纯文本 `<stem>.pdf.txt` 改为结构化 Markdown
  `<stem>.pdf.md`，`upload_text` 事件的 `text_path` 随之变化。

## Impact

- 后端代码：`webchat/webchat/artifacts.py`（`extract_pdf_text` /
  `_build_pdf_text_result` / 模块 docstring）、新增包内抽取模块、
  `webchat/webchat/grants.py`（重定向文案与 `guard` 判定前缀）。
- 提示词：`webchat/webchat/sdk_runtime/adapter.py`（系统提示追加段）。
- 前端：`webchat/webchat/static/js/app.js`（上传回执、`upload_text` 展示、
  `pdf_binary` 拦截提示）。
- 依赖：`webchat/requirements.txt` 移除 `pypdf`、新增 `PyMuPDF`
  （纯 wheel，无需系统 poppler）。
- 测试：`webchat/tests/test_artifacts_upload.py`、`test_grants.py`、
  `test_gate_hook.py`、`test_static_frontend.py` 中 `.pdf.txt` 断言与
  新增表格保真用例。
- 不影响：上传响应契约字段名（`text_status`/`text_path`/`text_chars`/
  `warning`）、事件类型名、租约与下载链路。
