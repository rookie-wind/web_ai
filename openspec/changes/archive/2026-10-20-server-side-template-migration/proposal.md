## Why

Server 模板结构会随设备类型新增而演进（新增 `监测点·X` sheet），但客户端手上的
文件可能还是旧版本（少表、版本标签落后）。当前版本门采用精确相等校验，旧版文件
会被 reader 直接拒绝。缺少一条服务端桥接路径意味着客户端要么报错止步，要么各自
做本地结构迁移（引入差异化、不可控、违背"服务端统一处理"原则）。

## What Changes

- 新增 MCP 工具 `migrate_device_archive_template(file_id)`：接受一份已上传的
  旧版本模板，由 server 产出当前版本的新 `file_id`（保留已有数据、补新 sheet
  空骨架、重贴正确版本标签），供客户端继续走 read/plan。
- 新增模块 `archiving/template_migrator.py`：承载确定性的"旧→新"结构迁移逻辑，
  可独立单测。
- 在 `edge_tools.py` 注册工具并复用现有 `template_store` 存取。
- 版本门（`excel_reader`）和建档工作流规格保持不动，迁移工具是额外提供的桥接。

## Capabilities

### New Capabilities
- `template-version-migration`: 服务端显式模板版本迁移工具，覆盖旧文件输入校验、
  结构升级逻辑、新 file_id 产出和错误反馈。

### Modified Capabilities
<!-- 无：版本门严格相等不变；建档工作流需求不变；分发流程不变 -->

## Impact

- **代码**：`mcp_server/edge_tools.py`（新工具注册）、
  `mcp_server/archiving/template_migrator.py`（新模块）、
  `mcp_server/tests/`（新单测）。
- **API 面**：MCP 工具列表新增一项，不影响既有工具的入出参。
- **依赖**：复用 openpyxl（已有）+ generator（已有骨架生成）。
- **文档/规格**：需在 SKILL.md 增加迁移工具说明；主规格 `template-version-migration`
  新增。
- **不改**：版本门、reader 核心、plan 逻辑、联通三工具。
