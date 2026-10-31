# conversion-execution-sandbox Specification

## Purpose

定义服务端转换执行能力的行为契约：6 个 exec 类 MCP 工具（配置校验、测试数据
生成、沙箱执行、报告查询、配置保存、打包）、"固定代码 + 不可信数据"的沙箱
执行纪律、产物的归属隔离与限期保留、测试门控打包、引擎单一事实源。本能力由
mcp_server 提供，Web（webchat 回环 /mcp）与 IDE 经同一工具面调用；webchat 侧
零代码改动（exec 不属 C4 写入集）。

## Requirements

### Requirement: 转换执行能力必须以 MCP 工具形式提供且 user 级可用

服务端 MUST 提供 6 个执行类 MCP 工具：`validate_config_format`（配置结构校验）、
`generate_test_data`（测试输入生成）、`execute_conversion_test`（沙箱执行转换
测试）、`get_test_report`（测试报告查询）、`save_conversion_config`（配置保存）、
`pack_bundle`（打包分发）。工具 MUST 注册进服务端工具清单（type=exec），user 级
接入凭据即可调用（不依赖云端超级账号、不依赖边缘任务凭据）；Web 会话经
HTTP 回环 `/mcp` 与 IDE 经原生 MCP 调用同一工具面，行为 MUST 一致。exec 类
工具 MUST NOT 进入写入门禁的写入集（无平台写副作用，无需逐次确认）。

#### Scenario: Web 会话调用执行类工具

- **WHEN** Web 会话的 agent 经 `/mcp` 回环以 user 级凭据调用
  `execute_conversion_test`
- **THEN** 工具正常执行并返回结构化结果，写入门禁不拦截（非写入集）
- **THEN** IDE 以相同参数调用得到相同结果

#### Scenario: 工具清单增量

- **WHEN** 调用 `list_mcp_tools`
- **THEN** 工具总数在既有 71 基础上增加 6 个 exec 类工具，既有工具行为不变

### Requirement: 沙箱执行必须隔离不可信数据

执行类工具 MUST 只执行**固定代码**（仓库内受版本控制的脚本：沙箱 runner 与
分发源只读母本 `protocol-conversion/scripts/protocol_converter.py` 镜像引擎），
用户输入 MUST 只作为数据进入（JSON 配置与测试输入），MUST NOT 执行用户提供的
代码或 shell 命令。子进程执行 MUST 满足：命令为参数列表（无 shell、无字符串
拼接命令行）、工作目录为**每次调用独立的临时目录且用后即清**（失败路径同样
清理）、施加单 case 与整批超时、施加输入大小与 case 数上限、施加 stdout 输出
上限。超时/超限/崩溃 MUST 显式返回该 case 失败及原因，MUST NOT 静默跳过或
拖垮服务进程。

#### Scenario: 病态输入不拖垮服务

- **WHEN** 一条测试输入触发引擎超时或输出超限
- **THEN** 该 case 标记失败并返回原因摘要，同批其余 case 继续执行，服务进程
  不受影响

#### Scenario: 临时目录用后即清

- **WHEN** 一次沙箱执行结束（无论成败）
- **THEN** 其独立临时目录被删除，不在磁盘残留

#### Scenario: 引擎缺失显式报错

- **WHEN** 分发源镜像引擎文件缺失时调用执行类工具
- **THEN** 返回明确的"引擎不可用"错误，服务不崩溃，其余工具不受影响

### Requirement: 配置校验必须覆盖三种转换契约且不执行配置

`validate_config_format` MUST 支持 MQTT（`platform_name` + `mappings[]`）、
HTTP（`base_url` + `token{}` + `apis[].data_mappings[]`）与 Modbus（根字段
prtlType/modelNum/classNum/taskList/labelList、read 必填、data_type/data_order
枚举）三种契约的结构校验；校验 MUST 产出结构化结果（每条错误含路径与原因），
MUST NOT 执行配置内容。`generate_test_data` 与 `execute_conversion_test`
MUST 仅支持 MQTT→MQTT 与 HTTP→MQTT 方向；对 Modbus 方向 MUST 返回明确的
"不支持"错误（Modbus 测试维持技能层静态契约校验 + 离线算例口径）。

