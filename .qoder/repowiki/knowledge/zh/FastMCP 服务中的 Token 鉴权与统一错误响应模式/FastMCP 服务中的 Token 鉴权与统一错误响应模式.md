---
kind: error_handling
name: FastMCP 服务中的 Token 鉴权与统一错误响应模式
category: error_handling
scope:
    - '**'
source_files:
    - mcp_server/server.py
    - .trae/skills/protocol-conversion/scripts/protocol_converter.py
---

## 1. 采用的错误处理体系

本项目是一个基于 FastMCP + Uvicorn 的 MCP（Model Context Protocol）服务，没有独立的 `errors/` 包或自定义异常类。错误处理集中在单个文件 `mcp_server/server.py` 中，通过以下机制实现：

- **ASGI 中间件统一拦截**：`AuthMiddleware` 类在请求进入业务逻辑前校验 `Authorization: Bearer <TOKEN>`，未携带或无效时直接返回 HTTP 401。
- **工具函数内显式权限检查**：所有写入型工具（`update_protocol_file`、`add_device_class`、`publish_work_log`、`publish_converted_script`）通过 `_check_write_permission()` 检查当前上下文是否为 `system` 级别，否则返回统一的 `{error, code, message}` 字典。
- **桩工具统一占位**：未实现的工具通过 `_stub_response(tool_name)` 返回 `{status: "not_implemented", tool, message}`，作为“功能尚未实现”的错误语义。
- **启动期配置错误**：当 FastMCP 实例缺少预期的 ASGI 方法时，直接 `raise RuntimeError(...)` 终止进程。

## 2. 关键文件与位置

- `mcp_server/server.py`：唯一承载错误处理的文件，包含 `TokenManager`、`AuthMiddleware`、`CompositeApp`、工具函数及辅助方法。
- `.trae/skills/protocol-conversion/scripts/protocol_converter.py`：Skill 脚本中使用 `try/except (ValueError, TypeError, json.JSONDecodeError)` 捕获解析异常，属于下游调用方而非服务端核心。

## 3. 架构与约定

### 3.1 鉴权错误路径
`AuthMiddleware.__call__` 对每个 HTTP 请求执行：
1. 非 HTTP 类型请求直接透传。
2. 从 `scope["headers"]` 提取 `authorization`，必须以 `Bearer ` 开头。
3. 缺失或格式错误 → 调用 `_send_json(401, "Unauthorized: Bearer token required")`。
4. 调用 `token_manager.is_valid(token)` 校验，失败 → `_send_json(401, "Unauthorized: Invalid token")`。
5. 根据客户端 IP 设置 `access_level_var`（`system` / `user`）和 `source_var`，再放行到下游。

### 3.2 业务层错误模型
写入权限检查由 `_check_write_permission()` 完成，返回结构为：
```python
{
    "error": True,
    "code": "FORBIDDEN",
    "message": f"写入操作需要系统级权限...当前权限级别: {access_level}, 来源: {source}"
}
```
该结构被直接作为工具返回值返回给 MCP 调用方，而不是抛出异常——这是 MCP 工具函数的约定（返回 dict 表示结果）。

### 3.3 JSON-RPC 错误格式
`AuthMiddleware._send_json` 将鉴权失败包装为 JSON-RPC 2.0 错误体：
```json
{"jsonrpc": "2.0", "error": {"code": -32001, "message": "..."}}
```
HTTP 状态码为 401，但消息体遵循 JSON-RPC 规范，便于 MCP 客户端识别。

### 3.4 上下文变量传递错误上下文
使用 `contextvars.ContextVar` 在中间件与工具之间传递 `access_level` 和 `source`，使工具函数能感知当前请求的权限级别并据此决定返回何种错误。

## 4. 约定与约束

- **所有 MCP 工具必须返回 dict**：包括成功结果和错误结果（如 `_stub_response`、`_check_write_permission` 返回的错误字典），不抛 Python 异常。
- **写入操作必须经过 `_check_write_permission()`**：四个写入工具均先调用该方法，若返回非 None 则立即 return，不再执行业务逻辑。
- **鉴权失败统一走 `AuthMiddleware`**：所有 `/mcp` 路径的请求都必须经中间件校验，未通过即返回 401 JSON-RPC 错误；静态页面（`/`、`/access`）和文档导出接口（`/api/docs/*`）绕过鉴权。
- **启动期致命错误直接 raise**：找不到 FastMCP 的 ASGI 方法时 `raise RuntimeError(...)`，因为这是部署配置错误，不应静默失败。
- **资源缺失降级处理**：`access.html` 不存在时用 try/except FileNotFoundError 提供 fallback HTML，避免服务启动失败。
- **无全局异常处理器**：未发现 `@app.exception_handler` 或类似的全局异常捕获，未捕获的异常由 Uvicorn/FastMCP 默认处理。
- **无 panic/recover 概念**：Python 生态下不使用 panic/recover，而是依赖 try/except 和返回值约定。

## 5. 不足与观察

- 错误码仅定义了 `FORBIDDEN`（业务层）和 `-32001`（JSON-RPC 鉴权层），缺乏更丰富的错误码体系（如参数校验失败、资源不存在等）。
- 桩工具全部返回相同的 `not_implemented` 响应，无法区分具体哪个工具未实现（虽然包含 `tool` 字段）。
- 未实现结构化日志记录，错误信息通过 print 输出到控制台，不适合生产环境。
- 下游 Skill 脚本（`protocol_converter.py`）自行处理 `ValueError`、`TypeError`、`json.JSONDecodeError`，与服务端错误处理风格不一致，属于独立模块边界内的处理方式。
