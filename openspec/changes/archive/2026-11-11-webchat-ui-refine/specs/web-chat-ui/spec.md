## RENAMED Requirements

- FROM: `### Requirement: 移动端必须全视口沉浸并按浏览器能力全屏`
- TO: `### Requirement: 移动端必须全视口沉浸布局`

## MODIFIED Requirements

### Requirement: 移动端必须全视口沉浸布局

移动端页面 MUST 采用全视口 app-like 布局（动态视口高度 `100dvh`、composer 吸底、
消息区独立滚动、适配 safe-area 安全区）。登录 MUST NOT 自动请求全屏——原生文件
picker 会强制退出全屏，自动全屏与上传冲突且体验跳动；沉浸感 MUST 由全视口布局
提供，MUST NOT 依赖 PWA/加主屏幕/HTTPS，MUST NOT 按操作系统硬分支。

#### Scenario: 全视口布局

- **WHEN** 用户在手机浏览器打开页面
- **THEN** 页面占满动态视口，composer 吸底、消息区滚动，无多余留白

#### Scenario: 能力检测全屏

- **WHEN** 用户点击登录
- **THEN** MUST NOT 自动请求全屏，保持全视口布局（避免后续文件 picker 退出全屏的跳动）

#### Scenario: 不支持降级

- **WHEN** 浏览器不支持全屏 API
- **THEN** 页面仍以全视口布局占满，无报错、不依赖全屏

### Requirement: 前端必须可在移动浏览器正常使用

页面 MUST 采用响应式布局，主流移动浏览器 MUST 可完成登录、对话、确认与下载全流程；
确认卡片在移动端 MUST 完整展示参数摘要且按钮可触达。移动端表单控件（composer 文本
输入、模型选择、确认卡输入）MUST 使用不小于 16px 的字号，避免 iOS Safari 聚焦时
自动放大页面；MUST NOT 以 `maximum-scale=1` 禁用用户缩放。模型选择控件 MUST 有
占位 option，未开会话时 MUST NOT 仅余空箭头。

#### Scenario: 手机完成确认闭环

- **WHEN** 用户在手机浏览器收到写入确认卡片
- **THEN** 可阅读完整摘要并完成确认或拒绝

#### Scenario: 聚焦不放大页面

- **WHEN** 用户在 iPhone 聚焦 composer 文本输入或模型选择
- **THEN** 页面不被自动放大，顶栏保持可见，无需手动捏合缩小

### Requirement: 产物必须可在页面上传与下载且凭据不进 URL

前端 MUST 经一体化 composer 的［＋］控件选择文件并**先暂存为 chip（不立即上传、
不解析）**，发送消息时 MUST 才上传暂存文件并将其引用随消息发送。上传通道 MUST 按
文件扩展名自动匹配（xlsx/xls/xlsm→建档表格、图片→截图（OCR）、其余→文档），默认
通道 MUST 为文档，MUST NOT 提供手动通道下拉。上传期间前端 MUST 禁用［＋］加文件
控件并显示忙碌提示，MUST NOT 重复提交同一文件；上传结束后 MUST 恢复控件，失败时
MUST 提示错误，暂存 chip 保留以便重试或移除。事件流出现 `upload_text` 事件时 MUST
展示文本提取结果或显式告警。事件流出现 artifact 事件时，前端 MUST 提供该产物的下载
入口；下载 MUST 经请求头或一次性票据由后端代理取回，URL MUST NOT 携带会话凭据或
一次性票据原文。

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

### Requirement: 输入区必须为一体化 composer 且附件可删除

前端输入区 MUST 为单一 composer 卡片，含附件 chip 行、自适应增高的文本输入与底部
工具栏（［＋］加文件、模型选择、发送/停止切换按钮）。已附加文件 MUST 以 chip 呈现
（文件名/缩略），每个 chip MUST 提供始终可见的 ✕ 删除入口（文件名截断 MUST NOT
裁剪 ✕），发送前 MUST 可逐个移除已暂存附件（移除发生在上传之前）。工具栏 MUST 保留
可选路由前缀提示，MUST NOT 强制前缀。

#### Scenario: 加文件呈现 chip

- **WHEN** 用户经［＋］附加一个文件
- **THEN** 附件行出现该文件 chip（文件名/缩略 + ✕ 删除入口），文件尚未上传解析

#### Scenario: 删除附件 chip

- **WHEN** 用户点击某附件 chip 的 ✕
- **THEN** 该附件从待发送列表移除、chip 消失，其余附件保留

#### Scenario: 多附件独立删除

- **WHEN** 用户附加多个文件后删除其一
- **THEN** 仅被删 chip 消失，其余附件仍可随消息发送

### Requirement: 执行中必须提供停止入口

前端 MUST 将发送与停止合一为切换按钮：空闲态为「发送」；轮次执行期间 MUST 变为
停止态（转圈/停止图标），点击后 MUST 经二次确认再调用 `POST /api/sessions/{id}/abort`。
`turn_done`、`turn_aborted` 或 `session_closed` 事件到达后 MUST 恢复发送态；页面
重新载入时 MUST 依据会话列表的 `turn_running` 恢复按钮状态。中止后 MUST 展示
“已完成的写入不会回滚”。

#### Scenario: 停止按钮可见

- **WHEN** 消息发送成功且轮次正在执行
- **THEN** 发送按钮变为停止态（转圈/停止图标），直到本轮结束或中止

#### Scenario: 重载后恢复

- **WHEN** 用户刷新页面且服务端仍有执行中的轮次
- **THEN** 按钮按 `turn_running` 恢复为停止态

#### Scenario: 中止后的提示

- **WHEN** 收到 `turn_aborted`
- **THEN** 页面显示“任务已中止；已完成的写入不会回滚”，按钮恢复发送态并允许继续输入