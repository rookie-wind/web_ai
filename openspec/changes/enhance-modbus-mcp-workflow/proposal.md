## Why

当前项目已有 MODBUS 协议转换 Skill 与规约管理 MCP 服务化设计，但二者尚未形成可直接实施的技术方案：`modbus-conversion` 仍以本地参考文档和示例性高阶 MCP 工具为主，而 MCP 服务化 Spec 已规划细粒度后端 API 原子工具。需要将首期范围收敛为 MODBUS Skill，通过可验证的 MCP 原子工具编排、本地参考兜底、权限控制和平台同步确认，形成可直接指导代码生成的方案。

## What Changes

- 首期仅完善 MODBUS 协议转换 Skill；HTTP/MQTT 相关 Skill 与工具限制策略不纳入本次范围。
- 将 MODBUS Skill 的 MCP 调用从示例性高阶工具改为 `规约管理MCP服务化Spec.md` 中定义的规约管理原子工具。
- 明确 Skill 启动时询问 `login(phoneNum, code)`；未提供时仅使用本地 `references` 参数来源。
- 明确 MCP 接入 Token 与后端业务 Token 不得混用。
- 明确参数获取优先级：MCP 查询优先；查询为空可回退本地推荐；查询失败不得当作不存在。
- 明确普通用户只读、系统级用户全部权限；普通用户遇到写入步骤必须停止并提示需要系统级用户。
- 明确写入操作必须先展示计划并经用户确认；写入后展示返回值，不自动重试。
- 明确默认先生成本地 MODBUS JSON；用户确认后再询问是否同步到平台。
- 明确 `classNum` 来源为大类编号，`modelNum` 来源为设备类型管理的 `deviceTypeCode` 字段。
- 明确数据项/原子标签首期只查询和新增基础信息，不写入完整寄存器采集配置。
- 明确 MODBUS 首期不调用删除类 MCP 工具。
- 补充可验证验收标准，要求输出参数来源、最终确认表、缺失项清单和写入返回值。

## Capabilities

### New Capabilities
- `modbus-mcp-workflow`: 定义 MODBUS 协议转换 Skill 如何编排规约管理 MCP 原子工具、本地参考兜底、权限校验、本地 JSON 生成和可选平台同步。

### Modified Capabilities

无。

## Impact

- 影响 Skill 文档：`.trae/skills/modbus-conversion/SKILL.md`，用于落地 MODBUS 流程中的 MCP 工具调用规则、参数来源规则、权限与写入交互规则。
- 影响 MCP 服务实现：`mcp_server/server.py`、拟新增 `mcp_server/api_client.py`、`mcp_server/requirements.txt`，用于实现规约管理原子工具、后端 API 调用和权限拦截。
- 影响现有设计文档：`规约管理MCP服务化Spec.md` 与 `规约管理基础数据模块Spec.md`，作为 API、字段、流程和业务规则依据。
- 不影响 HTTP/MQTT Skill 首期行为；不实现 Vue 接入页迁移；不实现删除类工具在 MODBUS Skill 中的调用。
