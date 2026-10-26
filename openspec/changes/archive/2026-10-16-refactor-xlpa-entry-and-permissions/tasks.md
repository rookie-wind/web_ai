## 1. XLPA 入口与资源包改名

- [x] 1.1 全量定位 `pca` 用户可见入口、Skill 目录、manifest、备用客户端路径、文档和 OpenSpec 引用，并用搜索结果清单验证影响面完整
- [x] 1.2 将 `.trae/skills/pca` 一刀切迁移为 `.trae/skills/xlpa`，更新 SKILL.md、manifest、agents/openai.yaml 和 tools 路径，并验证资源包 requiredFiles 全部存在
- [x] 1.3 更新 `mcp_server/mcp_client.py` 分发客户端路径到 `xlpa/tools/mcp_client.py`，并验证本机备用客户端入口能定位文件
- [x] 1.4 更新 access/showcase/README/部署文档中的入口名称和使用说明，并用全文搜索验证无过期 `/pca` 主入口说明残留
- [x] 1.5 更新 OpenSpec 主规格命名语义或相关引用，并运行 `openspec validate --strict` 验证规划一致性

## 2. 版本与资源包治理

- [x] 2.1 新增 MCP Server 版本配置事实源，并验证 `list_mcp_tools` 不再硬编码 server version
- [x] 2.2 保持 Agent 资源包版本以 package manifest 为事实源，并验证 `list_mcp_tools`、access 页面和 XLPA 前置检查展示一致版本信息
- [x] 2.3 更新资源包 manifest 的名称、skills 列表、requiredFiles 和 XLPA 模板/工具声明，并验证 `_validate_package_manifest` 通过
- [x] 2.4 实现资源包更新后的备份清理规则：manifest 校验失败保留备份，用户确认新版可用后删除不可复用备份，并用单元或脚本测试覆盖两种分支
- [x] 2.5 实现产物分类清理策略，仅删除 temp/sensitive_temp，保留输入、结果、审计、补偿和可复用缓存，并用样例产物清单验证行为

## 3. MCP Token 与云端写权限重构

- [x] 3.1 实现 `.token_registry.json` v2 user-only schema 加载、保存和旧版迁移备份，并用旧 v1 样例验证所有 token 迁移后 accessLevel 均为 user
- [x] 3.2 修改 TokenManager 和 AuthMiddleware，使 localhost/本机 IP 不再自动获得 system 权限，并用本机和远程来源模拟验证 accessLevel 均为 user
- [x] 3.3 新增本地超级账号配置读取逻辑，优先支持 login 返回的稳定 userId，必要时兼容 phone，并用样例配置验证命中/未命中分支
- [x] 3.4 新增或调整业务 Token 缓存逻辑，使 `login(phoneNum, code)` 结果可复用且失效时可清理，并用认证失效响应验证缓存失效处理
- [x] 3.5 改造云端写权限检查，使写工具只在业务账号命中超级账号表且用户确认后可执行，并用只读账号/超级账号两类场景验证
- [x] 3.6 更新 `list_mcp_tools` 能力矩阵字段，区分 MCP 接入、云端只读、云端写入、边缘建档 dry-run 和边缘建档写入，并验证返回 JSON 可被 Skill 使用

## 4. 边缘建档客户端与核心模型

- [x] 4.1 新增 `EdgeDeviceClient`，实现 `getRSAKey`、RSA 登录、loginStr 保存、五头签名和统一 `rtnCode` 响应归一化，并用 175 测试环境或 mock 验证登录链路
- [x] 4.2 为 EdgeDeviceClient 增加 per-call timeout 和联通类三态归一化，验证 NOT_CONFIGURED、OFFLINE_TIMEOUT、OK 三种结果
- [x] 4.3 新增建档核心模型：任务配置、拓扑节点、profile 字段、dry-run 计划、执行结果、补偿清单，并用类型/序列化测试验证结构稳定
- [x] 4.4 实现转换通讯地址函数：去掉第 1、2、7 位并在中间补 3 个 0，验证 `224356000099 -> 435600000099` 和非法输入错误

## 5. Excel 模板与 Profile 架构

