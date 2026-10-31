## ADDED Requirements

### Requirement: Web 会话运行时必须由国内版 Qoder Agent SDK 构建驱动

Web 会话运行时 MUST 由**国内版（CN）构建**的 Qoder Agent SDK 驱动（导入名
`qodercn_agent_sdk`，自带 `qoderclicn` CLI，不依赖部署环境 PATH 提供
`qodercli`）；个人访问令牌（PAT）MUST 经国内版环境变量
`QODERCN_PERSONAL_ACCESS_TOKEN` 注入，且 MUST 仅经环境变量传递、不出现在
子进程命令行。SDK 品牌为构建期常量、MUST NOT 期望以环境变量在运行时切换；
PAT 品牌与 SDK 构建品牌 MUST 一致（不一致将会话初始化握手超时）。SDK 的
模块名与类型名 MUST 限于会话运行时的适配层边界内，MUST NOT 泄漏到事件契约
模块或前端接口（沿用既有"SDK 事件类型不外泄"约束）。

#### Scenario: 国内版 PAT 注入后会话成功初始化

- **WHEN** 运维以 `QODERCN_PERSONAL_ACCESS_TOKEN` 注入有效国内版 PAT 并创建
  会话
- **THEN** 会话实例完成初始化握手（CLI 就绪），可处理用户消息并产生事件流

#### Scenario: 自带 CLI 不依赖 PATH

- **WHEN** 部署环境未在 PATH 提供 `qodercli`
- **THEN** 会话仍能启动（国内版 SDK 自带 `qoderclicn` CLI），不因缺少外部
  CLI 而失败

#### Scenario: SDK 名称限于适配层边界

- **WHEN** 检查事件契约模块与前端接口的源码/响应结构
- **THEN** 不出现国内版 SDK 的模块名（`qodercn_agent_sdk`）或其类型名作为
  契约字段