#### Scenario: 非法配置显式列错

- **WHEN** 提交缺少必填字段或枚举值非法的 MQTT 配置
- **THEN** 返回 ok=false 与逐条错误（含规则索引/路径与原因），不进入沙箱执行

#### Scenario: Modbus 方向显式拒绝

- **WHEN** 对 `modbus_to_internal` 调用 `execute_conversion_test`
- **THEN** 返回明确的"不支持该方向的沙箱执行"错误，提示使用静态契约校验

### Requirement: 测试执行必须产出结构化报告并可按归属查询

`execute_conversion_test` MUST 对每条 test_case（name/input/可选 expected）在
沙箱中执行镜像引擎并记录结果；有 expected 时 MUST 深度对比（含类型），无
expected 时 MUST 返回实际输出；聚合报告 MUST 含 test_run_id、总数、通过/失败/
跳过计数与逐条结果（失败含错误与输出摘要，截断保护）。报告 MUST 持久化并按
owner 归属隔离（短 TTL 保留）；`get_test_report` MUST 校验归属后返回报告，
越权查询 MUST 拒绝且不泄漏报告存在性。

#### Scenario: 端到端测试报告

- **WHEN** 提交合法配置与 3 条含 expected 的测试用例（2 对 1 错）
- **THEN** 返回报告中 passed=2、failed=1，失败条目含差异说明；凭 test_run_id
  可再次查询到同一报告

#### Scenario: 越权查询被拒

- **WHEN** 以他人归属的凭据查询某 test_run_id
- **THEN** 返回不存在/无权限语义，不泄漏报告存在性

### Requirement: 配置保存与打包必须按归属隔离并限期保留

`save_conversion_config` MUST 先通过配置校验（不合法拒绝保存），将配置 JSON
按 owner 归属存入产物存储（既有快照存储语义：归属隔离、30 天 TTL），返回
file_id 与既有票据下载端点信息；`pack_bundle` MUST 校验测试报告状态为
**passed** 才打包（未通过 MUST 拒绝），ZIP MUST 包含 config.json、
mapping_report.md、test_report.json、manifest.json（含各文件 SHA256 清单）与
README.md，并按同一归属隔离与 TTL 存储。越权读取 MUST 被存储层归属校验拒绝。

#### Scenario: 保存合法配置

- **WHEN** 提交校验通过的配置与名称调用 `save_conversion_config`
- **THEN** 返回 file_id，凭既有票据下载端点可取回相同内容的 JSON

#### Scenario: 测试未通过拒绝打包

- **WHEN** 提交 status 非 passed 的测试报告调用 `pack_bundle`
- **THEN** 返回明确的门控拒绝与原因，不产生 ZIP

#### Scenario: 打包产物完整可溯源

- **WHEN** 打包成功后下载 ZIP 并解包
- **THEN** 目录结构与文件齐全，manifest 含每个文件的 SHA256，且与实际文件
  校验和一致

### Requirement: 引擎必须保持单一事实源

执行类工具引用的镜像引擎 MUST 是分发源只读母本
（`agent_assets/skills/protocol-conversion/scripts/protocol_converter.py`），
MUST NOT 在 mcp_server 内维护引擎副本；服务启动时 MUST 校验引擎文件存在。
引擎版本随 Agent 资源包升级自动跟随，工具与资源包 MUST 在同一变更中交付
（避免工具与引擎版本错配窗口）。

#### Scenario: 资源包升级引擎自动跟随

- **WHEN** Agent 资源包升级带来 protocol-conversion 引擎更新
- **THEN** 执行类工具在服务重启后使用新版引擎，无需工具侧代码改动

#### Scenario: 引擎缺失启动校验

- **WHEN** 服务启动时分发源引擎文件不存在
- **THEN** 记录明确告警，执行类工具返回"引擎不可用"，其余工具面不受影响
