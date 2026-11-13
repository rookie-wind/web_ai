## Context

- Web 会话与 IDE 共用同一 CLI/SDK，但 webchat 以 `setting_sources=[]` 关闭
  settings 来源，技能发现不生效；仓库 `.qoder/skills` 是旧版 0.1.0（xlpa
  SKILL.md 首行损坏）且体积 13MB，不适合作为来源。
- canonical `agent_assets/skills` 为 0.8.0（9 个技能，SKILL.md 约 100KB），
  是 MCP Server 分发包的母本。
- 会话已具备工作区（`xlpa-input/`、`xlpa-output/`）与写入门禁；只读面未开放。
- `gen_script` 的字段契约无法从 IDE transcript 探测（仓库会话 transcript 无该
  调用），平台 400 实测给出 required：`cusstr`、`query`、`dataItemId`。

## Decisions

### D1 技能索引 + 按需注入（B+C）

- 启动时 `load_catalog(skills_root)` 解析每个 `SKILL.md` frontmatter 的
  `name`/`description`/`when_to_use`，`render_index()` 渲染为系统提示附录；
  索引含真实路径，模型可 `Read` 全文。
- `/技能名` 前缀在 `AgentHandle._prepare_prompt` 中匹配目录内技能名（大小写
  不敏感），命中则把 SKILL.md 全文作为「只读参考」块拼在该轮用户消息前。
  选择拼在**用户消息**而非每轮重建系统提示：resume 场景下系统提示的 append
  行为不稳定，消息注入保证每轮生效。
- 不匹配的前缀（如 `/foo`）保持普通文本，不误注入。

### D2 Read 白名单

- `WriteGate(read_roots=[workspace, skills_root])`；`check_read` 对
  `file_path`/`path` 做 `resolve()`，相对路径按 workspace 解析，必须位于某个
  根内；拒绝时产 `gate_blocked(guard=read_path, confirmable=false)`。
- adapter 工具面 `Write/Edit/Read` 同时进 `allowed_tools`；`can_use_tool`
  复用 `check_read`，PreToolUse 门禁仍先行裁决。

### D3 PDF 文本 sidecar

- `extract_pdf_text` 惰性导入 `pypdf`，按页 `extract_text()` 拼接。
- 上传端点写 `xlpa-input/<stem>.pdf.txt`；`ImportError`/解析异常/空文本三分支
  均写 `warning`，保留原 PDF、HTTP 200。前端 notify 显示 warning。

### D4 同会话轮次串行化

- `send_message` 在租约校验后、并发名额前检查 `session.turn_running`，命中返回
  409，不排队、不拉起第二个 CLI 轮次。
- `/confirm` 返回 `turn_running`；前端仅在其为 false 时自动续跑，为 true 时
  提示已确认、助手将在当前轮重试。确认票据已在窗口内生效，不依赖续跑消息。

### D5 工具契约不硬编码

- 技能文档明确“先读 schema、先查历史、按实测补齐、失败即停”；只在
  `modbus-conversion` 记录 `gen_script` 的平台实测必填字段作为参考，不修改
  `mcp_server/server.py` 的签名或加硬校验，避免锁死其他协议方向。

## Risks / Trade-offs

- `/技能名` 全文注入会使该轮提示变长（xlpa 约 13KB）；仅在显式前缀时发生，
  普通消息不注入。
- Read 白名单仅两个根，模型无法读仓库源码/配置；这是有意的最小权限。
- PDF 扫描件无文本时无法自动 OCR（图片型 PDF 不在本次范围），以 warning 显式
  告知并引导截图 OCR。

## Migration

- 新增依赖 `pypdf`（纯 Python）。
- 新增环境变量 `WEBCHAT_SKILLS_ROOT`（默认 `agent_assets/skills`）。
- 存量无前缀会话行为不变；同会话并发消息从“静默乱序”变为显式 409。
