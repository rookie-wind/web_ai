## 1. Token Registry 与接入鉴权

- [x] 1.1 在服务端新增按 IP 固定的 Token Registry 读写逻辑，并通过同一非本机 IP 两次访问 `/api/access-info` 返回同一 user Token 验证
- [x] 1.2 在服务启动时加载已持久化的 Token Registry，并通过重启服务后旧 user Token 仍可调用 `list_mcp_tools` 验证
- [x] 1.3 在 Token Registry 中记录 IP、Token、accessLevel、createdAt、lastSeenAt、revoked，并通过访问接入信息或 MCP 调用后 lastSeenAt 更新验证
- [x] 1.4 在鉴权中间件中识别未撤销的持久化 user Token，并通过 revoked Token 被拒绝、未撤销 Token 通过验证
- [x] 1.5 确保 localhost/system 管理员 Token 仍来自 `MCP_AUTH_TOKEN`，并通过本机访问仍获得 system 权限验证
- [x] 1.6 将 Token Registry 作为本地敏感运行态文件排除出 Agent 资源包和版本控制范围，并通过 ZIP 列表与忽略规则检查验证

## 2. MCP 版本与资源包探测

- [x] 2.1 扩展 `list_mcp_tools` 返回 MCP Server 版本、Agent 资源包版本、manifest 校验状态和兼容性特性，并通过工具调用响应字段验证
- [x] 2.2 更新本地/远端资源包版本比较逻辑，并通过版本一致、远端较新、本地缺失 manifest 三类样例验证提示内容
- [x] 2.3 增加版本兼容风险提示规则，并通过本地 Skill 缺少新能力时输出建议更新但不自动更新验证
- [x] 2.4 保持现有 `list_mcp_tools` 字段兼容，并通过旧字段 `server`、`version`、`auth`、`tools` 仍存在验证

## 3. `/pca` 前置检查与能力矩阵

- [x] 3.1 更新 `.trae/skills/pca/SKILL.md` 的前置检查，展示 MCP 连接、权限、来源、Server 版本、本地/远端资源包版本，并通过文档审查验证字段齐全
- [x] 3.2 新增 `/pca` 能力矩阵，覆盖 MCP 工具调用、平台只读查询、本地 references 分析、本地 JSON 生成、平台新增、平台同步、资源包更新，并通过文档审查验证 system/user/未登录三类场景
- [x] 3.3 在 user 权限下隐藏平台新增和平台同步确认选项，并通过文档示例或手工流程验证不出现写入询问
- [x] 3.4 在 system 权限下保留写入前确认要求，并通过文档示例或手工流程验证写入计划必须先展示
- [x] 3.5 增加可选更新提示和兼容风险提示，并通过远端版本较新但任务可继续时不阻塞流程验证

## 4. MODBUS 原子标签匹配流程

- [x] 4.1 更新 `.trae/skills/modbus-conversion/SKILL.md`，将原子标签查询入口明确为 API-E10 `GetProtocoFunctionTypeList` / MCP `get_function_type_list`，并通过文档审查验证不再把 `get_data_item_list` 作为原子标签查询入口
- [x] 4.2 将原子标签流程调整为平台功能项优先、关键词变体/同义词/模糊匹配、本地 references 兜底、用户补充，并通过文档审查验证顺序正确
- [x] 4.3 增加原子标签匹配置信度分级和批量确认表，并通过高置信默认建议、中低置信用户确认、无候选用户补充三类样例验证
- [x] 4.4 强化查询失败与查询为空的文案和处理分支，并通过 `error=true` 不进入新增、`empty=true` 可进入本地兜底验证
- [x] 4.5 在平台和本地都未命中时增加用户补充模板，并通过补充中文名、英文标签、单位、读写属性、数据含义字段验证
- [x] 4.6 在 user 权限下对用户补充项仅标记为本地使用和平台未同步，并通过不询问保存平台功能项验证
- [x] 4.7 在 system 权限下对用户补充项先确认基础信息再询问是否新增平台功能项，并通过确认后才调用功能项保存工具验证

## 5. MODBUS 输出与长流程体验

- [x] 5.1 更新 MODBUS 最终确认表，展示平台候选、本地候选、用户补充、来源、匹配方式、置信度、待确认动作，并通过文档示例验证字段齐全
- [x] 5.2 增加变更影响提示，说明用户选择或补充原子标签对 `taskList`、`labelList`、本地 JSON 和平台同步的影响，并通过示例输出验证
- [x] 5.3 增加续跑摘要，展示已确认实体、已确认点位、待确认点位、本地 JSON 状态、平台同步状态和下一步动作，并通过阶段性结束输出验证
- [x] 5.4 确保本地 JSON 生成与平台同步继续分阶段执行，并通过 user 权限不展示同步、system 权限确认后才同步验证
- [x] 5.5 保留现有最小冒烟测试、未验证项清单、字段语义拆分和增强点表要求，并通过一次完整 MODBUS 记录样例验证

## 6. 接入页、文档与安全提示

- [x] 6.1 更新 `mcp_server/static/access.html` 展示 Token 绑定当前访问 IP、重启后复用和 IP 变化需重新获取的提示，并通过接入页展示验证
- [x] 6.2 更新部署文档说明 Token Registry 的敏感性、持久化行为和不得提交版本控制，并通过文档审查验证
- [x] 6.3 更新 README 或启动输出中已过时的工具数量与桩工具描述，并通过启动日志和文档内容一致性验证
- [x] 6.4 确保 Agent 资源包导出不包含 Token Registry，并通过 `/api/docs/export-skills-package` ZIP 内容验证

## 7. 验证与回归

- [x] 7.1 运行 `openspec validate refine-modbus-workflow-and-ip-token --strict` 并验证通过
- [x] 7.2 验证 MCP Server 重启后远程 user Token 仍可调用 `list_mcp_tools`，并确认 access_level 仍为 user
- [x] 7.3 验证 user 权限 MODBUS 流程不会调用 `add_*`、`update_*`、`del_*`、`save_*`、`upload_protocol_file` 或 `gen_script` 写入工具
- [x] 7.4 验证 system 权限 MODBUS 流程在任何写入前均展示计划并等待用户确认
- [x] 7.5 验证 `/pca` 在版本一致、版本落后、manifest 缺失、MCP 探测失败四类状态下均给出正确能力矩阵和下一步建议
- [x] 7.6 验证原子标签匹配的批量确认表覆盖平台功能项高置信、平台功能项多候选、本地候选和用户补充四类结果
