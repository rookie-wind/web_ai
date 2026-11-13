# web-artifact-delivery Delta

## ADDED Requirements

### Requirement: PDF 文档必须提取文本且失败显式降级

`document` 通道接收 PDF 后，系统 MUST 在保留原文件的同时用 `pypdf` 提取
文本并写 `xlpa-input/<stem>.pdf.txt`，响应 MUST 返回 `text_path` 与
`text_chars`。依赖缺失、解析失败或未提取到文本时，上传 MUST 仍成功并保留
原文件，但 MUST 返回显式 `warning`，MUST NOT 伪造"已提取文本"。

#### Scenario: 正常 PDF

- **WHEN** 用户上传含文本的 PDF
- **THEN** 原 PDF 与 `<stem>.pdf.txt` 同时存在，响应返回 `text_path`

#### Scenario: 损坏或扫描件 PDF

- **WHEN** 上传的文件无法解析或没有文本层
- **THEN** 上传返回 200、原文件保留、响应含 `warning`，且不生成空的文本文件
