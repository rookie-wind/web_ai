## MODIFIED Requirements

### Requirement: PDF 文档必须提取文本且失败显式降级

`document` 通道接收 PDF 后，系统 MUST 在保留原文件的同时把 PDF 抽取为
结构化 Markdown 并写 `xlpa-input/<stem>.pdf.md`（表格 MUST 以 GFM 表格
保留列结构，MUST NOT 输出丢失表格结构的逐页纯文本）。上传响应 MUST
立即返回 `text_status="pending"` 与 `path`，MUST NOT 等待文本提取完成。
提取 MUST 在后台执行，完成后 MUST 向同一会话事件流追加 `upload_text`
事件：成功载荷含 `text_path`（指向 `.pdf.md`）与 `text_chars`；依赖
缺失、解析失败、未提取到文本或写盘失败时载荷 MUST 含显式 `warning`，
且 MUST NOT 伪造"已提取文本"。会话已被物理删除时 MUST NOT 追加事件。

#### Scenario: 正常 PDF

- **WHEN** 用户上传含文本的 PDF
- **THEN** 原 PDF 立即落盘，响应返回 `text_status=pending`；后台完成后
  `<stem>.pdf.md` 与 `upload_text` 事件出现

#### Scenario: 含表格的 PDF 保留列结构

- **WHEN** 用户上传含带框线寄存器点表的 PDF
- **THEN** `upload_text` 的 `text_path` 指向 `.pdf.md`，该文件中原表格
  以 GFM 表格呈现且单元格不与原版面列位置串位

#### Scenario: 正常 PDF 立即返回

- **WHEN** 用户上传含文本的大 PDF
- **THEN** 上传响应在秒级返回 `text_status=pending` 与原文件路径，不等待解析

#### Scenario: 后台提取完成

- **WHEN** 后台解析完成
- **THEN** 事件流出现 `upload_text`，含 `text_path` 与 `text_chars`

#### Scenario: 损坏或扫描件 PDF

- **WHEN** 上传的文件无法解析或没有文本层
- **THEN** 上传返回 200 且原文件保留；`upload_text` 载荷含 `warning`，不生成
  空的文本文件
