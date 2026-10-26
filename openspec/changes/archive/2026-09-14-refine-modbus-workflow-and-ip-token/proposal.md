## Why

当前 MODBUS 转换流程已具备平台查询、本地 references 回退和用户确认能力，但从使用者角度仍存在几个摩擦点：原子标签查不到时容易被误判为平台不存在，用户级权限下仍可能看到无法执行的写入分支，MCP Server 重启后远程用户已分配的 Token 会失效，且 `/pca` 前置检查缺少版本与更新建议。需要将这些交互与持久化规则沉淀为可验证的工作流规范。

## What Changes

- 优化 MODBUS 原子标签匹配流程：原子标签平台查询使用 API-E10 `GetProtocoFunctionTypeList`（MCP 工具 `get_function_type_list`）查询功能项列表，平台未命中时进行关键词、同义词和模糊匹配；仍未命中再回退本地 references；本地也未命中时提示用户补充基础信息。
- 增加原子标签批量确认与置信度表达：避免逐点打断，统一展示平台候选、本地候选、用户补充项、来源、置信度和待确认动作。
- 调整权限交互：`user` 权限下不展示、不询问、不执行任何需要 system 权限的平台写入动作；`system` 权限下仍必须先展示写入计划并经用户确认。
- 强化查询语义：严格区分平台查询失败（`error=true`）与查询为空（`empty=true`），查询失败不得进入新增流程。
- 优化 `/pca` 前置探测：除 MCP 连通性与权限外，展示 MCP Server 版本、远端 Agent 资源包版本、本地资源包版本、版本兼容风险和是否建议更新。
- 增加能力矩阵提示：在进入业务流程前说明当前可执行的平台查询、本地生成、平台新增、平台同步和资源包更新能力。
- 新增 MCP Token 管理能力：非本机 user Token 按 IP 固定并持久化，MCP Server 重启后旧 Token 继续有效；预留 `lastSeenAt`、`revoked`、清理和撤销能力。
- 增加长流程体验要求：MODBUS 输出包含续跑摘要、变更影响提示、未验证项和下一步建议。
- 不新增独立“纯本地模式”入口；仍允许在未登录或平台不可用时按既有本地 references 兜底继续，但不作为单独模式选择流程。

## Capabilities

### New Capabilities

- `mcp-token-management`: 定义 MCP 接入 Token 的按 IP 固定分配、持久化、重启复用、撤销预留和安全边界。

### Modified Capabilities

- `modbus-mcp-workflow`: 优化 MODBUS 原子标签匹配、权限分支、批量确认、查询失败/为空处理、续跑摘要和变更影响提示。
- `pca-entry-workflow`: 增强 `/pca` 前置探测中的版本、资源包更新、能力矩阵和权限相关用户提示。

## Impact

- 影响 `.trae/skills/modbus-conversion/SKILL.md`：更新原子标签匹配、明确 API-E10/get_function_type_list 查询入口、批量确认、权限分支、写入确认、续跑摘要和输出模板。
- 影响 `.trae/skills/pca/SKILL.md`：更新 `/pca` 前置检查、版本探测、更新提示、能力矩阵和 user/system 权限提示。
- 影响 `mcp_server/server.py`：扩展 `TokenManager` 为按 IP 持久化 Token Registry，调整 `/api/access-info` 与鉴权校验逻辑以加载持久化 Token。
- 影响 `mcp_server/static/access.html`：接入页展示按 IP 固定 Token、Token 绑定来源和重启复用说明。
- 影响 `.trae/skills/package-manifest.json` 与各 Skill manifest 的版本比较语义；可能需要在 `list_mcp_tools` 返回值中补充兼容性与特性标识。
- 影响本地安全约束：新增 Token Registry 文件必须作为本地运行态文件处理，不得进入 Agent 资源包或版本控制。