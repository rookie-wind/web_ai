## 1. 确认卡片前置

- [x] 1.1 `adapter.py` 追加 Web 交互系统提示（preset append），约定直接调用工具
  触发表单、不在聊天索要凭据、不引导聊天回复"确认"；验证 pytest：options 断言。
- [x] 1.2 README 记录确认/凭据交互约定。

## 2. 禁止工具结果自动生成产物

- [x] 2.1 删除 `_maybe_export_large_result`、`LARGE_RESULT_EXPORT_THRESHOLD` 与
  调用点；验证 pytest：超大工具结果不产生文件、不产 artifact 事件。
- [x] 2.2 前端截断文案去掉"可下载完整文件"；README 更新产物来源说明。

## 3. 回归

- [x] 3.1 webchat 全量 pytest 全绿（154 passed）；mcp_server 零改动。
- [x] 3.2 `openspec validate --all --strict` 通过后归档本变更。
