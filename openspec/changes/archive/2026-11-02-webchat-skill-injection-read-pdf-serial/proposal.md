## Why

Web 会话实测未加载任何技能：adapter 以 `setting_sources=[]` 启动且 cwd 为会话
工作区，事件 `878fbcf0...` 的 118 次工具调用中没有 `Skill`，只有
`mcp__xlpa__*` 与 `WebSearch`。模型因此只能凭记忆拼平台工具入参，出现近 100
次 `gen_script` 重试（`cusstr`/`query`/`dataItemId` 缺失或为空）后才偶然成功。

同时用户上传 PDF 后无法读取内容（webchat 环境无 PDF 解析依赖），模型只能靠
截图 OCR 或让用户手抄；同一会话并发轮次还会出现两个 `turn=9`、`turn 8` 缺失
与文本重复（`send_message` 只校验租约、不校验 `turn_running`，确认卡片自动续跑
会再发一条消息）。

## What Changes

- **技能真正加载（B+C）**：启动时读取 canonical `agent_assets/skills` 各
  `SKILL.md` 的 name/description/when_to_use 形成索引写入系统提示（含各
  SKILL.md 路径）；消息以 `/技能名` 开头时该技能全文在**当轮**注入，其余技能
  由模型按需用内置 `Read` 读取。技能来源锁定 `agent_assets`，不使用仓库
  `.qoder/skills` 旧副本；目录可经 `WEBCHAT_SKILLS_ROOT` 覆盖。
- **开放内置 Read**：`tools` 增加 `Read`；WriteGate 新增 `read_roots`
  （会话工作区 + canonical 技能目录），路径经 `resolve()` 白名单校验，仓库
  其他文件/目录穿越一律拒绝且不可确认解除。
- **PDF→文本**：`document` 通道落盘 PDF 后用 `pypdf` 提取文本写
  `xlpa-input/<stem>.pdf.txt`，响应返回 `text_path`/`text_chars`；提取失败或
  扫描件无文本时显式 `warning`，原文件保留、上传不阻塞，不伪造成功。
- **同会话轮次串行化**：`send_message` 在 `turn_running` 时返回
  409「上一轮仍在执行，请稍候」；`/confirm` 响应带 `turn_running`，前端在该
  轮仍在执行时不再自动发续跑消息，改为提示「助手将在当前轮重试」。
- **工具契约按技能与实测走**：在 canonical 技能中写明平台工具入参以
  `list_mcp_tools` schema 与同类历史记录（`get_script_list`/`get_json_detail`）
  为准；`gen_script` 实测必填 `query`/`cusstr`/`dataItemId`（正整数非空数组）
  仅作参考，不硬编码 `mcp_server` 签名。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `agent-runtime-session`: 技能索引与按需注入、内置只读边界、同会话轮次串行。
- `web-artifact-delivery`: PDF 文档文本提取与失败显式降级。
