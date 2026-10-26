# showcase-stats-persistence Specification

## Purpose

使 showcase 页面展示的运行数据（配置数量、测试数量、品牌/设备类型数量）从本地持久化计数、服务端回归报告和平台实时查询中动态获取，消除硬编码。

## Requirements

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

### Requirement: 回归测试数通过服务端完整回归运行获取
系统 SHALL 在服务启动后通过独立后台线程对 `mcp_server/tests` 全量测试套件运行服务端回归，解析结构化结果获取测试总数、通过数和失败数，并 SHALL 将结果保存到与服务事件计数分离的独立回归报告文件。

#### Scenario: 启动后台运行回归
- **WHEN** MCP Server 启动完成初始化阶段
- **THEN** 系统必须在独立线程中运行 `mcp_server/tests` 全量回归，不接受筛选或提前停止
- **THEN** 系统必须解析结果获取 test_total、test_passed、test_failed 数量
- **THEN** 结果必须写入独立的服务端回归报告文件，不覆盖业务事件计数

#### Scenario: 回归运行中或异常
- **WHEN** 回归正在运行、测试目录缺失或运行被中断
- **THEN** 系统必须分别以 RUNNING、UNAVAILABLE 或 INTERRUPTED 状态呈现，并保留上次有效计数或报告不可用
- **THEN** 不得把部分或过期的测试结果当作本次完整结果展示
- **THEN** 不得阻塞服务正常启动

#### Scenario: showcase 展示测试数
- **WHEN** 前端请求 /api/showcase/data
- **THEN** 响应必须包含 testTotal 字段取自服务端回归报告

### Requirement: 品牌与设备类型数从平台 API 实时查询
showcase 中"覆盖设备品牌"和"覆盖设备类型"SHALL 来自 /api/showcase/data 端点对平台接口的实时调用结果，不硬编码。

#### Scenario: 平台可用时展示实时数据
- **WHEN** 前端请求 /api/showcase/data 且 system_token 有效
- **THEN** 系统必须调用 get_brand_list 获取品牌总数
- **THEN** 系统必须调用 get_device_type_list 获取设备类型总数
- **THEN** 响应中 brandCount / deviceTypeCount 为平台实际数值
- **THEN** dataSource 字段必须为 "live"，并把成功结果写入本地缓存

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

### Requirement: 统计与缓存文件为本地运行态文件
.stats.json、服务端回归报告和 showcase 平台统计缓存 MUST 在 .gitignore 中排除，MUST 不出现在 Agent 资源包中。

#### Scenario: 版本控制排除
- **WHEN** 上述运行态文件存在
- **THEN** 不得被 git 跟踪

#### Scenario: 资源包排除
- **WHEN** 导出 Agent 资源包
- **THEN** ZIP 不得包含这些运行态文件
