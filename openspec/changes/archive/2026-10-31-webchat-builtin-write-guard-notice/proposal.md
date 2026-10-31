## Why

内置写入放行后，模型偶尔先把文档写到 `xlpa-output/` 之外的路径，被路径护栏拒绝一次，
随后自行改写到正确目录并成功生成产物。当前前端把这类拒绝与平台写入禁止同层级渲染为
红色"操作被禁止、无法确认解除"卡片，让用户误以为触发了不可解除的策略红线；实测反馈
中用户明确认为该提示是噪声。

门禁拒绝事件与审计必须保留（可回放、可举证），但"自纠错型"路径护栏不应与
"平台写入/登录禁止"同层级展示。

## What Changes

- `gate_blocked` 事件 payload 新增可选字段 `guard`；内置写入路径/扩展名拒绝的值为
  `builtin_write_path`，其他拒绝不带该字段。
- 前端渲染分级：带 `guard=builtin_write_path` 的拒绝降级为一行灰色系统提示
  （"已拦截 N 次写入（路径不在 xlpa-output/），助手会自动改写到产物目录"），同一会话
  聚合计数，不渲染禁止卡；平台写入/登录等策略禁止保持现有红色卡片与不可确认语义。
- 拒绝逻辑、审计台账、事件持久化均不变。

## Capabilities

### Modified Capabilities

- `write-gate-isolation`: 门禁拒绝事件新增可选 `guard` 标识，并约定前端按该标识区分
  展示层级（自纠错护栏弱提示 vs 策略禁止强提示）。

## Impact

- **webchat 后端**：`grants.py` 拒绝 payload 增加可选 `guard` 字段（默认不带，存量行为不变）。
- **前端**：`static/js/app.js` 增加护栏弱提示渲染与聚合计数；`static/app.css` 增加一行样式。
- **mcp_server**：零改动。
- **测试**：门禁 payload 断言新增 `guard`；前端静态标记断言；webchat 全量回归。
