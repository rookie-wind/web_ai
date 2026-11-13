## MODIFIED Requirements

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
