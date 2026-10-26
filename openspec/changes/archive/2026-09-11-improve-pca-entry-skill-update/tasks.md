## 1. PCA 入口前置检查与业务 Token 缓存

- [x] 1.1 更新 `.trae/skills/pca/SKILL.md`，将 MCP 端点与示例从旧 3000 端口修正为当前 8765 端口与 IPv4/localhost 表达
- [x] 1.2 在 `/pca` 入口流程中新增前置检查章节：调用 `list_mcp_tools`、展示工具数量、`access_level`、source 和权限影响
- [x] 1.3 定义本地后端业务 Token 缓存策略：缓存位置、读取条件、失效处理、不得写入 MCP 配置、不得作为 Bearer Token 使用
- [x] 1.4 定义无本地业务 Token 时的登录提示：请求 `phoneNum` 和 `code`；用户跳过时仅执行本地 references 或无需登录的流程
- [x] 1.5 定义本地业务 Token 失效时的恢复路径：展示错误、清理/标记失效、重新提示登录、等待用户决定

## 2. Skills 全量更新流程

- [x] 2.1 更新 `/pca` Skill，新增“检查并更新本地 Skills”入口操作
- [x] 2.2 定义本地与远端 Skill 版本读取规则，至少读取各 `SKILL.md` 的 `metadata.version`；远端缺少 manifest 时展示无法精确比较的原因
- [x] 2.3 定义全量更新计划展示：下载来源、更新范围、备份路径、覆盖策略、生效方式
- [x] 2.4 实现或规划必要的辅助脚本/工具：下载 Skills ZIP、备份 `.trae/skills`、覆盖全部 Skills、校验关键目录与 `agents/openai.yaml`
- [x] 2.5 明确用户未确认更新时不得修改本地 Skills，继续执行当前版本流程并提示版本差异风险
- [x] 2.6 明确更新完成后提示重新加载 `/pca` 会话或重启客户端

## 3. IPv4 用户可见配置

- [x] 3.1 检查 `mcp_server/server.py` 的 `/api/access-info` baseUrl 生成逻辑，确保用户可见配置不生成 IPv6 地址
- [x] 3.2 检查 `mcp_server/static/access.html` 的配置生成和错误提示，移除旧 3000 端口文本，确保示例使用 IPv4 或 localhost
- [x] 3.3 保留服务端内部 `::1` localhost 兼容，不把“不展示 IPv6”扩展成拒绝 IPv6 请求
- [x] 3.4 添加验证：接入页生成的 Trae/Cursor/VS Code/Claude/Kimi/Windsurf/Cline 配置中不出现 IPv6 主机

## 4. MODBUS 协议转换决策规则

- [x] 4.1 更新 `.trae/skills/modbus-conversion/SKILL.md`：`func_code` 必须来自协议文档；文档无说明、多个候选或平台差异时列出歧义并由用户确认
- [x] 4.2 更新 `data_type` 决策规则：本地 JSON 优先使用 Skill 规范写法，平台历史写法只作为差异或待验证项记录
- [x] 4.3 更新来源标记规则：MCP 来源必须精确到工具、rows 下标和字段；本地来源必须精确到文件和章节/表格/sheet
- [x] 4.4 更新字段语义拆分规则：区分 `classNum`、`modelNum`、`classifyId`、`deviceTypeId`、`deviceTypeCode`、`brandId`、`modelId`、`protocolId` 的含义与是否写入 JSON
- [x] 4.5 更新平台暂无数据项规则：本地保留、平台新增所需基础信息、权限要求、是否阻塞同步必须输出

## 5. MODBUS 交互记录输出模板

- [x] 5.1 在 MODBUS Skill 中新增交互记录输出结构：结论摘要、环境与接入、阶段一/二/三、最终确认表、测试与未验证项、产物清单、下一步建议、安全说明
- [x] 5.2 增强点表展示字段：中文名、英文标签、Hex 地址、Dec 地址、寄存器跨度、单位、data_type、data_order、func_code、data_exprs、来源、读写属性
- [x] 5.3 定义歧义项确认表：功能码、单位、标签语义、地址变体、累积量精度、平台差异等影响输出的项必须先确认
- [x] 5.4 定义最小冒烟测试清单：JSON 结构一致性、Hex/Dec 地址、寄存器跨度、功能码来源、data_type 规范、字节序示例或转换公式
- [x] 5.5 定义未验证项清单：现场设备读取、平台写入、平台新增数据项、功能码现场兼容性、data_type 兼容性等

## 6. 验证

- [x] 6.1 使用 `openspec validate improve-pca-entry-skill-update --strict` 验证规划工件
- [x] 6.2 静态检查 `/pca` 与 MODBUS Skill 文档，确认新增规则覆盖用户确认的 5 类需求
- [x] 6.3 手动验证无本地业务 Token 场景：`/pca` 提示登录；用户跳过时仅使用本地 references（已通过 F3000X 转换验证）
- [x] 6.4 手动验证有本地业务 Token 场景：`/pca` 不重复提示登录，平台查询使用缓存 Token；Token 失效时提示重新登录（已通过 F3000X 转换验证：IDE Token 失效→获取新 Token→重新登录）
- [x] 6.5 手动验证 Skills 更新流程：未确认时不覆盖；确认时先备份再全量覆盖，并提示重新加载（已通过验证脚本全流程模拟：场景 A 拒绝更新→不覆盖；场景 B 确认更新→备份→下载 ZIP(187 文件)→覆盖→包级 manifest 校验 26/26 通过→8 个 Skill 级 manifest 校验全部通过→清理备份）
- [x] 6.6 手动验证接入配置和下载链接不输出 IPv6 地址
- [x] 6.7 用一次 MODBUS 协议转换记录验证输出模板：包含摘要、字段语义拆分、增强点表、歧义确认、冒烟测试、未验证项和下一步建议（已通过 F3000X 转换验证）
