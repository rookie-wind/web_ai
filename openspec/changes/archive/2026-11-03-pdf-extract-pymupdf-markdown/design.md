## Context

现状（代码已核对）：

- `webchat/webchat/artifacts.py` 的 `extract_pdf_text()` 惰性导入 `pypdf`，
  逐页 `extract_text()` 拼接；`_build_pdf_text_result()` 写
  `xlpa-input/<stem>.pdf.txt` 并组装 `upload_text` 载荷（`text_path` /
  `text_chars` / `warning`）。
- `webchat/webchat/grants.py:563` 读取护栏对 `.pdf` 返回拒绝文案
  `"...请读取自动提取的文本：{resolved.name}.txt"`；`grants.py:580` 用
  `reason.startswith("PDF ")` 判定 `guard="pdf_binary"`。
- `webchat/webchat/sdk_runtime/adapter.py:34` 的 `WEBCHAT_SYSTEM_APPEND`
  告诉 Agent 读取 `<原文件名>.pdf.txt`。
- 前端 `static/js/app.js` 上传回执与 `pdf_binary` 拦截提示各写死一处
  `.pdf.txt`；`tests/test_static_frontend.py` 断言这些字面量。
- 仓库根 `_pdf_to_md.py` 是已验证的 PyMuPDF 抽取参考实现（正文块去表 +
  `find_tables` → GFM + 页锚点），AMC_V3.10 说明书 45 页实测 40 张表、
  寄存器表 0 列错位。
- 依赖声明在 `webchat/requirements.txt`（`pypdf>=5.0,<7.0`）；
  `webchat/.venv` 已安装 PyMuPDF（实测可用）。

约束：上传响应不得被解析阻塞（后台线程池执行）；抽取失败必须显式降级；
`.pdf` 二进制必须继续被护栏拦截；事件契约字段名不变。

## Goals / Non-Goals

**Goals:**

- 表格型 PDF 的旁路产物结构保真，能直接支撑 `modbus-conversion` 类技能。
- 抽取逻辑从临时脚本收敛为包内模块，产物按来源 PDF 物理页可追溯。
- 后缀、提示语、护栏重定向、系统提示、前端文案一处改齐，不留下互相
  矛盾的指引。
- 依赖缺失时上传链路照常工作（仅降级为 `warning`）。

**Non-Goals:**

- 不做扫描件 OCR（仍走既有 `screenshot` 通道），不引入 poppler 等系统级
  二进制依赖。
- 不改造上传/下载/租约/事件契约本身，不改 `document` 通道的目录布局。
- 不为历史会话补生成 `.pdf.md`（历史 `.pdf.txt` 只保留可读性，不迁移）。
- 不处理跨页续表自动拼接（后续独立优化，见 Risks）。

## Decisions

### D1 新增 `webchat/webchat/pdf_extract.py`，`artifacts.py` 只做编排

抽取算法（正文块去表、表格转 GFM、页锚点、单元格清洗）放独立模块，
`artifacts.py` 保留 `extract_pdf_text` 的调用位与载荷组装职责。

- 为什么单列：`artifacts.py` 已 471 行且职责是通道分道/登记/下载；
  表格转换是纯函数，单列便于用固定输入做 golden 测试。
- 备选：直接写在 `artifacts.py` 内 —— 被否，模块会继续膨胀且测试要
  拖起整个上传栈。
- `extract_pdf_text()` 保留为兼容出口（改为 `pdf_extract.py` 的再导出）
  还是删除？→ **删除**，改名 `extract_pdf_markdown()`，调用点仅
  `_build_pdf_text_result()` 一处，无外部使用者（已 grep 确认）。

### D2 产物后缀用 `<stem>.pdf.md`，不用 `<stem>.md`

`stem` 已含原名，保留 `.pdf` 段形成 `协议.pdf.md`：

- 护栏重定向可直接拼 `resolved.name + ".md"`，无需额外解析；
- 与历史 `.pdf.txt` 天然区分，不会覆盖旧旁路文件；
- 与 `_pdf_to_md.py` 脚本行为一致（脚本用 `with_suffix(".md")`，正式
  实现改为附加式以对齐护栏拼接）。

### D3 护栏重定向按磁盘实况选择后缀

`grants.py` 的 `.pdf` 分支改为：同目录存在 `<name>.pdf.md` 提示它；
否则存在 `<name>.pdf.txt` 提示它（兼容历史会话）；两者都不存在提示
`<name>.pdf.md` 并说明"可能尚未完成或已失败"。

- 为什么：固定提示 `.md` 会让 Agent 去读不存在的路径并反复重试；
  历史工作区只有 `.txt`。
- 备选：只提示 `.md` —— 被否（旧会话失效）；只提示 `.txt` —— 被否
  （与新产物矛盾）。
- `guard="pdf_binary"` 判定依赖 `reason.startswith("PDF ")`，重写文案时
  MUST 保留该前缀，否则前端拦截聚合失效。

