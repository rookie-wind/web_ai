## Context

当前服务端通过 `TokenManager` 在内存中维护非本机 IP 到 MCP 接入 Token 的映射，重启后远程用户 Token 会失效；`list_mcp_tools` 已返回 MCP 服务版本与资源包信息，但 `/pca` 入口对本地/远端版本差异、兼容风险和能力矩阵的展示仍不稳定。MODBUS Skill 已定义平台查询、本地 references 回退、系统级写入确认和最终确认表，但原子标签查不到时缺少关键词不一致场景下的批量匹配与低打扰确认机制，`user` 权限下也仍存在展示写入分支或触发 FORBIDDEN 后才停止的体验问题。

## Goals / Non-Goals

**Goals:**

- 让非本机 user Token 按访问 IP 固定，MCP Server 重启后继续有效。
- 让 `/pca` 前置检查同时输出权限、版本、资源包更新建议、兼容风险和当前能力矩阵。
- 让 MODBUS 原子标签匹配以平台功能项列表（API-E10 `GetProtocoFunctionTypeList` / MCP `get_function_type_list`）为主、本地 references 为兜底，并通过批量确认降低用户打断频率。
- 在 `user` 权限下隐藏所有平台写入选择，在 `system` 权限下维持写入前确认。
- 保持查询失败与查询为空的语义差异，避免误新增平台数据。

**Non-Goals:**

- 不新增独立的“纯本地模式”入口或模式选择页。
- 不改变后端业务 Token 与 MCP 接入 Token 的隔离关系。
- 不改变 MODBUS 之外的 MQTT/HTTP 协议转换流程。
- 不在首期实现图形化 Token 管理后台；仅预留撤销、清理、lastSeenAt 等数据结构与行为边界。

## Decisions

### 1. Token Registry 采用按 IP 明文 Token 持久化

MCP Server 在本地运行态文件中保存非本机 IP 的 user Token 映射。访问 `/api/access-info` 时，服务按客户端 IP 查找 registry：存在且未 revoked 时返回原 Token；不存在或已撤销时生成新 Token 并保存。`AuthMiddleware` 校验 Bearer Token 时同时认可管理员 Token 与 registry 中未撤销的 user Token。

选择理由：当前项目主要面向本地/局域网开发与协作，用户诉求是服务重启后无需重新配置客户端，按 IP 明文保存实现最直观，也能在接入页再次展示相同 Token。

替代方案：

- 保存 Token hash：更安全，但无法在接入页重新展示原 Token，不符合“按 IP 固定再次获取”的体验。
- 由 `MCP_AUTH_TOKEN + IP` 确定性生成：无需保存明文，但管理员 Token 变更会导致所有 user Token 失效，且不利于撤销单个 IP。
- 继续内存保存：实现最简单，但不满足重启后继续有效。

### 2. Token Registry 是运行态文件，不属于 Agent 资源包

Token Registry 应放在 `mcp_server/` 下的本地运行态路径，并纳入忽略规则，不随 `.trae/skills` Agent 资源包导出。

选择理由：Token 属于本机服务安全状态，不是可分发资产；打包到 Agent 资源包会导致凭证泄露风险。

### 3. `/pca` 前置探测以低打扰摘要为默认输出

`/pca` 入口通过 `list_mcp_tools` 和本地 manifest 信息生成环境摘要，默认展示核心结论：MCP 是否连通、权限级别、Server 版本、远端资源包版本、本地资源包版本、是否建议更新、当前能力矩阵。只有版本不兼容、manifest 缺失、资源包校验失败或用户主动要求更新时，才展开更新计划或风险详情。

选择理由：前置检查需要稳定，但不能每次用大量诊断信息打断用户。

### 4. 原子标签匹配采用“平台功能项批量候选 + 本地兜底 + 用户补充”

MODBUS Skill 查询原子标签时应使用 API-E10 `GetProtocoFunctionTypeList`，在 MCP 层对应 `get_function_type_list`。该查询返回平台功能项列表，是原子标签候选的主来源；`get_data_item_list` 仅用于协议数据项列表，不作为原子标签查询入口。Skill 应尽量一次性查询平台功能项列表，并在本地内存中对协议文档点位执行精确、归一、同义词或模糊匹配，输出高/中/低/无四类置信度。平台功能项为空时再查本地 references；本地也无结果时再请求用户补充。

选择理由：平台功能项/原子标签通常比本地 references 更丰富，查不到经常是关键词不一致，而不是平台缺失。批量匹配能降低接口调用次数和用户打断频率，也避免把协议数据项查询和原子标签查询混用。

### 5. 权限决定交互分支，而不是依赖失败返回

当 `accessLevel=user` 时，Skill 不展示“是否新增平台”“是否同步平台”等写入选项，也不调用写入工具试错；只在摘要中说明写入不可用。`system` 仅代表“允许写入”，任何写入仍必须展示计划并等待用户确认。

选择理由：用户级权限下询问无法执行的动作会造成挫败感；系统级自动写入则存在误操作风险。

### 6. 长流程输出包含续跑摘要与变更影响提示

MODBUS 每个阶段结束时输出可续跑摘要，至少包含已确认实体、已确认点位、待确认点位、本地 JSON 状态、平台同步状态和下一步命令建议。用户选择或补充某个原子标签时，需要说明该选择影响 `taskList`、`labelList`、本地 JSON 和可选平台同步。

选择理由：MODBUS 文档分析通常是多轮长流程，用户需要知道当前进度和每个确认动作影响范围。

## Risks / Trade-offs

- Token Registry 明文保存导致本机文件泄露风险 → 将 registry 定义为运行态敏感文件，要求不进入版本控制、不打包分发，并在部署文档和接入页提示安全边界。
- 按 IP 固定在 DHCP 或 NAT 场景下可能把 Token 绑定给变化或共享的网络身份 → 接入页展示绑定 IP，并说明 IP 变化需要重新获取；后续预留撤销和清理能力。
- 原子标签模糊匹配可能产生误匹配 → 中/低置信候选必须经用户确认，高置信结果也进入最终确认表并标注来源。
- 版本更新提示过于频繁会干扰用户 → 仅在版本不一致、兼容风险、manifest 缺失或用户主动检查时展开提示；普通一致状态只显示简短摘要。
- `user` 权限下隐藏写入分支可能让用户不知道如何同步平台 → 摘要和下一步建议必须说明需要在服务器本机以 `system` 权限执行同步阶段。

## Migration Plan

1. 先更新 OpenSpec 规格和 Skill 文档，明确用户可见行为。
2. 实现 Token Registry 并保持现有 `MCP_AUTH_TOKEN` 管理员 Token 行为不变。
3. 扩展 `list_mcp_tools` 返回版本、资源包和兼容性信息；保持现有字段兼容。
4. 更新 `/pca` Skill 前置检查与 MODBUS Skill 原子标签匹配流程。
5. 更新接入页和部署文档，说明按 IP 固定 Token、重启复用、安全边界和更新提示。
6. 通过单元或手工验证覆盖：重启后 user Token 可用、user 权限不触发写入、system 写入仍需确认、版本差异提示、原子标签批量确认。