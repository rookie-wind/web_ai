# web-chat-ui Delta

## ADDED Requirements

### Requirement: 输入区必须提示可选路由前缀且不得强制

前端输入区 MUST 以提示文案说明可选路由前缀：`/web` 强制网页检索、`/xlpa`
强制协议助手，并说明不带前缀时自动判断。提示 MUST NOT 要求用户每次输入都携带
前缀；前端 MUST NOT 把 `/` 当作必须的命令入口，MUST NOT 拦截或改写用户输入，
MUST NOT 新增会改变会话模式的开关。前缀的识别与剥离由 Agent 侧完成。

#### Scenario: 用户直接输入不带前缀

- **WHEN** 用户在输入框输入普通任务且不带 `/web` 或 `/xlpa`
- **THEN** 消息按原样发送，由 Agent 自动判定路由

#### Scenario: 用户使用可选前缀

- **WHEN** 用户在输入框以 `/web` 或 `/xlpa` 开头输入任务
- **THEN** 前端原样发送该文本，不做拦截或改写；Agent 识别前缀并强制本次路由

#### Scenario: 输入提示不构成强制

- **WHEN** 用户查看输入区提示
- **THEN** 提示只说明前缀为可选项，不出现"必须使用前缀"的要求
