# Understand-Anything 分析进度（pca-mcp-server）

> 本文件由 `/understand` 执行过程手工记录，供跨会话续跑使用。
> 不属于 Understand-Anything 的产物，Phase 7 清理不会触碰它。

## 当前状态

- 项目根：`e:\codeGIT\pca-mcp-server`
- 数据目录：`.ua/`（`config.json` 已固化 `outputLanguage: zh`、`autoUpdate: false`）
- 基线 commit：`29f7d2292d3b2d2c66627f8ef709eb64835d84e2`
- 插件根：`~\.understand-anything-plugin`（Junction，`packages/core/dist` 已构建）
- pnpm 不在 PATH；需要时用 `corepack pnpm@10 ...`（Program Files 无写权限，`corepack enable` 会 EPERM）

## 范围决定（用户已确认）

- 排除测试目录 `mcp_server/tests/`（图谱只看生产代码）
- `.ua/.understandignore` 另排除：`.qoder/`、`.trae/`、`.ua/`、`openspec/changes/archive/`、
  `agent_assets/skills/*/references/`、全部二进制（xlsx/docx/png…）与运行态产物
- 结果：**109 文件 / 10 批次**，filteredByIgnore=611，complexity=moderate
- 粒度：全量符号级；跨会话分轮跑

## Phase 完成情况

| Phase | 状态 | 产物 |
|---|---|---|
| 0 预检 | 完成 | 非 worktree，无既有图谱 → 全量分析 |
| 0.5 ignore | 完成 | `.ua/.understandignore` |
| 1 SCAN | 完成 | `.ua/intermediate/scan-result.json`（109 文件，已修正 8 个被损坏的 sizeLines） |
| 1.5 BATCH | 完成 | `.ua/intermediate/batches.json`（10 批次） |
| 2 ANALYZE | **进行中** | 批次 1/2/3/4 已产出并**已独立复核为可信**：217 节点 / 442 边 / imports 53-53 |
| 3–7 | 未开始 | 分层、导览、审阅、组装、清理 |

## ⚠ 环境级故障：Node 文件读取会返回未初始化内存（本会话发现）

症状：同一路径，Node/.NET(PowerShell) 与 CPython/内置 Read 工具读到不同内容。

- `server.py`：Node 读到 122,640 B / 452 行 / 4595 个 NUL / 头部二进制；
  Python 与 Read 工具读到 118,544 B / 3139 行 / 0 个 NUL / 合法 UTF-8 Python
- `mapper_core.h`：Node 读到 10,343 B 且搜不到 `MAPPER_CORE_H`；真实 6,247 B / 166 行
- 隔离实验：Python 写入 100 / 4096 / 100000 字节的纯 ASCII 文件，Node 一律读到
  **+4096**（= NTFS 簇大小）且内容为全 256 字节值的随机内存
- 沙箱外（`required_permissions=all`）复现一致 → **不是沙箱造成**
- node = `C:\Program Files\nodejs\node.exe` v22.22.3，python = `C:\Python314`，均为真身；
  读 56 字节的 `.ua/config.json` 时两者逐字节一致 → 非全局性损坏，**按文件稳定复现**
- 已排除的区分因素：未提交/刚修改状态（对照组 `edge_tools.py`、`api_client.py` 同为未提交但读取正常）

影响：所有 `.mjs` 内置脚本跑在这个 Node 上，因此 `scan-project.mjs` 与
`extract-structure.mjs` 对受影响文件产出的是垃圾数据（表现为 0 符号 + 行数偏小 ~7 倍）。

**检测手段（必须保留）**：`verify-extract-integrity.py` 与 `verify-scan-lines.py`
用 CPython 独立复核全部文件。当前结果：**42 个 Python 文件中 40 个完全一致**，
残留 2 条（`stage_zero_generate.py` 250/251、`edge_proxy_config.py` 46/47）仅为
行尾换行计数口径差 1 行，非损坏。

已修复的 8 个文件（`repair-corrupted-reads.py`）：
- ast 注入结构：`server.py`(fn93/cls3)、`xlpa/tools/mcp_client.py`(fn7)、
  `protocol_converter.py`(cls1)、`test_protocol_converter.py`(cls12)、
  `gen_test_report.py`(无顶层 def)、`mcp_client.py`(无顶层 def)
