# web-artifact-delivery Specification

## Purpose

定义 webchat 侧"产物与上传"的行为契约：用户输入（文本/文档/图片）分道进入会话、
图片经本地 OCR 转文本、会话产物经后端代理下载并以一次性 grant 授权、工作区与产物
按保留期分类处置。本能力在 webchat 侧代理与治理，MUST NOT 改动 mcp_server；与
mcp_server 侧的 `xlpa-archive-template-delivery`（模板生产与交付）是不同能力。

## Requirements

### Requirement: 输入必须按三通道分道进入会话

用户输入 MUST 支持文本、文档、图片三类，并按数据性质分道处置：文本粘贴 MUST 直接
作为会话消息；已填建档表格 MUST 经 webchat 后端代理转发到 mcp_server 既有上传通道
换取 file_id，MUST NOT 复制进会话工作区（保持"只有 MCP 碰建档数据"）；协议文档
MUST 落会话工作区供运行时读取；图片（截图/照片）MUST 以原扩展名落会话工作区
（input 分类），并经本地 OCR 生成 `<stem>.ocr.txt` 兜底文本——运行时 MUST 能读到
原图（Agent 具备读图能力时可直接读取）且 MUST 能读到 OCR 文本（读图不可用时兜底），
MUST NOT 仅保留 OCR 文本而丢弃原图。拍照（照片）通道与截图共用本分道。上传入口
优先级：文本粘贴 > 电子表格文件 > 屏幕截图 > 拍照。同名文件落盘 MUST 追加序号
后缀避免覆盖。

#### Scenario: 已填建档表格经代理换取 file_id

- **WHEN** 用户上传一份已填建档表格
- **THEN** webchat 后端代理转发到 mcp_server 既有上传通道，返回 file_id
- **THEN** 表格不复制进会话工作区；运行时后续凭 file_id 经 MCP 工具读取

#### Scenario: 协议文档落会话工作区

- **WHEN** 用户上传协议文档（点表/规格说明等）
- **THEN** 文档落会话工作区（input 分类），运行时可直接读取

#### Scenario: 屏幕截图经 OCR 落工作区

- **WHEN** 用户上传一张图片（截图或照片）
- **THEN** 原图按原扩展名落会话工作区（input 分类），并生成 `<stem>.ocr.txt`
  兜底文本；上传响应与消息引用同时给出原图路径与 OCR 文本路径，运行时两者皆可读

#### Scenario: 同名图片不覆盖

- **WHEN** 用户两次上传同名图片
- **THEN** 第二次落盘追加序号后缀，两份原图与各自 OCR 文本均保留

### Requirement: 本地 OCR 必须为可插拔 provider 且失败显式提示

OCR MUST 做成可插拔 provider，默认本地实现（离线可跑、CPU 友好、重依赖隔离在
webchat venv，MUST NOT 污染 mcp_server 环境）；识别失败或行列结构无法保留时
MUST 显式提示（响应载荷含失败原因），MUST NOT 静默以猜测内容继续。OCR 失败或
OCR 依赖缺失 MUST NOT 使上传整体失败：原图 MUST 照常落盘保留，响应 MUST 返回
原图路径与显式告警（不生成空的 OCR 文本文件）。质量基线（V8'：三张样图 + 一份电子
表格对照）MUST 留证。

#### Scenario: 截图识别成功

- **WHEN** 一张清晰屏幕截图经 OCR provider 识别
- **THEN** 原图与识别文本均落会话工作区，上传响应给出两路径与质量信息，运行时
  可读原图或文本继续

#### Scenario: 识别失败显式提示

- **WHEN** 图片模糊、内容无法识别或行列结构无法保留（如微信加密缓存文件改名
  为 jpg）
- **THEN** 上传返回成功且原图保留，响应含显式失败原因告警，不生成 OCR 文本文件，
  MUST NOT 以猜测内容静默继续

#### Scenario: OCR 依赖缺失降级为仅原图

- **WHEN** OCR 引擎未安装或加载失败
- **THEN** 上传返回成功且原图保留，响应含显式告警，其余通道与会话不受影响

### Requirement: 产物下载必须经后端代理且 URL 不携带凭据

