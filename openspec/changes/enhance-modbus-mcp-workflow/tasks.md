## 1. MCP 后端原子工具基础

- [ ] 1.1 在 `mcp_server/requirements.txt` 增加 `httpx>=0.27.0`，并通过 `pip install -r mcp_server/requirements.txt` 验证依赖可安装
- [ ] 1.2 新增 `mcp_server/api_client.py`，实现 `ProtocolApiClient` 的异步 JSON 请求、文件请求、Token 请求头、超时和错误归一化，并用静态类型检查或导入测试验证模块可加载
- [ ] 1.3 在 `api_client.py` 中实现统一返回结构，验证网络错误、HTTP 错误、后端非 `20000`、认证错误和成功响应能区分 `error` 与 `empty`
- [ ] 1.4 在 `mcp_server/server.py` 注册 `login`、大类、设备类型、品牌、型号、规约信息、数据项、脚本相关原子工具，并通过 `list_mcp_tools` 验证工具名称、类型和说明可见
- [ ] 1.5 保留 MCP 接入 Bearer Token 鉴权，并验证后端业务 Token 只作为工具参数传入后端 API，不替代 MCP 接入 Token

## 2. 权限与写入保护

- [ ] 2.1 将所有写入类工具标记为 `write`，覆盖 `add_*`、`update_*`、`del_*`、`save_*`、`upload_protocol_file`、`gen_script`，并通过工具清单验证分类正确
- [ ] 2.2 为写入类工具统一接入系统级权限检查，验证普通用户调用任一写入工具返回 `FORBIDDEN`
- [ ] 2.3 验证系统级用户可以调用写入工具，但工具只返回后端实际结果，不在服务端自动重试
- [ ] 2.4 验证查询工具在普通用户和系统级用户下均可调用，并且查询失败不会返回空结果伪装成不存在

## 3. MODBUS Skill 工具编排文档

- [ ] 3.1 更新 `.trae/skills/modbus-conversion/SKILL.md` 的 MCP 工具章节，移除或标记废弃 5 个示例高阶工具名，并验证文档中不再把它们作为实际调用工具
- [ ] 3.2 在 MODBUS Skill 中新增原子工具映射表，列明 `list_mcp_tools`、`login`、查询工具、条件写入工具、平台同步工具的调用目的和触发条件，并由人工阅读验证无缺项
- [ ] 3.3 在 MODBUS Skill 启动流程中加入 `login(phoneNum, code)` 询问规则，并验证未提供登录信息时文档明确要求仅使用本地 `references`
- [ ] 3.4 在 MODBUS Skill 中加入 Token 隔离说明，并验证文档明确区分 MCP 接入 Token 与后端业务 Token

## 4. MODBUS 参数查询与本地兜底

- [ ] 4.1 更新 `modelNum` 获取规则：优先 `get_device_type_list`，取 `deviceTypeCode`；字段缺失或为空时回退本地 references 或询问用户，并通过文档审查验证规则存在
- [ ] 4.2 更新 `classNum` 获取规则：优先 `get_classify_list` 获取大类编号；字段缺失或为空时回退本地 references 或询问用户，并通过文档审查验证规则存在
- [ ] 4.3 更新品牌、型号、数据项/原子标签查询规则，验证文档明确“优先查询、命中复用、为空可推荐、失败不新增”
- [ ] 4.4 新增参数来源标记规则，验证最终确认表要求标注 `MCP:<tool>.<field>`、`references:<file>` 或 `user`
- [ ] 4.5 新增缺失项清单规则，验证任一必需参数无法确认时文档要求停止生成最终 JSON

## 5. 数据项与基础信息新增

- [ ] 5.1 在 MODBUS Skill 中明确原子标签查询对应数据项管理工具，并通过文档审查验证使用 `get_data_item_list` 作为查询入口
- [ ] 5.2 在 MODBUS Skill 中明确 `add_data_item` 首期只新增数据项/原子标签基础信息，并验证不要求写入寄存器地址、功能码、数据类型、字节序、表达式或枚举映射
- [ ] 5.3 增加系统级用户新增基础信息的交互：用户提供或本地推荐、用户确认新增内容、再询问是否新增到平台，并通过文档审查验证三步齐全

## 6. 本地 JSON 生成与平台同步

- [ ] 6.1 在 MODBUS Skill 中新增生成前最终确认表，验证表中包含品牌、设备类型、classNum、modelNum、协议类型、采集数据项、原子标签、寄存器地址、功能码、data_type、data_order、data_exprs、来源和待确认项
- [ ] 6.2 保持默认先生成本地 `output/{品牌}_{设备类型}_{日期}.json`，并验证用户未确认前不会触发平台同步说明
- [ ] 6.3 新增平台同步二阶段流程：用户确认本地 JSON 后询问是否同步平台；确认后展示同步计划；再次确认后调用写入工具，并通过文档审查验证流程存在
- [ ] 6.4 明确 MODBUS 首期不调用删除类 MCP 工具，并验证工具计划中不包含 `del_classify`、`del_device_type`、`del_brand`、`del_model`、`del_protocol_info`、`del_data_item`、`del_script`、`del_protocol_file`

## 7. 验证与回归

- [ ] 7.1 使用 `openspec validate enhance-modbus-mcp-workflow --strict` 验证 OpenSpec 工件通过校验
- [ ] 7.2 启动 MCP Server 后调用 `list_mcp_tools`，验证 MODBUS 首期需要的工具可见且类型正确
- [ ] 7.3 手动验证未提供登录信息场景：Skill 只使用本地 references，并在输出中标注来源
- [ ] 7.4 手动验证 MCP 查询命中、查询为空、查询失败三类场景，确认 Skill 分别执行命中复用、本地推荐/用户提供、错误展示且不新增
- [ ] 7.5 手动验证普通用户遇到新增或平台同步时停止并提示系统级用户
- [ ] 7.6 手动验证系统级用户写入前展示计划、写入后展示返回值、失败后不自动重试
- [ ] 7.7 手动验证本地 JSON 生成后，未确认同步平台时不调用 `upload_protocol_file`、`add_protocol_info`、`gen_script`
