## ADDED Requirements

### Requirement: 新建会话必须提供账号选择对话框

前端新建会话 MUST 提供对话框供用户选择 Qoder 云账号：默认账号 或 自带 PAT；
自带 PAT 输入 MUST 掩码，MUST 提供"记住"勾选且默认不勾。提交 MUST 经既有建会话
接口携带账号选择；校验失败 MUST 展示后端给出的可辨识原因，MUST NOT 回显 PAT
明文，凭据 MUST NOT 进入 URL。默认账号不可用时 MUST 提示需自带 PAT。

#### Scenario: 选默认账号建会话

- **WHEN** 用户在新建会话对话框选择默认账号并提交
- **THEN** 创建绑定默认账号的会话

#### Scenario: 自带 PAT 掩码输入

- **WHEN** 用户选择自带账号并输入 PAT
- **THEN** 输入以掩码显示，提交后 URL 与界面不出现 PAT 明文

#### Scenario: 校验失败提示

- **WHEN** 自带 PAT 校验失败
- **THEN** 对话框展示可辨识原因，不创建会话

#### Scenario: 记住勾选

- **WHEN** 用户勾选记住并提交有效自带 PAT
- **THEN** 后端持久化该 PAT，下次新建会话预填

### Requirement: 输入区必须提供模型选择下拉

前端输入区 MUST 提供模型选择下拉，选项取自当前会话账号的启用模型清单，MUST
展示展示名与成本标记（免费/价格系数）；切换 MUST 对下一条消息生效（消息级），
MUST NOT 改变路由模式或会话模式。下拉 MUST 反映当前预选模型；账号为会话级，
MUST NOT 在会话内提供切换账号入口。

#### Scenario: 下拉呈现账号清单

- **WHEN** 会话创建完成
- **THEN** 输入区下拉列出该账号启用模型并含成本标记，预选默认模型

#### Scenario: 消息级切换模型

- **WHEN** 用户改选模型并发送消息
- **THEN** 下一条消息使用新模型，无需新建会话

#### Scenario: 切换模型不改路由模式

- **WHEN** 用户切换模型
- **THEN** `/web` 与 `/xlpa` 路由前缀语义及会话模式保持不变