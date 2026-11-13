## 1. 配置与运行时

- [x] 1.1 `config.py` 新增 `DEFAULT_CLI_READ_ROOTS` 与 `read_extra_roots`；
  `WEBCHAT_READ_EXTRA_ROOTS` 追加（逗号/分号、支持 `~`/`%VAR%`）。
- [x] 1.2 `runtime.py` 在 Read 白名单中追加 `read_extra_roots`；
  `api.py` 注入配置。
- [x] 1.3 README 补充配置项与 Read 边界说明。

## 2. 验证

- [x] 2.1 单测：默认根包含 `qoder-mcp-outputs` 与 `.qoder-cn/tmp`；环境变量
  可追加多个目录。
- [x] 2.2 运行时装配：额外根内的文件可读，工作区外普通文件仍拒绝。
- [x] 2.3 真实路径校验：
  - `%TEMP%/qoder-mcp-outputs/...` → allow
  - `~/.qoder-cn/tmp/.../tool-outputs/...` → allow
  - `_ac_local.env`、`webchat_data/events/*.jsonl`、其他会话工作区 → deny
- [x] 2.4 webchat 全量：**183 passed, 0 failed**。
- [x] 2.5 `openspec validate --all --strict` 通过后归档。
