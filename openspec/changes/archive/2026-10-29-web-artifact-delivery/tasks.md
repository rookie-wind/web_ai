## 1. 配置与依赖（地基）

- [x] 1.1 `webchat/requirements.txt` 新增 `python-multipart`（上传）与
  `rapidocr-onnxruntime`（OCR，拉入 onnxruntime），隔离在 webchat venv；验证
  `webchat\.venv\Scripts\pip install -r requirements.txt` 成功、`python -c "import
  python_multipart"`（python-multipart 新版导入名，钉版本避免已弃用的 `multipart`）
  与 `import rapidocr_onnxruntime` 均可导入，且 mcp_server venv 不受影响。
- [x] 1.2 `config.py` 新增上传上限（表格/图片 10 MB、文档 20 MB）、保留天数
  （input/result/template 30、sensitive_temp 7）、OCR provider 选择/开关、下载 grant
  TTL 及对应 `WEBCHAT_*` 环境变量，沿用 `load_settings` 解析/校验范式；验证新增配置
  默认值断言 + 非法值抛 `SettingsError` 的 pytest 通过。

## 2. 三通道上传落点分道

- [x] 2.1 新增上传路由（`webchat/artifacts.py`，`api.py` 挂载），以 `channel` 分道，
  用 `UploadFile` 流式落盘、按通道施加上限、超限返回 413；文本通道复用既有
  `send_message` 不新增端点；验证路由注册 + 超限拒绝（413）的 pytest 通过。
- [x] 2.2 `archive_table` 通道：代理转发 mcp_server `/api/archive/uploads`（带会话
  mcp_token），返回 file_id，**不落会话工作区**；验证 pytest（用 fake/stub mcp_server）
  断言返回 file_id 且工作区无该表格副本。
- [x] 2.3 `document` 通道：协议文档落 `workspace/xlpa-input/`（input 分类），运行时可
  读取；验证 pytest 断言文件落位正确目录、分类为 input、可读。
- [x] 2.4 会话删除端点（DELETE，区别于 close）：用户主动删除会话 → 立即物理删除
  工作区与全部产物（temp/input/result/template 一并清），校验会话归属；验证 pytest
  断言删除后工作区不存在、后续下载一律 404、越权删除被拒。

## 3. 本地 OCR（可插拔 provider）

- [x] 3.1 定义 `OCRProvider` 协议（`recognize(image_bytes) -> OcrResult{text,
  structure_ok, confidence}`）+ 默认 `RapidOcrProvider`（懒加载，不在 create_app 时
  加载模型）；验证 provider 单测（stub 图片返回文本；懒加载：未调用不加载模型）。
- [x] 3.2 `screenshot` 通道接入 OCR：截图→文本落会话工作区，事件流给出识别结果/质量
  提示；验证 pytest 断言 OCR 文本落位、运行时可读取该文本。
- [x] 3.3 OCR 失败/行列无法保留（`structure_ok=False`）→ 显式报错（4xx + 提示），
  **不静默以猜测内容继续**；OCR 依赖缺失/加载失败 → 截图通道降级提示"OCR 不可用"，
  不崩溃主服务、不影响其他通道；验证 pytest 覆盖失败显式提示与依赖缺失降级两条路径。
- [x] 3.4 V8' OCR 质量基线：三张样图 + 一份电子表格对照，记录识别质量证据到
  `validation/web-artifact-delivery/`；验证证据文件落盘、结论可复核（达标/不达标及
  是否需换引擎）。

## 4. 一次性下载 grant + 产物事件 + 代理下载

- [x] 4.1 新增 `DownloadGrantStore`（`mint(session_id, artifact_id) -> token`、
  `consume` 原子校验并删除、短 TTL 兜底），语义为消费即作废（区别于 C4 可复用
  GrantStore）；验证 pytest：消费即作废、重放被拒、并发消费仅一次成功、跨会话 grant
  无效。
- [x] 4.2 artifact 事件与产物检测：**先给 `events.py` 的 `EVENT_TYPES` 封闭元组加
  `artifact`（照抄 C4 加 `gate_blocked` 先例，否则事件被当 unknown 透传）**；
  `runtime.run_message` turn 收尾扫描 `workspace/xlpa-output/` 新增文件（一期仅来源 A），
  登记 (artifact_id → 来源) 并 `events.append(..., "artifact", {...})`（**不含凭据、
  不含一次性 grant**）；验证 pytest 断言 `artifact` 在 EVENT_TYPES、产出 artifact 事件、
  payload 无凭据/grant、幂等（重复扫描不重复登记）。
- [x] 4.3 按需铸造端点 `POST /api/sessions/{id}/artifacts/{aid}/grant`：校验会话归属后
  mint 一次性 grant、经响应体返回（**不入 artifact 事件**）；验证 pytest：铸造成功、
  grant 不出现在任何事件 payload、非本会话铸造被拒。
- [x] 4.4 产物代理下载端点（一期仅来源 A：工作区 `xlpa-output/`；来源 B mcp_server
  回源保留端点形态、二期接白名单/显式登记）：先校验会话票据 + 归属 + artifact_id
  **命中服务端产物登记表**（白名单，防 `../` 逃逸）+ `consume` 一次性 grant，通过后
  流式转发；grant 经请求头（如 `X-Artifact-Grant`）传递；验证 pytest：合法下载成功、
  grant 消费后重放被拒、跨会话/越权下载被拒（404/403）、**artifact_id 含 `../` 或
  未命中登记表被拒（traversal 测试）**、下载 URL 不含凭据/owner/grant。
- [x] 4.5 来源 B（mcp_server 原生模板/报告）自动检测一期不实现（降级二期）；验证
  design/spec 一致声明一期仅来源 A，下载端点保留可扩展形态、不承诺来源 B 自动检测。

## 5. 保留期清理接入

- [x] 5.1 保留期清理（沿用 cleanup.py 分类语义，不 import mcp_server）：`xlpa-tmp/`=temp
  会话销毁即清（接入 `runtime.close()`）、result/template 30 天、input 30 天、
  sensitive_temp 7 天、audit 不清、未知分类一律保留、用户主动删除会话立即物理删除；
  验证 pytest 覆盖各分类处置与"未知分类保留"。
- [x] 5.2 TTL 清理后台任务（按目录 mtime + 分类，webchat 自有轻量任务，避免跨包耦合）；
  验证 pytest（注入 now_fn）断言过期产物被清、未过期保留、audit 不受影响。

## 6. 回归与证据

- [x] 6.1 端到端 pytest：上传（表格/文档/截图三通道）→ 产物 → 代理下载全链路，断言
  凭据不进 URL、一次性 grant 生效、三通道落点正确；验证该端到端测试通过。
- [x] 6.2 webchat pytest 全绿 + 主 pytest 基线全绿；验证 `webchat\.venv\Scripts\pytest`
  与主 `pytest` 均全绿（记录通过数）。
- [x] 6.3 mcp_server 零改动核验 + IDE 回归人工验证：确认本变更未改 mcp_server 代码
  （沿用 cn-sdk-migration 修正后的核验方法：本变更编辑文件无一在 mcp_server/ 下，
  webchat 未纳入 git 跟踪），IDE `/mcp` 与接入页行为不变；验证结论记入
  `validation/web-artifact-delivery/evidence-index.md`。
- [x] 6.4 冒烟实测 user 级会话 token 对 mcp_server `/api/archive/uploads` 的上传权限
  （cn-sdk 经验：admin token 曾 401、token 分级敏感）；验证 user 级 token 上传放行与否
  结论记入 evidence-index.md；若不足则在 evidence 标注并与 mint 端协调（不改 mcp_server）。