- 仅校正行数：`mapper_core.c`(739)、`mapper_core.h`(166) —— C 无 ast 能力，
  结构仍为空，标 `structureSource=no-parser-for-c`，需下轮用 Read 工具人工补
- 注入的条目均带 `structureSource=cpython-ast-fallback` marker，便于归因

## 修正后的剩余工作量

| 批次 | 文件 | 显著符号 | 说明 |
|---|---|---|---|
| 9 | 25 | **141** | server.py 独占 96（MCP 工具面）；建议单独一轮先做 server.py |
| 8 | 25 | **13** | protocol_converter(1) + test_protocol_converter(12)；2 个 C 文件待人工补 |
| 5/6/7/10 | 30 | 0 | 纯文件节点，无符号 |

预计最终图谱规模由 ~331 节点上调至 **~451 节点**（109 文件 + ~342 符号）。


## 历史缺陷记录：server.py 空提取（已解决）

`mcp_server/server.py`（真实 3139 行）被 `extract-structure.mjs` 提取为 **0 函数 / 0 类**，
且 stderr 无任何 Warning。Python 自带 `ast` 可正常解析出 3 个类
（`TokenManager` [431-620]、`AuthMiddleware` [2623-2684]、`CompositeApp` [2690-3068]）
与 93 个顶层函数。

后果：server.py 是 FastMCP 入口与鉴权中间件所在，若照实使用脚本输出，
它将成为孤立 file 节点，架构图谱严重误导。

成因已查明为上节的 Node 读取损坏，**不是脚本 bug，也不是 PEP 701 嵌套引号 f-string**。

### 处置（已完成）

实际执行方法（勿改 `build-batch.mjs` 的过滤规则）：

1. 写一个一次性脚本，用 `ast` 解析 `mcp_server/server.py`，取顶层
   `FunctionDef` / `AsyncFunctionDef` / `ClassDef` 的 name / startLine / endLine / args，
   以及顶层赋值名（作为 exports 依据，与 tree-sitter 对 Python 的行为一致：
   exports = 全部顶层定义）。
2. 把结果就地注入 `.ua/tmp/ua-file-extract-results-9.json` 中 server.py 那条记录的
   `functions` / `classes` / `exports` / `metrics` 字段（仅补该文件，其余文件不动）。
3. 重跑 `python .ua/tmp/list_sig.py 9` 取新的显著符号清单，照此撰写 `sem-9.json`，
   再 `node .ua/tmp/build-batch.mjs 9`。
4. **必须在最终报告中声明**：server.py 的结构来自 CPython `ast` 而非 tree-sitter，
   与 SKILL.md「信任内置脚本」的约束存在一处有意偏离，以便后续复跑可归因。

## 剩余待办

1. 按上面方法补 server.py 结构
2. 批次 9（含 34+ 符号）与批次 5/6/7/8/10（共 57 个文件节点，无符号）
3. 全部 `batch-*.json` 就位后跑 `merge-batch-graphs.py`，再进入 Phase 3 起的
   架构分层 / 导览 / 审阅 / 组装 / 清理

## 复用工具（`.ua/tmp/`，均为执行期间编写）

- `verify-extract-integrity.py` — **可信度复核**：ast vs extract 逐文件比对（先跑这个）
- `verify-scan-lines.py` — sizeLines 与真实行数全量交叉核对（检测损坏读取）
- `repair-corrupted-reads.py` — 对受影响文件做 ast 注入 + 行数校正
- `patch-server-structure.py` — 单独补 server.py 结构
- `rerun-deterministic.mjs` — 重跑 Phase 1/1.5 + 各批次结构提取（**注意：会覆盖 ast 补资，
  重跑后必须再跑 repair-corrupted-reads.py**）
- `gen-batch-inputs.mjs` — 由 batches.json 生成各批次分析输入
- `summarize-extract.mjs` / `plan-rounds.mjs` / `list_sig.py` — 规模与显著符号统计
- `dump-docstrings.py` — 按批次导出 docstring（摘要依据来源；Python 读取可信）
- `build-batch.mjs` — 语义表 + 结构结果 → `batch-<i>.json`，含 ID/字段/imports 1:1/分片自检
- `sem-<i>.json` — 各批次语义表（摘要与标签）；新增批次照此撰写后 `node build-batch.mjs <i>`