产物（模板/报告/转换配置等）下载 MUST 由 webchat 后端代理；下载请求 MUST 经请求头
携带会话凭据 + 一次性 grant；下载 URL MUST NOT 携带凭据或 owner 摘要（防反代日志与
浏览器历史留存）；下载端点 MUST 先校验 artifact_id 命中服务端产物登记表才放行
（artifact_id 为客户端可控输入，MUST NOT 直接拼接路径，防 `../` 路径逃逸），校验
grant 与会话归属后再回源取产物字节流转发。

#### Scenario: 会话内产物代理下载

- **WHEN** 用户在会话内下载一个产物
- **THEN** 请求头携带会话凭据与一次性 grant，后端校验通过后回源取字节流转发
- **THEN** 下载 URL 不含凭据/owner 摘要

#### Scenario: 跨会话下载被拒

- **WHEN** 用户尝试下载不属于自己会话的产物
- **THEN** 后端校验会话归属失败，拒绝（404/403），不泄漏产物存在性

#### Scenario: artifact_id 路径逃逸被拒

- **WHEN** 客户端构造含 `../` 或未命中登记表的 artifact_id 请求下载
- **THEN** 后端以登记表白名单校验，未命中一律拒绝（404），MUST NOT 直接拼接
  工作区路径，杜绝路径逃逸

### Requirement: 产物下载授权必须为一次性 grant

产物下载授权 MUST 为一次性 grant（消费即作废），区别于写入门禁在 TTL 窗口内可复用
的计划域票据；grant MUST 与 (session_id, 产物标识) 绑定、服务端持有；grant MUST 经
请求头传递，MUST NOT 出现在 URL；一次下载消费后 MUST 立即作废，重放 MUST 被拒。
grant MUST 由按需铸造端点在用户请求下载时签发（响应体返回），MUST NOT 预置进
artifact 事件 payload（防历史重放出现已消费的死票据）。

#### Scenario: grant 消费即作废

- **WHEN** 产物就绪后后端铸造一次性下载 grant，用户凭会话凭据 + grant 下载成功
- **THEN** 该 grant 立即作废；再次使用同一 grant 下载被拒

#### Scenario: grant 不经 URL

- **WHEN** 检查产物下载请求
- **THEN** grant 经请求头传递，不出现在 URL 查询串或路径

#### Scenario: 按需铸造 grant

- **WHEN** 前端要下载某产物，调按需铸造端点请求 grant
- **THEN** 后端校验会话归属后铸造一次性 grant 并在响应体返回（不入事件流）；
  前端再以请求头携带该 grant 下载

### Requirement: 会话工作区与产物必须按保留期分类处置

会话工作区与产物 MUST 按 cleanup.py 既有分类语义处置：会话工作区临时内容（temp）
会话销毁即清；产物与模板（result/template）保留 30 天（与既有快照 DEFAULT_TTL_DAYS
对齐）；含凭据的建档 Excel（sensitive_temp）任务终态后保留 7 天；上传的协议文档与
OCR 文本（input）保留 30 天；写操作审计日志（audit）维持现状不清理；未知分类 MUST
一律保留。保留期是**数据持久化**语义（文件留存供审计/重建）；**可重下载限会话
存活期/进程内**——会话 close 即撤销 mcp_token（与 C3“会话结束凭据立即撤销”一致），
来源 B 回源随之失效，一期不做跨关闭/重启的重下载（持久化产物登记与跨重启归属
推后）。用户主动删除会话 MUST 立即物理删除工作区与产物（新增 delete 端点，
区别于 close）。

#### Scenario: 会话销毁清临时内容

- **WHEN** 会话被用户结束或超时回收
- **THEN** 该会话工作区 temp 内容即清；result/template 产物按 30 天保留

#### Scenario: 保留期内文件持久但重下载限会话存活期

- **WHEN** 会话仍存活（未 close、进程未重启）且用户回到该产物
- **THEN** 可重新铸造一次性 grant 再次下载；会话 close 或进程重启后，产物文件按
  保留期留存（供审计/重建），但一期不再提供重下载（mcp_token 已撤销）

#### Scenario: 未知分类一律保留

- **WHEN** 清理流程遇到无法归类的文件
- **THEN** 一律保留，不误删可复用或可审计资产

### Requirement: 用户主动删除会话必须立即物理删除

