## Context

动机见 proposal.md - Why。此处只记录塑形方案的现状与约束：

- **会话工作区布局已就绪**：`runtime.create()` 已建 `workspaces_dir/<session_id>/`
  下的 `xlpa-tmp/` 与 `xlpa-output/`；agent 的 `cwd=workspace`，产物天然落
  `xlpa-output/`（C3 已交付）。
- **事件设施已就绪**：`EventStore.append(session_id, type, payload)` 按会话分区
  JSONL、seq 单调、支持 `Last-Event-ID` 重放；`artifact` 事件复用此设施即可。
- **门禁票据范式可参照但语义不同**：C4 `grants.py` 的 `GrantStore` 是 (session_id,
  target) 的 **TTL 窗口内可复用**票据（覆盖分批续跑）；C5 产物下载要的是
  **一次性（消费即作废）**票据，语义相反，不能直接复用。
- **mcp_server 既有通道**：`/api/archive/uploads`（Bearer 鉴权、分块、
  `snapshot_store.upload_max_bytes` 上限、换取 file_id）、`/api/archive/templates/<id>`
  （file_id 即票据、URL 带 owner 摘要）；webchat 代理可复用其鉴权范式，但**不改**
  mcp_server（公网门控延至 C7）。
- **保留期分类已定义**：`mcp_server/cleanup.py` 有 `ARTIFACT_KEEP/DELETE_CATEGORIES`
  与 `should_delete_artifact`；`snapshot_store/task_report_store` 的
  `DEFAULT_TTL_DAYS=30`、`operation_log_store=7`。webchat 不 import mcp_server
  （包边界纪律），沿用语义而非代码。
- **环境约束**：OCR 重依赖 MUST 隔离在 webchat venv，不污染 mcp_server；一期
  内网部署，CN-SDK 部署契约见 requirements §7.3。

## Goals / Non-Goals

**Goals:**
- 三通道上传落点分道（文本/表格/文档/截图），表格经代理换 file_id 不进工作区。
- 本地 OCR 可插拔 provider（默认 RapidOCR），失败显式提示、不静默猜测。
- 产物后端代理下载 + 一次性 grant，凭据/grant 只经请求头、绝不入 URL。
- `artifact` 事件驱动前端下载入口；保留期按 cleanup 分类接入清理。
- mcp_server 零改动；webchat pytest 全绿 + 主基线全绿。

**Non-Goals:**
- 前端页面/下载 UI（C7）；本变更只交付后端 API 与事件契约。
- 照片（拍照）OCR 通道（推后，provider 预留接口）。
- mcp_server 既有端点公网门控（延至 C7）。
- 转换执行类工具与沙箱（C6）。

## Decisions

### D1 上传路由与三通道分道
新增上传端点（倾向独立 `artifacts.py` 路由，`api.py` 挂载），以 `channel` 区分：
`text`（直接进消息，复用 `send_message`）、`archive_table`（代理转发 mcp_server
`/api/archive/uploads`，带会话 mcp_token，返回 file_id，**不落工作区**）、
`document`（落 `workspace/xlpa-input/`，input 分类）、`screenshot`（先 OCR→文本落
工作区）。用 `UploadFile` + python-multipart，按通道施加上限（见 D6），流式落盘防
内存耗尽。**备选**：单一 `/uploads` + 类型自动嗅探——否决，通道语义与落点差异大，
显式 channel 更可控、上限更好施。

### D2 OCR 可插拔 provider + 懒加载 + 显式失败
定义 `OCRProvider` 协议（`recognize(image_bytes) -> OcrResult{text, structure_ok,
confidence}`）；默认 `RapidOcrProvider`（rapidocr-onnxruntime，离线 CPU）。模型
**首次使用懒加载**（不在 create_app 时加载，避免拖慢启动/无谓占内存）。识别失败或
`structure_ok=False`（行列无法保留）→ 抛显式错误，上传端点转 4xx + 提示，**不静默
以猜测内容继续**。OCR 依赖缺失/加载失败 → 截图通道返回"OCR 不可用，请改用文本/表格"，
**不崩溃整个服务**（其他通道不受影响）。provider 可经配置切换，为二期照片通道与
V8' 质量不达标时的引擎替换预留。**备选**：直接内联 RapidOCR 调用——否决，D10 明确
要求可插拔。

