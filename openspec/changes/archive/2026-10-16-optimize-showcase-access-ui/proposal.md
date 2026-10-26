## Why

当前 `showcase.html` 已具备成果展示基础，但首屏架构图过小、信息表达偏弱，无法充分体现 AI 智能体驱动的协议接入交付闭环；从展示页跳转到 `access.html` 后，深色霓虹展示风与浅色后台表单风强烈割裂，削弱“成品产品”的整体感。

本次变更将把展示页与接入页统一成同一套产品视觉语言，并补齐 Qoder 客户端接入，让老板展示场景和实际接入工具形成连续体验。

## What Changes

- 优化 `showcase.html` 的首屏布局：保留标题叙事，采用左侧文案与核心数字、右侧放大终端打字机的方案。
- 将原首屏右侧小架构图移出，重绘为独立大尺寸“协议智能体数据流转架构”模块，强调“用户需求 → AI 智能体 → 协议识别与技能路由 → MCP 工具网关 → 配置生成/测试验证/打包分发/上线运行”的交付闭环。
- 调整幕3副题，仅将“右边是现在的做法”替换为体现 AI 的表达；保留“同一件事，两种做法”标题和既有 Before/After 叙事结构。
- 修复展示页文案中的 `重复 查看文档` 空格问题。
- 在展示页兼容客户端中新增 Qoder，并将相关客户端数量从 7 调整为 8；收尾句只改数字，不重写措辞。
- 重做 `access.html` 为与展示页一致的深色霓虹产品风格，包括背景、卡片、平台选择、按钮、状态面板和代码预览。
- 将 `access.html` 平台选择从普通下拉升级为 8 个目标平台卡片，并新增 Qoder 平台。
- 将接入文本预览从普通 `textarea` 升级为代码编辑器式展示，复制和下载仍必须使用干净的原始文本。
- 增加从 `access.html` 返回成果展示页的无文字图标入口。
- 修复 `access.html` 错误提示中仍指向 `/` 的旧路径，改为 `/access`。
- 不新增演示模式，不新增全局运行仪表条，不展开 48 个 tools，不改变 MCP API 或鉴权逻辑。

## Capabilities

### New Capabilities
- `showcase-access-experience`: 定义成果展示页与一键接入页的视觉体验、架构表达、平台兼容和接入配置生成要求。

### Modified Capabilities
- `agent-assets-package-management`: 接入页生成的用户可见说明新增 Qoder 平台配置，并保持 Agent 资源包下载与安装说明兼容。
- `pca-entry-workflow`: 用户可见接入体验继续满足 IPv4 地址展示与可执行下一步要求，并通过接入页为新增 Qoder 客户端生成可用配置。

## Impact

- Affected files:
  - `mcp_server/static/showcase.html`
  - `mcp_server/static/access.html`
- No backend API change is intended; `/`, `/showcase`, `/access`, `/api/access-info`, and existing export endpoints remain unchanged.
- Qoder configuration uses `mcpServers` root with `url` + `headers`, and intentionally omits `type`.
- Apply phase must first inspect current uncommitted edits in `showcase.html` because an earlier implementation attempt partially changed the hero/architecture CSS before this planning workflow started.
- Browser verification is required after implementation because visual layout, SVG geometry, code preview, copy/download behavior, and platform switching cannot be fully validated by static inspection alone.
