## Why

现有系统仍以 `/pca` 入口、localhost/system 权限和硬编码版本为核心，无法准确表达开发阶段已确定的 XLPA 工作流、云端平台写权限模型以及边缘建档后端的独立鉴权边界。Path B 已实测打通 `:7500` 设备建档、挂载、下发、召测和清理链路，现在需要把这些事实固化为一套可扩展、可审计、可复跑的 XLPA 入口与自动建档能力。

## What Changes

- **BREAKING**: 将协议转换入口从 `pca` 一刀切改名为 `xlpa`，包括 Skill 目录、资源包清单、备用 MCP 客户端路径、用户可见入口文案和 OpenSpec 能力命名；开发阶段不保留 `/pca` wrapper。
- **BREAKING**: 取消 localhost / 本机 IP 自动授予 system 写权限；MCP 接入 Token 一律表示用户级接入能力。
- 将 `.token_registry.json` 迁移为 v2 user-only 接入 Token 注册表，不再作为平台写权限事实源；旧 registry 迁移前备份。
- 引入云端业务登录权限模型：`login(phoneNum, code)` 仅产生后端业务 Token；平台写权限由业务账号命中本地超级账号配置决定。
- 将 MCP Server 版本与 Agent 资源包版本从代码硬编码迁移到配置/manifest 事实源，并在入口、接入页、showcase 和 `list_mcp_tools` 中一致展示。
- 资源包更新成功后按校验结果和用户确认清理旧版本备份；仅删除后续不可复用的临时产物，保留输入、结果、审计和可复用缓存。
- 新增 XLPA 自动建档工作流：Excel 任务模板 + `EdgeDeviceClient` + 可扩展设备 profile + 原子 MCP 工具 + Skill 编排。
- 首期建档支持 8163 网关与 XLBA 电表，虚拟网关和更多设备类型仅预留 profile 扩展接口。
- 自动建档使用 `deviceId + roadNo` 作为幂等匹配优先键；失败时不自动回滚主流程，但提供按补偿清单删除本次新建设备的确认式工具。
- 自动建档实现已确认的转换通讯地址规则、`proxyCommType` 网关必填校验、下发审计提示、联通类三态归一化和可配置超时。

## Capabilities

### New Capabilities
- `xlpa-device-archiving-workflow`: 定义 XLPA 自动建档的 Excel 模板、边缘 `:7500` 鉴权、设备 profile、原子工具、幂等计划、补偿清理、下发/召测/通讯状态验证行为。

### Modified Capabilities
- `pca-entry-workflow`: 将入口语义迁移为 XLPA，更新前置检查、能力矩阵、登录提示、版本展示、下一步建议和用户可见命名。
- `mcp-token-management`: 将 MCP 接入 Token 迁移为 user-only registry，取消 localhost/system 权限来源，并定义 v1→v2 迁移与备份行为。
- `agent-assets-package-management`: 将资源包命名、必需文件、备用客户端路径和更新后备份清理策略迁移到 XLPA 语义，并要求版本来自 manifest/config。
- `modbus-mcp-workflow`: 更新 MODBUS 子流程在 XLPA 入口下的权限判断、平台写入授权来源和可选衔接自动建档的边界。

## Impact

- 影响 `mcp_server/server.py` 中 TokenManager、AuthMiddleware、`_check_write_permission`、`list_mcp_tools`、接入信息 API、资源包 manifest 加载/校验/打包和版本展示。
- 影响 `.trae/skills/pca` 目录、`.trae/skills/package-manifest.json`、`mcp_server/mcp_client.py`、接入页/showcase 文案和相关 OpenSpec 规格命名。
- 新增边缘建档客户端与建档模块，独立于现有 `ProtocolApiClient`；新增原子 MCP 工具和 XLPA Skill 编排文档/模板。
- 引入本地超级账号配置、业务 Token 缓存、user-only Token Registry v2、版本配置文件和资源包备份清理规则。
- 需要回归验证 MCP 接入、云端只读查询、云端写权限、资源包下载、XLPA 前置检查、MODBUS 转换、自动建档 dry-run、补偿清理和敏感信息脱敏。
