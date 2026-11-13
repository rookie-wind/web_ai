## ADDED Requirements

### Requirement: 输入区必须为一体化 composer 且附件可删除

前端输入区 MUST 为单一 composer 卡片，含附件 chip 行、自适应增高的文本输入与
底部工具栏（［＋］加文件、模型选择、中止、发送）。已附加文件 MUST 以 chip 呈现
（文件名/缩略），每个 chip MUST 提供 ✕ 删除入口，发送前 MUST 可逐个移除已附加
文件。工具栏 MUST 保留可选路由前缀提示，MUST NOT 强制前缀。

#### Scenario: 加文件呈现 chip

- **WHEN** 用户经［＋］附加一个文件
- **THEN** 附件行出现该文件 chip（文件名/缩略 + ✕ 删除入口）

#### Scenario: 删除附件 chip

- **WHEN** 用户点击某附件 chip 的 ✕
- **THEN** 该附件从待发送列表移除、chip 消失，其余附件保留

#### Scenario: 多附件独立删除

- **WHEN** 用户附加多个文件后删除其一
- **THEN** 仅被删 chip 消失，其余附件仍可随消息发送

### Requirement: 移动端必须全视口沉浸并按浏览器能力全屏

移动端页面 MUST 采用全视口 app-like 布局（动态视口高度 `100dvh`、composer 吸底、
消息区独立滚动、适配 safe-area 安全区）。登录用户手势 MUST 按
`document.fullscreenEnabled` 能力检测尝试 `requestFullscreen()` 进入沉浸全屏；
浏览器不支持时 MUST 优雅降级为全视口布局占满，MUST NOT 按操作系统硬分支，
MUST NOT 依赖 PWA/加主屏幕/HTTPS。

#### Scenario: 全视口布局

- **WHEN** 用户在手机浏览器打开页面
- **THEN** 页面占满动态视口，composer 吸底、消息区滚动，无多余留白

#### Scenario: 能力检测全屏

- **WHEN** 浏览器支持全屏且用户点击登录
- **THEN** 尝试 `requestFullscreen()` 隐藏浏览器 chrome 进入沉浸全屏

#### Scenario: 不支持降级

- **WHEN** 浏览器不支持全屏（如 iPhone Safari）且用户登录
- **THEN** 不报错，降级为全视口布局占满

## MODIFIED Requirements

### Requirement: 产物必须可在页面上传与下载且凭据不进 URL

前端 MUST 经一体化 composer 的［＋］控件提供文件上传入口（表格/文档/图片），
上传成功 MUST 可将其引用随消息发送。上传通道 MUST 按文件扩展名自动匹配
（xlsx/xls/xlsm→建档表格、图片→截图（OCR）、其余→文档），默认通道 MUST 为
文档，MUST NOT 提供手动通道下拉。上传期间前端 MUST 禁用［＋］加文件控件并显示
忙碌提示，MUST NOT 重复提交同一文件；上传结束后 MUST 恢复控件，失败时 MUST 提示
错误，用户可经［＋］重新选择重试。事件流出现 `upload_text` 事件时 MUST 展示文本提取结果或显式
告警。事件流出现 artifact 事件时，前端 MUST 提供该产物的下载入口；下载 MUST 经
请求头或一次性票据由后端代理取回，URL MUST NOT 携带会话凭据或一次性票据原文。

#### Scenario: 上传驱动建档

- **WHEN** 用户上传已填建档表格并要求执行
- **THEN** 文件进入会话工作区，流程使用其内容

#### Scenario: PDF 自动走文档通道

- **WHEN** 用户选择 PDF 文件
- **THEN** 上传通道自动切换为「文档」，不会误走建档表格通道

#### Scenario: 上传期间防重复

- **WHEN** 上传请求尚未返回
- **THEN** ［＋］加文件控件禁用并显示“上传中…”，再次点击不产生重复请求

#### Scenario: 后台文本提取结果可见

- **WHEN** 事件流出现 `upload_text`
- **THEN** 页面显示已提取的文本路径与字数，或显示提取失败告警

#### Scenario: 产物下载不暴露凭据

- **WHEN** 用户点击产物下载
- **THEN** 下载成功，浏览器地址与历史记录中不出现凭据