---
kind: logging_system
name: 基于 print 与 Uvicorn 控制台的轻量日志输出
category: logging_system
scope:
    - '**'
source_files:
    - mcp_server/server.py
    - mcp_server/requirements.txt
---

## 1. 使用的系统/方法

本仓库**没有引入任何专用日志框架**（如 `logging`、`structlog`、`loguru`、`python-json-logger` 等）。MCP 服务器 (`mcp_server/server.py`) 的运行时输出全部通过 Python 内置的 `print()` 函数直接写入标准输出，并由底层 ASGI 服务器 **Uvicorn** 负责将 stdout 输出到进程控制台。依赖清单 (`requirements.txt`) 仅声明 `mcp>=1.0.0,<2.0.0` 与 `uvicorn>=0.30.0`，未包含任何日志库。

## 2. 关键文件

- `mcp_server/server.py`：唯一业务代码入口，集中使用 `print()` 输出启动信息、鉴权状态、工具数量等运行期信息。
- `mcp_server/requirements.txt`：依赖声明，无日志相关包。
- `.trae/skills/.../scripts/build_pack.py`、`.trae/skills/protocol-conversion/scripts/gen_test_report.py`、`.trae/skills/modbus-conversion/temp/*.py`：辅助脚本同样使用 `print()` 输出构建/测试过程信息，属于开发辅助用途。

## 3. 架构与约定

- **无日志初始化**：程序启动时不配置 logger、不设置日志级别、不注册 handler 或 formatter，也没有日志轮转、文件落盘、结构化字段等机制。
- **统一前缀约定**：所有 `print()` 调用均使用方括号包裹的级别前缀，如 `[INFO]`、`[WARNING]`，用于在纯文本控制台输出中区分消息语义。例如：
  - 启动阶段：`[INFO] MCP Server starting on http://...`、`[INFO] Admin token authentication enabled.`
  - 警告阶段：`[WARNING] MCP_AUTH_TOKEN not set - auto-generating tokens for all IPs.`
- **上下文变量承载可观测信息**：虽然未落盘为日志，但请求级上下文通过 `contextvars.ContextVar`（`access_level_var`、`source_var`）在鉴权中间件 (`AuthMiddleware`) 中注入，并在 `list_mcp_tools` 工具返回体中暴露给调用方，作为“可观测性”的替代方案。
- **Uvicorn 控制台输出**：实际部署时由 `uvicorn.run(...)` 启动，Uvicorn 自身会输出 HTTP 访问日志（取决于其默认配置），项目代码不再额外拦截或格式化。

## 4. 约定与约束

- **描述性约定**：所有面向运维/调试的控制台输出统一采用 `[LEVEL] message` 格式；当前仅观察到 `INFO` 与 `WARNING` 两种级别，未见 `ERROR`/`DEBUG` 等其它级别的使用。
- **无强制约束**：仓库中没有 lint 规则、文档或类型注解强制要求必须使用某种日志方式；现有模式是“最小实现”的自然结果——服务功能集中在 FastMCP + 自定义 ASGI 中间件，日志并非关注点。
- **可观测性边界**：由于没有结构化日志，无法按请求 ID、IP、Token 来源等维度进行聚合检索；需要追踪请求上下文时，应通过工具返回值中的 `auth.access_level` / `auth.source` 字段获取，而非依赖日志。
- **生产建议**：若后续需要结构化日志、分级过滤、文件落盘或接入外部日志系统，应在 `server.py` 启动处添加统一的 logger 初始化（例如基于 `logging` 模块或 `structlog`），并将所有 `print()` 替换为结构化日志调用，同时保留当前 `[INFO]/[WARNING]` 前缀风格以兼容现有监控解析逻辑。

## 5. 结论

该仓库的“日志系统”本质上是**零配置的 stdout 输出**，依赖 Uvicorn 控制台打印，辅以统一的 `[LEVEL]` 前缀约定。它适用于本地开发与快速验证场景，但不具备生产环境所需的结构化、可检索、可分级的日志能力。