### D3 一次性下载 grant（独立存储，区别于 C4）
新增 `DownloadGrantStore`（与 `grants.py` 并列，或 `grants.py` 内新增类）：
`mint(session_id, artifact_id) -> token`（`secrets.token_urlsafe`）、
`consume(token, session_id, artifact_id) -> bool`（**原子校验并删除**，重放即 False）、
短 TTL 兜底未用 grant。绑定 (session_id, artifact_id)，服务端持有事实，经**请求头**
（如 `X-Artifact-Grant`）传递。**为何不复用 C4 GrantStore**：C4 是 TTL 窗口内可复用
（覆盖分批续跑），C5 要消费即作废，语义相反。**备选**：复用 GrantStore 加一次性
标志——否决，两种生命周期混在一处易误用。
**签发流程（补齐）**：新增按需铸造端点 `POST /api/sessions/{id}/artifacts/{aid}/grant`
（校验会话归属后 mint、grant 经响应体返回）；grant **不入 artifact 事件 payload**
（否则历史重放会产出已消费的死票据），前端要下载时先调铸造端点取 grant、再以
请求头携带下载。

### D4 产物代理下载 + 双来源
下载端点 `GET /api/sessions/{id}/artifacts/{artifact_id}/download`：先 `_require_user`
校验会话票据 + 归属，再 `consume` 一次性 grant，通过后按来源回源：
- **来源 A（会话工作区）**：`xlpa-output/<artifact_id>` → `FileResponse`/
  `StreamingResponse` 直接服务。
- **来源 B（mcp_server 产物）**：模板/任务报告等 → webchat 后端用**会话 mcp_token**
  （请求头 Authorization）代理 GET mcp_server 既有端点，流式转发给用户；**用户侧
  URL 不含凭据/owner**（凭据在后端回源请求头里）。
维护 artifact_id → 来源（工作区路径 or mcp_server 端点）的映射（产物登记，见 D5）。
**一期范围**：先只服务来源 A（会话工作区产物）；来源 B（mcp_server 原生模板/报告）
代理下载保留端点形态、二期接白名单/显式登记再接（见 D5）。
**路径安全**：下载 MUST 先校验 artifact_id 命中服务端产物登记表才放行——artifact_id
是客户端可控输入，MUST NOT 直接拼接 `xlpa-output/<artifact_id>`，登记表白名单天然
消除 `../` 逃逸。
**备选**：让用户直连 mcp_server 下载——否决，正是 D9 要消除的 URL 带凭据问题。

### D5 artifact 事件与产物检测
一轮消息执行后（`runtime.run_message` 的 turn 收尾），扫描 `workspace/xlpa-output/`
新增文件，对每个新产物：登记 (artifact_id → 来源) + `events.append(session_id,
"artifact", {artifact_id, name, size, ...})`（**不含凭据、不含一次性 grant**）。
前端（C7）据事件渲染下载入口。
**一期只检测来源 A（工作区扫描）**：agent 把报告/转换配置/OCR 文本写进
`xlpa-output/` 即被检测，覆盖 AC-1/AC-2 的产物下载。来源 B（mcp_server 原生
模板/任务报告）的自动检测一期**不做**、降级二期（届时按白名单工具/显式登记
实现）；此前不承诺“经 MCP 工具取得产物引用”的自动检测（spec 场景已相应收窄）。
**备选**：由 agent 经 MCP 工具显式上报产物——一期不依赖工具面改动，用
工作区扫描更简单可靠；若后续 SDK 提供产物信号可切换（见 Open Questions）。

### D6 保留期清理接入
webchat 侧保留清理**沿用 cleanup.py 分类语义**（不 import mcp_server）：会话工作区
`xlpa-tmp/`=temp（会话销毁即清，接入 `runtime.close()`）、`xlpa-output/`产物与模板=
result/template（30 天）、代理落地的建档 Excel 副本=sensitive_temp（任务终态后 7 天，
**注**：D10 表格不落工作区，此项针对确需落地的敏感副本，若无则不适用）、
`xlpa-input/`文档与 OCR 文本=input（30 天）；audit 不清；未知分类一律保留。
**可重下载限会话存活期**：`runtime.close()` 撤销 mcp_token（C3“会话结束凭据立即
撤销”），来源 B 回源随之失效，故重下载仅在会话存活期/进程内成立；30 天保留期是
**数据持久化**承诺（文件留存供审计/重建），非跨关闭/重启的可重下载承诺——一期
接受此收窄（V9“续跑限服务未重启”同源），持久化产物登记 + 跨重启归属推后。
**用户主动删除会话**：新增 delete 端点，立即物理删除工作区与产物（区别于 close：
close 只撤凭据/终止实例、文件按保留期留存）。TTL 清理经后台扫描（按目录 mtime +
分类）或复用 mcp_server 清理触发点，倾向 webchat 自有轻量后台任务，避免跨包耦合。

