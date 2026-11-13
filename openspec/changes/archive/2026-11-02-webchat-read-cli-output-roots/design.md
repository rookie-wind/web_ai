## Context

- CLI 大结果落盘路径随工具与项目变化，但根目录稳定：
  `%TEMP%/qoder-mcp-outputs`（MCP 结果溢出）与 `~/.qoder-cn/tmp`（CLI
  `tool-outputs`）。
- 只放开这两个根就能覆盖实测所有被拒路径；把整个文件系统改为可读会暴露
  事件库（内含明文凭据）、其他会话工作区、`.env` 与 MCP Token 配置。

## Decisions

### D1 白名单 + 额外根，不做默认放行

`Settings` 新增 `read_extra_roots`：

- 默认值 `DEFAULT_CLI_READ_ROOTS = (%TEMP%/qoder-mcp-outputs,
  ~/.qoder-cn/tmp)`；
- `WEBCHAT_READ_EXTRA_ROOTS` 用逗号/分号分隔追加，支持 `~` 与 `%VAR%`；
- 运行时把 `session.workspace`、`skill_catalog.root`、`read_extra_roots`
  一起传给 `WriteGate(read_roots=...)`，仍由 `check_read` 做 `resolve()` 后
  的 `is_relative_to` 校验。

### D2 保持现有拒绝项

事件库、其他会话工作区、仓库 `.env`/`permissions.json`/`mcp.json` 等仍在
白名单之外，验证脚本已确认继续拒绝。

## Risks / Trade-offs

- `%TEMP%/qoder-mcp-outputs` 与 `~/.qoder-cn/tmp` 是同一 OS 用户下的共享
  临时目录，理论上可能读到其他会话的溢出结果。它们只含工具结果，且路径名
  带工具名与哈希，实际很难被枚举；后续可在 CLI 支持时把落盘目录改到会话
  工作区内以彻底隔离。
- 未采用黑名单模式：黑名单对密钥/日志/系统目录无法穷举，默认放行风险更高。