- [x] 5.1 设计并生成 XLPA 自动建档 Excel 模板，包含任务配置、拓扑总览、网关明细、XLBA 电表明细和字典说明，并用 openpyxl 回读验证 sheet 与列存在
- [x] 5.2 实现 Excel reader，解析 edge_base_url、loginName、password、超时、下发/召测开关、节点键、父节点键、deviceId、roadNo、identifier 和 deviceAddress，并用缺列/非法值样例验证错误输出
- [x] 5.3 实现 profile base/registry，支持字段 target 分类：base_field、extInfos、data_item、derived，并验证未知 deviceTypeId 报可读错误
- [x] 5.4 实现 8163 网关 profile，校验 proxyCommType 来源优先级（网关明细值 > 任务默认值 > dry-run 错误），并验证缺失时阻止联通类计划
- [x] 5.5 实现 XLBA 电表 profile，生成 itemId=20200002 的 itemBody 字段结构，并验证 roadNo、commAddr、protocolCode 等字段映射
- [x] 5.6 为虚拟网关保留 profile 扩展占位，并验证当前使用虚拟网关时提示二期实现而非错误映射到其他类型

## 6. 自动建档计划、执行与补偿

- [x] 6.1 实现 `read_device_archive_template` 原子工具，验证返回内容包含脱敏后的任务配置和结构化校验结果
- [x] 6.2 实现 `plan_device_archive` 原子工具，基于现有设备树和 Excel intent 生成创建、更新、跳过和冲突计划，并验证首次新建和复跑场景
- [x] 6.3 实现以 `deviceId + roadNo` 为优先键的幂等匹配，保留节点键用于首跑建树和结果映射，并用样例 Excel 验证匹配行为
- [x] 6.4 实现 `edge_upsert_device`、`edge_mount_device`、`edge_get_device_tree`、`edge_get_device_list` 原子工具，并用 mock 或 175 测试验证 create/update/mount/read 返回结构
- [x] 6.5 实现 `edge_set_device_param`、`edge_get_online_status`、`edge_call_device_data` 原子工具，验证下发审计提示、可配置超时和三态归一化
- [x] 6.6 实现补偿清单记录，至少记录本次新建设备节点键、deviceId、设备名和 deleteDevice payload，并用失败模拟验证清单完整
- [x] 6.7 实现 `edge_apply_compensation_plan` 确认式清理工具，按叶子到父节点顺序删除补偿清单内本次新建设备，并用回读验证不删除清单外设备

## 7. XLPA Skill 编排与 MODBUS 衔接

- [x] 7.1 更新 XLPA 入口 Skill 前置检查，展示新版能力矩阵、版本信息、云端登录状态、云端写权限和边缘建档任务状态，并用示例输出验证文案
- [x] 7.2 更新 MODBUS Skill 权限判断，云端写入只由业务登录账号命中超级账号表决定，并验证普通账号不展示平台同步确认
- [x] 7.3 在 MODBUS 转换完成后增加可选自动建档衔接，提示用户提供/生成 Excel 模板并先执行 dry-run，验证跳过时保留可复用产物
- [x] 7.4 编写自动建档 Skill 流程：读取模板、生成计划、展示冲突、请求确认、执行原子工具、可选下发、可选召测、输出报告和补偿清单，并用样例任务跑通 dry-run
- [x] 7.5 确保所有 Skill 输出对 password、token、登录响应脱敏，并用包含敏感字段的样例验证输出不泄露明文

## 8. Showcase、Access 与整体数据更新

- [x] 8.1 更新 access 页面，展示 XLPA 资源包、user-only MCP Token、云端写权限来源和 IPv4 接入信息，并用浏览器或静态检查验证文本
- [x] 8.2 更新 showcase 页面，使用平台真实数据或最近成功缓存替代演示假数据，并展示数据来源、更新时间和失败降级状态
- [x] 8.3 更新整体数据展示：工具数量来自 `TOOL_DEFINITIONS`/`list_mcp_tools`，资源包版本来自 manifest，协议/品牌/设备类型来自平台查询或缓存，并用接口输出验证

## 9. 测试与验收

- [x] 9.1 增加转换地址、Excel reader、profile registry、Token Registry 迁移、权限矩阵、EdgeDeviceClient 响应归一化和补偿清理的自动化测试，并验证测试全部通过
- [x] 9.2 使用 175 测试环境或等价 mock 跑自动建档 dry-run、创建/挂载、proxyCommType 校验、下发超时和补偿清理的端到端验证，并保留脱敏报告
- [x] 9.3 回归验证 `list_mcp_tools`、登录、云端只读、云端写权限拒绝/允许、资源包下载、备用 MCP 客户端路径和 access-info 输出
- [x] 9.4 运行 `openspec validate --strict`，确认所有 delta spec 与任务状态可通过校验
- [x] 9.5 完成实现后更新任务勾选状态，并在最终交付摘要中列出保留产物、清理产物、未验证项和下一步建议