### D7 配置与依赖
`config.py` 新增：上传上限（表格/图片 10 MB、文档 20 MB）、保留天数（input/result/
template 30、sensitive_temp 7）、OCR provider 选择/开关、下载 grant TTL；对应
`WEBCHAT_*` 环境变量，沿用 `load_settings` 解析与校验范式。`events.py` 的
`EVENT_TYPES` 封闭元组加 `artifact`（照抄 C4 加 gate_blocked 先例）。`requirements.txt`
新增 `python-multipart`（上传；新版导入名为 `python_multipart`，验证/钉版本须据此，
勿用已弃用的 `import multipart`）、`rapidocr-onnxruntime`（OCR，拉入 onnxruntime），
隔离在 webchat venv。

### D8 mcp_server 零改动 / 公网门控延 C7
本变更不改 mcp_server 任何代码；复用既有 `/api/archive/uploads`（上传代理）与
`/api/archive/templates/<id>`（下载回源）。既有把凭据放 URL 的端点的**公网门控延至
C7**公网前置清单，一期（内网）保持既有行为，避免本期碰 mcp_server（与 C3/C4 一致）。

## Risks / Trade-offs

- [OCR 质量不达标（V8'）] → provider 可插拔，V8' 用三样图 + 一表格对照留证；不达标
  经 provider 换引擎，不动上层；识别失败一律显式提示不静默猜测。
- [onnxruntime/rapidocr 在 Windows 安装或体积问题] → 隔离在 webchat venv；OCR 懒加载
  且加载失败降级（截图通道提示不可用，不影响文本/表格/文档通道与主服务）。
- [一次性 grant 并发消费竞态] → `consume` 加锁原子校验并删除；重放/并发只有一次成功。
- [产物检测漏报/误报（工作区扫描）] → 以 turn 收尾扫描 `xlpa-output/` 增量为准，
  登记 artifact_id 幂等；漏报可经历史回看补，误报以文件存在性兜底。
- [大文件上传内存耗尽] → 流式落盘 + 按通道上限（对齐 snapshot_store 分块上限），
  超限即拒（413）。
- [user 级会话 token 对 `/api/archive/uploads` 的上传权限未实测] → 冒烟（tasks 6.4）
  实测 user 级 token 上传是否放行（cn-sdk 经验：admin token 曾 401、token 分级敏感）；
  若不足与 mint 端协调，但本变更保持 mcp_server 零改动。
- [跨会话/越权下载] → 下载先校验会话票据 + 归属，grant 绑定 (session_id,
  artifact_id)，来源 B 回源用会话自身 mcp_token，不泄漏他人产物存在性。

## Migration Plan

1. **部署**：webchat venv `pip install -r requirements.txt`（新增 python-multipart、
   rapidocr-onnxruntime）；配置 `WEBCHAT_*` 上传上限/保留天数/OCR 开关。mcp_server
   无需改动或重启。
2. **灰度顺序**：先上三通道上传（文本/表格/文档）→ 截图 OCR → 产物代理下载 +
   一次性 grant → artifact 事件 → 保留期清理，各步独立 pytest 留证。
3. **回滚**：本变更全为 webchat 新增（上传/下载路由、OCR、grant、清理事件），不破坏
   既有端点；回滚即停用新路由，mcp_server 与 IDE 路径零影响。OCR 依赖问题可经配置
   关闭截图通道单独降级。

## Open Questions

- **产物检测机制**：一期用 turn 收尾扫描 `xlpa-output/`；若后续 CN SDK 提供产物就绪
  信号，可切换为事件驱动（不影响 artifact 事件契约与下载流程）。
- **OCR structure_ok 的"行列保留"判定阈值**：V8' 基线给出经验阈值，实现期定，不影响
  provider 接口与"失败显式提示"契约。
- **来源 B 的 artifact_id → mcp_server 端点映射表**：来源 B 检测已降级二期（D5），
  该映射表随二期白名单/显式登记一并补全，不影响一期来源 A 的代理下载与一次性
  grant 契约。