用户主动删除会话 MUST 立即物理删除该会话工作区与全部产物（temp/input/result/
template 一并清除），区别于 close（close 只撤销凭据/终止实例并按保留期留存文件）；
删除 MUST 校验会话归属，删除后该会话产物 MUST NOT 再可下载。

#### Scenario: 删除会话即物理清除

- **WHEN** 用户对属于自己的会话发起删除
- **THEN** 后端立即物理删除该会话工作区与全部产物，后续下载请求一律 404

### Requirement: 上传必须施加大小上限

上传 MUST 施加大小上限：建档表格 10 MB、屏幕截图/图片 10 MB、协议文档 20 MB
（对齐 mcp_server 既有分块上传上限机制）；超过上限 MUST 明确拒绝并提示，
MUST NOT 静默截断或耗尽缓冲。

#### Scenario: 超限上传被拒

- **WHEN** 用户上传超过对应通道上限的文件
- **THEN** 后端明确拒绝（如 413）并提示上限，不落盘、不耗尽内存缓冲

### Requirement: mcp_server 原生 file_id 产物必须自动交付给前端

对白名单 MCP 工具（`generate_device_archive_template`、
`get_device_archive_template_download`、`save_conversion_config`、`pack_bundle`）
返回的 `file_id`，webchat 后端 MUST 在会话事件循环内立即使用该会话凭据回源
mcp_server 取产物字节，落会话工作区 `xlpa-output/` 并登记产物、产 `artifact`
事件，供前端复用既有一次性 grant 下载流程。`file_id`、owner 摘要与 Token MUST NOT
出现在事件 payload、下载 URL 或浏览器可见位置。同一会话内同一 `file_id` MUST 只
登记一次（重复的工具结果不产生重复下载卡片）。回源失败（非 200、超时或超过大小
上限）MUST 产 `error` 事件显式告知用户，MUST NOT 静默丢弃，且错误文案 MUST NOT
包含回源 URL、owner 摘要或 Token。本能力在 webchat 侧实现，MUST NOT 改动
mcp_server。

#### Scenario: 建档模板生成后可直接下载

- **WHEN** Agent 调用 `generate_device_archive_template` 并返回 `file_id`
- **THEN** 后端立即回源取模板字节落 `xlpa-output/`，前端收到 `artifact` 事件并可
  经按需铸造 grant 下载该模板
- **THEN** 即使 Agent 之后再次生成模板（服务端清理旧快照），已落盘的旧模板仍可下载

#### Scenario: 重复工具结果不重复登记

- **WHEN** Agent 对同一 `file_id` 多次调用下载信息查询工具
- **THEN** 后端只登记一次，事件流不出现重复的下载卡片

#### Scenario: 回源失败显式提示

- **WHEN** 回源请求返回非 200 或超时
- **THEN** 事件流出现 `error` 事件提示产物获取失败，不落半成品文件，
  且事件内容不含 URL/owner/Token

#### Scenario: 白名单外工具不触发回源

- **WHEN** 非白名单工具结果中出现 `file_id` 字段
- **THEN** 后端不回源、不登记产物

### Requirement: 产物必须由显式请求或原生产物产生

系统 MUST NOT 仅因工具结果体积超过某个阈值就自动生成并登记下载产物。产物来源
MUST 限于：Agent 在会话工作区 `xlpa-output/` 显式写入的文件，以及白名单 MCP
工具（`generate_device_archive_template`、`get_device_archive_template_download`、
`save_conversion_config`、`pack_bundle`）返回 `file_id` 的原生产物。用户未要求
生成文档时，MUST NOT 出现额外的下载卡片或落盘文件。

#### Scenario: 大体积工具结果不产生产物

- **WHEN** 一次只读工具调用（如 `list_mcp_tools`）返回超过 8000 字的结果，
  用户并未要求生成文档
- **THEN** 不产生落盘文件，不产 `artifact` 事件，也不出现下载卡片

#### Scenario: 显式写入仍产生产物

- **WHEN** Agent 因用户请求在 `xlpa-output/` 生成文本类文档
- **THEN** turn 收尾扫描登记该文件并产 `artifact` 事件

#### Scenario: 原生产物仍自动交付

- **WHEN** 白名单 MCP 工具返回 `file_id`（如建档模板）
- **THEN** 后端回源落盘并产 `artifact` 事件，用户可直接下载

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
