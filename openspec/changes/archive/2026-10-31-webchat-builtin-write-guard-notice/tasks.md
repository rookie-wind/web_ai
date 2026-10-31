## 1. 事件与渲染分级

- [x] 1.1 `grants.py`：`_deny` 支持可选 `guard`，内置写入路径/扩展名拒绝传
  `builtin_write_path`；验证 pytest：护栏拒绝 payload 带 guard，平台写入拒绝不带。
- [x] 1.2 `static/js/app.js`：`guard=builtin_write_path` 降级为一行弱提示并按会话聚合
  计数；平台写入/登录禁止卡渲染不变；验证静态标记断言通过。
- [x] 1.3 `static/app.css`：新增 `.guard-line` 弱样式；验证静态资源可取。

## 2. 回归

- [x] 2.1 webchat 全量 pytest 全绿（145 passed）；mcp_server 零改动。
- [x] 2.2 `openspec validate --all --strict` 通过后归档本变更。
