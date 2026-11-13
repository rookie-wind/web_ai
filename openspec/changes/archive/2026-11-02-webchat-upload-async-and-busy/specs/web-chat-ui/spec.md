# web-chat-ui Delta

## MODIFIED Requirements

### Requirement: 产物必须可在页面上传与下载且凭据不进 URL

前端 MUST 提供文件上传入口（表格/文档/图片，走既有上传通道），上传成功
MUST 可将其引用随消息发送。上传通道 MUST 按文件扩展名自动匹配（xlsx/xls/
xlsm→建档表格、图片→截图（OCR）、其余→文档），默认通道 MUST 为文档。
上传期间前端 MUST 禁用上传按钮并显示忙碌提示，MUST NOT 重复提交同一文件；
上传结束后 MUST 恢复按钮，失败时 MUST 保留文件选择以便重试。事件流出现
`upload_text` 事件时 MUST 展示文本提取结果或显式告警。事件流出现 artifact
事件时，前端 MUST 提供该产物的下载入口；下载 MUST 经请求头或一次性票据由
后端代理取回，URL MUST NOT 携带会话凭据或一次性票据原文。

#### Scenario: 上传驱动建档

- **WHEN** 用户上传已填建档表格并要求执行
- **THEN** 文件进入会话工作区，流程使用其内容

#### Scenario: PDF 自动走文档通道

- **WHEN** 用户选择 PDF 文件
- **THEN** 上传通道自动切换为「文档」，不会误走建档表格通道

#### Scenario: 上传期间防重复

- **WHEN** 上传请求尚未返回
- **THEN** 上传按钮禁用并显示“上传中…”，再次点击不产生重复请求

#### Scenario: 后台文本提取结果可见

- **WHEN** 事件流出现 `upload_text`
- **THEN** 页面显示已提取的文本路径与字数，或显示提取失败告警

#### Scenario: 产物下载不暴露凭据

- **WHEN** 用户点击产物下载
- **THEN** 下载成功，浏览器地址与历史记录中不出现凭据
