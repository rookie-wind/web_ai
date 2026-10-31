## Why

C4（write-gate-isolation）一期禁用命令执行后，Web 会话没有 Bash，无法执行协议转换
流程中"跑测试脚本、打 ZIP"两个环节——L3（协议转换）在 Web 端断裂：配置能生成、
能确认写入，但测试验证只能"AI 手动模拟转换逻辑"（`test-validation/SKILL.md`
Phase 3 明确"当前无 C 引擎可执行"），打包只能"AI 生成文件列表，用户手动打包"
（`pack-distribution/SKILL.md`）。两个 SKILL.md 中的「调用的 MCP 工具（MCP 就绪
后）」表格自 0.1 版起标注"待开发"，至今未落地。

架构方案（`web-chat-agent-runtime-solution.md` D7/Phase 3）为此明确的后续工作：
服务端补 6 个执行类工具——`validate_config_format`、`generate_test_data`、
`execute_conversion_test`、`get_test_report`、`save_conversion_config`（此 5 个已在
`test-validation/SKILL.md` 规划并写明"在沙箱中执行"）+ 打包工具（pack-distribution
规划 `pack_bundle`）。C5 已交付产物与上传闭环，本变更（C6）补齐执行与打包，
使 L3 在 Web 与 IDE 两条路径均可用。

## What Changes

- **新增 6 个 MCP 执行类工具（type=exec，user 级可用）**：配置校验、测试数据
  生成、沙箱执行转换测试、测试报告查询、配置保存、打包。注册进
  `mcp_server/server.py` 工具面（71 → 77），实现放新模块
  `mcp_server/conversion_tools.py`（仿 `edge_tools.py` 注册模式）。
- **沙箱执行纪律**：执行的是**固定代码**（分发源只读母本
  `agent_assets/skills/protocol-conversion/scripts/protocol_converter.py`，
  Python 镜像引擎），输入是**不可信数据**（用户 JSON）而非不可信代码；
  子进程 + 超时 + 每次调用独立临时目录 + 无 shell + 输入/输出大小上限，
  用后即清。
- **产物存储复用 snapshot_store 语义**：`save_conversion_config` 与 `pack_bundle`
  的产物经 `template_store` 按 owner 隔离保存（30 天 TTL），下载走既有
  `/api/archive/templates/<id>?owner=` 端点（file_id 即票据）；Web 端经 webchat
  的产物代理下载属 C5「来源 B」二期边界，本变更不涉及。
- **SKILL.md 改写**：`test-validation`（AI 手动模拟 → 工具调用）、
  `pack-distribution`（手动打包 → `pack_bundle`）、`protocol-conversion`（测试
  镜像补充 MCP 执行入口）、`xlpa`（能力矩阵/流程补执行与打包）、
  `modbus-conversion`（声明 execute 工具不适用 Modbus，维持静态契约 + 离线算例）。
- **资源包升版 0.25.0 → 0.26.0**（`package-manifest.json` + 各受改 Skill 的
  manifest/SKILL.md 版本同步 bump）。
- **webchat 零代码改动**：exec 类工具不在 C4 写入集（`classify_tool` 归为
  非写入放行），防漂移单测按 type 解析比对，type=exec 不进 write/edge_write 集，
  既有测试不受影响。
- **Modbus 边界**：`execute_conversion_test` 一期仅支持 MQTT→MQTT / HTTP→MQTT
  （Python 镜像引擎覆盖方向）；Modbus 无镜像引擎，测试维持 SKILL 层静态契约
  校验 + 离线算例（`validate_config_format` 支持 Modbus 契约的结构校验）。

## Capabilities

### New Capabilities
- `conversion-execution-sandbox`: 服务端转换执行能力——6 个 exec 类 MCP 工具、
  固定代码 + 不可信数据的沙箱执行纪律、产物归属隔离与限期保留、测试门控打包、
  引擎单一事实源（分发源只读母本）。

### Modified Capabilities
- 无。测试/打包此前仅存在于 SKILL.md 层（"AI 手动模拟"），不构成既有规格
  requirement；工具面增量不改任何既有能力的行为契约。

## Impact

- **mcp_server（代码）**：新增 `conversion_tools.py`（工具实现 + 注册函数）、
  沙箱 runner（子进程入口脚本）、报告/产物存储接入；`server.py` 注册 + 
  `TOOL_DEFINITIONS` 增 6 条（type=exec）；操作日志覆盖产物类工具。
- **agent_assets（资源包）**：5 个 SKILL.md 改写、对应 manifest.json 与 SKILL.md
  frontmatter 版本 bump、`package-manifest.json` 0.25.0 → 0.26.0。
- **webchat**：零代码改动；回归确认门禁防漂移测试全绿、exec 工具经 `/mcp`
  回环可正常调用（user 级）。
- **测试**：`mcp_server/tests/test_conversion_tools.py`（校验规则/数据生成/沙箱
  执行/超时/上限/报告/保存/打包/归属隔离）；主 pytest 基线全绿 + webchat pytest
  全绿；证据记入 `validation/conversion-execution-sandbox/`。
- **IDE 兼容**：纯增量——既有 71 工具行为不变，`list_mcp_tools` total 71 → 77；
  全量 schema 体积进一步增大（D12 意图子集收敛为后续独立优化，不在本变更）。
