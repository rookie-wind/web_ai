## Purpose

使 showcase 页面展示的运行数据（配置数量、测试数量、品牌/设备类型数量）从本地持久化计数和平台实时查询中动态获取，消除硬编码。

## ADDED Requirements

### Requirement: 已生成配置数通过事件计数持久化
系统 SHALL 维护 .stats.json 文件记录已生成转换配置总数，初始值为 19，每次 gen_script 工具成功执行后计数 +1 并落盘。

#### Scenario: 服务启动加载计数
- **WHEN** MCP Server 启动
- **THEN** 系统必须从 .stats.json 读取 scripts_generated 计数
- **THEN** 文件不存在时必须以初始值 19 创建

#### Scenario: gen_script 成功后递增
- **WHEN** gen_script 工具执行成功返回结果
- **THEN** 系统必须将 scripts_generated 计数 +1
- **THEN** 系统必须立即写入 .stats.json 确保持久化

#### Scenario: showcase 展示配置数
- **WHEN** 前端请求 /api/showcase/data
- **THEN** 响应必须包含 scriptsGenerated 字段取自 .stats.json

### Requirement: 回归测试数通过启动时运行获取
系统 SHALL 在服务启动时运行 test_protocol_converter.py 测试套件，解析结果获取测试总数并记录到 .stats.json。

#### Scenario: 启动运行测试
- **WHEN** MCP Server 启动完成初始化阶段
- **THEN** 系统必须同步执行 test_protocol_converter.py（允许数秒延迟）
- **THEN** 系统必须解析输出获取 test_total、test_passed、test_failed 数量
- **THEN** 结果必须写入 .stats.json

#### Scenario: 测试脚本不存在或执行异常
- **WHEN** test_protocol_converter.py 文件缺失或运行超时
- **THEN** 系统必须记录错误日志
- **THEN** .stats.json 的 test_total 保持上次值或为 0
- **THEN** 不得阻塞服务正常启动

#### Scenario: showcase 展示测试数
- **WHEN** 前端请求 /api/showcase/data
- **THEN** 响应必须包含 testTotal 字段取自 .stats.json

### Requirement: 品牌与设备类型数从平台 API 实时查询
showcase 中"覆盖设备品牌"和"覆盖设备类型"SHALL 来自 /api/showcase/data 端点对平台接口的实时调用结果，不硬编码。

#### Scenario: 平台可用时展示实时数据
- **WHEN** 前端请求 /api/showcase/data 且 system_token 有效
- **THEN** 系统必须调用 get_brand_list 获取品牌总数
- **THEN** 系统必须调用 get_device_type_list 获取设备类型总数
- **THEN** 响应中 brandCount / deviceTypeCount 为平台实际数值
- **THEN** dataSource 字段必须为 "live"

#### Scenario: 平台不可用时降级
- **WHEN** 前端请求 /api/showcase/data 且 system_token 无效
- **THEN** 系统必须返回缓存数据（如有）并标记 dataSource 为 "cache"
- **THEN** 无缓存时 brandCount / deviceTypeCount 返回 null 并标记 dataSource 为 "static"

### Requirement: showcase 前端动态渲染统计数值
showcase.html 的 delivery.stats 区域 SHALL 通过调用 /api/showcase/data 动态填充数值，不得硬编码具体数字。

#### Scenario: 页面加载更新数据
- **WHEN** 用户打开 showcase 页面
- **THEN** 前端必须 fetch /api/showcase/data
- **THEN** delivery.stats 四项数值必须用响应数据覆盖渲染
- **THEN** 数据来源标记（live/cache/static）必须展示

### Requirement: .stats.json 为本地运行态文件
.stats.json MUST 在 .gitignore 中排除，MUST 不出现在 Agent 资源包中。

#### Scenario: 版本控制排除
- **WHEN** .stats.json 存在
- **THEN** 不得被 git 跟踪

#### Scenario: 资源包排除
- **WHEN** 导出 Agent 资源包
- **THEN** ZIP 不得包含 .stats.json
