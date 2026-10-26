## MODIFIED Requirements

### Requirement: 用户可见接入信息必须使用 IPv4
系统 SHALL 在接入页面、配置片段、Skills 下载链接和 `/pca` 输出中优先使用 IPv4 地址，并 SHALL NOT 在用户可复制的接入配置中生成 IPv6 地址；服务端内部可以继续识别 IPv6 localhost 以保持兼容。

#### Scenario: 生成接入配置
- **WHEN** 系统为用户生成 MCP 接入配置或 Skills 下载链接
- **THEN** 配置中的 URL 必须使用 `127.0.0.1`、`localhost` 或局域网 IPv4 地址
- **THEN** 配置中不得出现形如 `[::1]` 或包含冒号分段的 IPv6 主机地址

#### Scenario: 服务器检测到 IPv6 localhost
- **WHEN** 请求来源为 IPv6 localhost
- **THEN** 系统可以按 localhost 判定权限
- **THEN** 系统对用户展示或复制的 baseUrl 仍必须使用 IPv4 或 `localhost` 表达

#### Scenario: 为 Qoder 生成接入配置
- **WHEN** 用户在接入页选择 Qoder 并生成 MCP 接入配置
- **THEN** 配置中的 URL 必须使用 `127.0.0.1`、`localhost` 或局域网 IPv4 地址
- **THEN** Qoder 配置必须使用 `mcpServers` 根键、`url` 字段和 `headers.Authorization` 字段
- **THEN** Qoder 配置不得包含 `type` 字段

### Requirement: PCA 入口输出必须给出用户可执行下一步
系统 SHALL 在 `/pca` 前置检查和任一子流程结束时输出用户可执行的下一步建议，且建议必须与当前登录状态、权限级别、版本状态、产物状态和用户选择一致。

#### Scenario: 本地配置已生成但未同步平台
- **WHEN** 协议转换流程生成本地 JSON 且用户未确认平台同步
- **THEN** `/pca` 汇总输出必须说明本地文件路径、平台同步未执行、未调用写入工具
- **THEN** `/pca` 必须给出后续可选操作，例如测试验证、打包分发或在 system 权限下同步平台

#### Scenario: 当前权限为 user
- **WHEN** 当前 MCP `access_level` 为 `user`
- **THEN** `/pca` 必须说明平台写入不可用
- **THEN** `/pca` 不得展示平台新增或平台同步的确认选项
- **THEN** 如用户请求写入或同步，系统必须提示需要在服务器本机以 system 权限执行

#### Scenario: 当前存在可选更新
- **WHEN** 前置检查发现本地 Agent 资源包落后于远端但当前任务可继续
- **THEN** `/pca` 必须将更新作为可选下一步展示
- **THEN** `/pca` 不得用更新提示阻塞当前已可执行的只读查询或本地生成流程

#### Scenario: 接入页生成平台配置
- **WHEN** 用户通过接入页为目标平台生成接入配置
- **THEN** 页面必须给出复制或下载该配置的下一步操作
- **THEN** 切换目标平台后下一步提示必须与当前平台一致
