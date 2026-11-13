## Why

MCP 工具结果过大时，CLI 会自动落盘为 `<persisted-output>` 文件并把路径交给
模型。实测会话中 `read_device_archive_template` 的 70KB 结果、
`plan_device_archive` 的计划文件和 `get_function_type_list` 全量列表分别位于：

- `%TEMP%/qoder-mcp-outputs/...`
- `~/.qoder-cn/tmp/<project>/tool-outputs/session-.../...`

当前 Read 白名单只有会话工作区与技能目录，这些路径被判越界，模型无法读取
大结果，只能改用几十次分页查询（单会话出现 30 次 `get_function_type_list`，
单轮耗时 303 秒/242 秒），并在界面上出现“操作被禁止: Read”红卡。

## What Changes

- Read 白名单新增**额外目录**配置：默认自动包含上述两个 CLI 落盘目录，
  并支持 `WEBCHAT_READ_EXTRA_ROOTS`（逗号/分号分隔）继续追加。
- 仍保持白名单语义（Fail-Closed）：仓库密钥、事件库、其他会话工作区与
  系统敏感目录继续拒绝；不改为全盘可读的默认放行模式。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `agent-runtime-session`: 内置 Read 白名单扩展为“工作区 + 技能目录 +
  配置的额外目录”，默认含 CLI 大结果落盘目录。
