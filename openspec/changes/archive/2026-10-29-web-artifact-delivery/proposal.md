## Why

现状把凭据/归属摘要放进 URL 查询串交付产物（`/api/archive/templates/<id>?owner=`、
`/api/logs?token=`，`_handle_template_download` 注释明确"file_id 本身即为票据"），URL 会被反代日志与
浏览器历史留存，与 FR-6"产物下载不经 URL 明文携带凭据"冲突；且 webchat 侧目前没有
任何上传通道与产物查看/下载入口——用户跑完建档/转换拿不到产物，输入也无法送文档与
截图。C3 已落地会话运行时与工作区布局（`xlpa-output/`）、C4 已落地一次性 grant 门禁
范式，C5 补齐"产物与上传"闭环，是 AC-1/AC-2 端到端验收的前置。

## What Changes

- **三通道输入落点分道（D10）**：文本粘贴 → 直接作为会话消息；已填建档表格 →
  webchat 后端代理转发到 mcp_server 既有 `/api/archive/uploads` 得 file_id（**不复制
  进会话工作区**，保持"只有 MCP 碰建档数据"）；协议文档 → 落会话工作区供运行时读取；
  屏幕截图 → 经本地 OCR 转文本后落工作区。**照片（拍照）通道一期推后**（provider 预留
  接口，二期再接）。
- **本地 OCR 可插拔 provider（D10）**：默认 RapidOCR（onnxruntime，离线、CPU 友好、
  重依赖隔离在 webchat venv，不污染 mcp_server）；识别失败或行列结构无法保留 MUST 显式
  提示，MUST NOT 静默以猜测内容继续；V8' 质量基线（三张样图 + 一份电子表格对照）留证。
- **产物代理下载 + 一次性 grant（D9）**：产物（模板/报告/转换配置等）下载改由 webchat
  后端代理，请求头携带会话凭据 + 一次性 grant（消费即作废，区别于 C4 写门禁的 TTL 窗口
  可复用票据）；下载 URL **MUST NOT** 携带凭据/owner 摘要。grant 由**按需铸造端点**签发
  （响应体返回，MUST NOT 进 artifact 事件 payload，防历史重放出死票据）；下载端点
  MUST 校验 artifact_id 命中服务端产物登记表才放行（防 `../` 路径逃逸）。
- **`artifact` 事件类型**：新增产物就绪事件，前端据此渲染下载入口（D5 事件契约含"产物"）。
- **保留期接入 cleanup.py（D11）**：会话工作区与产物按分类处置——temp 会话销毁即清、
  result/template 30 天、sensitive_temp 任务终态后 7 天、input 30 天、audit 不清；
  未知分类一律保留。**可重下载限会话存活期/进程内**（会话 close 即撤销 mcp_token，
  来源 B 回源失效，与 C3 一致）；30 天保留期是**数据持久化**承诺，非跨关闭/重启的
  可重下载承诺。用户主动删除会话 MUST 立即物理删除工作区与产物（新增 delete 端点，
  区别于 close）。
- **上传大小上限**：表格 10 MB / 图片 10 MB / 文档 20 MB（对齐 snapshot_store 既有分块
  upload_max_bytes 机制）。
- **mcp_server 零改动**：既有把凭据放 URL 的端点的公网门控**延至 C7**公网前置清单；
  一期（内网）保持既有行为。

## Capabilities

### New Capabilities
- `web-artifact-delivery`: webchat 侧产物与上传能力——三通道输入落点分道、本地 OCR
  可插拔 provider、产物后端代理下载 + 一次性 grant、保留期接入 cleanup.py。与既有
  `xlpa-archive-template-delivery`（mcp_server 侧模板交付）是不同能力：本能力在 webchat
  侧代理与治理，不改 mcp_server。

### Modified Capabilities
- `agent-runtime-session`: (1) 事件契约新增 `artifact` 事件类型（产物就绪，前端渲染
  下载入口）；(2) "会话工作区"需求把保留期从"后续 C5 定义"落为按 cleanup.py 分类的
  具体保留表（web-artifact-delivery 拥有保留机制，本能力引用之）。

## Impact

- **webchat 后端（代码）**：新增上传/下载路由（`sessions_api.py` 或新 `artifacts.py`）、
  一次性下载 grant 存储（与 C4 `grants.py` 并列，语义不同：消费即作废）、OCR provider
  模块、产物检测（`xlpa-output/` → artifact 事件）、保留期清理接入；`config.py` 新增
  上传上限/保留天数/OCR 开关等配置；`requirements.txt` 新增 python-multipart（上传）、
  rapidocr-onnxruntime（OCR）等，隔离在 webchat venv。
- **mcp_server**：零改动（公网门控延至 C7）。
- **前端 UI**：不在本变更（C7）；本变更只交付后端 API 与事件契约。
- **照片 OCR 通道**：推后（provider 预留接口）。
- **依赖**：新增 OCR 与上传相关依赖，须隔离在 webchat venv，不污染 mcp_server 环境。
- **测试**：上传→产物→下载端到端 pytest；断言凭据不进 URL；OCR 失败显式提示；保留期
  分类处置；webchat pytest 全绿 + 主 pytest 基线全绿。