### D4 表格与正文互斥去重沿用参考实现

`find_tables()` 后取 `get_text("blocks")`，块中心落在任一表格 bbox 内
的块跳过；表格按 `extract()` 二维数组转 GFM，单元格 `re.sub(r"\s+", " ")`
并转义 `|`；首行命中表头关键词（地址/名称/类型/偏移/R/W 等）当表头，
否则生成 `列N` 占位表头。已知局限：续页表格会退化为占位表头（见 Risks）。

### D5 依赖替换：`pypdf` → `PyMuPDF`

`webchat/requirements.txt` 直接替换（`pypdf` 仅被 PDF 提取使用）。
仍保持**惰性导入** + `ImportError` → `warning` 的既有降级路径，导入名
固定 `import pymupdf`（新版官方名），不改写为 `fitz` 回退以免双路径。

### D6 `text_chars` 语义不变，按 Markdown 字符数计

事件字段与类型不变（前端/测试无需改结构），仅内容从纯文本变为 MD。
空判定改为"正文与表格皆空"才算无文本层：纯扫描表格 PDF 的
`get_text()` 为空但可能有表格，避免误报扫描件。

### D7 测试样本：程序生成带框线表格 PDF

现有测试夹具只有文本 PDF。新增用例需要一个**含框线表格**的 PDF，
方案是在测试里用 PyMuPDF 画线 + 写单元格文字生成（几十行内、无需二进制
资产、与实现同源但不断言列对齐算法本身）。另加一条可选的真实样本
golden 测试：仓库内 AMC PDF 路径存在时校验寄存器表列数与若干已知行，
不存在则 `skip`，避免依赖大二进制文件。

### D8 抽取模块另提供页区间入口（实施期细化）

实施时发现：45 页全档 `find_tables()` 扫描约 30-40 秒，真实样本 golden
测试若跑全档会把单测套件拖到分钟级。故 `pdf_extract.py` 除
`extract_pdf_markdown(path)` 外另暴露
`extract_pdf_pages_markdown(path, first_page, last_page)`（1-based
闭区间，锚点仍用真实物理页码），`extract_pdf_markdown` 退化为它的
全档封装。上传链路仍调全档入口，页区间入口只供测试与后续
"只重抽某几页"类需求使用。

实测同时确证：PyMuPDF 2.0 与 1.28.x 在本模块用到的 API（`open` /
`find_tables` / `extract` / `get_text("blocks")` / `Matrix`）完全兼容，
`requirements.txt` 钉 `<2.0` 是为了锁定已目视校验过的 1.28.x 行为，
不是为了规避 API 破坏。

## Risks / Trade-offs

- [无框线表格（纯文字对齐/无线框）不被 `find_tables` 识别，退化为正文]
  → 如实降级为文本块输出，不伪造表结构；需要时在 `document` 通道外
  人工补表，后续可考虑基于列坐标的启发式补强。
- [跨页续表被拆成多张表，续页丢表头 → 占位表头 `列1..列N`]
  → 先保留页锚点保证可追溯；续页继承表头作为后续独立小变更。
- [PyMuPDF  wheel 体积（约数十 MB）与许可（AGPL）]
  → 内网部署、不分发外部；体积换表结构保真是明确取舍。
- [`find_tables` 逐页扫描在大 PDF 上更慢（45 页秒级）]
  → 已在后台线程执行且响应先行返回 `pending`，不影响上传体验；
    如后续超长手册变慢，可加页数上限 + 截断告警。
- [损坏 PDF 的异常类型与 `pypdf` 不同]
  → 捕获宽口径 `Exception` 转 `warning`（沿用现有写法），测试断言
    "原文件保留 + 无 MD 文件 + 载荷含 warning" 而非具体异常类型。
- [历史会话只有 `.pdf.txt`，系统提示统一讲 `.md`]
  → 由 D3 的按磁盘实况重定向兜底；系统提示措辞改为"同目录
    `<原文件名>.pdf.md`（历史会话可能为 `.pdf.txt`）"。

## Migration Plan

1. 新增 `pdf_extract.py` + 依赖替换，改 `artifacts.py` 落地 `.pdf.md`；
   同步 `grants.py`、`adapter.py`、`app.js` 文案。
2. 更新既有测试断言（`.pdf.txt` → `.pdf.md`）并新增表格保真用例；
   `pytest` 全绿后重启 webchat（后端改动需重启，静态文件仅需硬刷新）。
3. 上传真实 AMC 说明书做端到端验证：`upload_text` 指向 `.pdf.md`，
   文件内寄存器表列对齐，Agent 能直接 Read 到点表。
4. 回滚：改回 `extract_pdf_*` 实现与四处文案即可，无数据迁移；
   历史 `.pdf.txt` 未被删除，回滚后重定向逻辑仍可用。
