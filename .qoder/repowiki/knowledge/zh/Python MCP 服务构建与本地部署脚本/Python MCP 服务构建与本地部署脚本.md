---
kind: build_system
name: Python MCP 服务构建与本地部署脚本
category: build_system
scope:
    - '**'
source_files:
    - mcp_server/requirements.txt
    - mcp_server/install.bat
    - mcp_server/start.bat
    - mcp_server/server.py
    - mcp_server/.env
    - .trae/mcp.json
    - mcp server部署.md
---

## 1. 构建系统概览

本项目是一个基于 Python 的 MCP（Model Context Protocol）服务端，采用极简的本地化构建与部署方案。没有 Makefile、Dockerfile、CI/CD 流水线或容器化配置；构建完全依赖 Python 标准库 `venv` + `pip`，并通过 Windows Batch 脚本完成环境初始化与服务启动。

核心依赖仅两个：`mcp>=1.0.0,<2.0.0`（MCP 协议 SDK）和 `uvicorn>=0.30.0`（ASGI 服务器），声明在 `mcp_server/requirements.txt` 中。

## 2. 关键文件

- `mcp_server/requirements.txt` — 唯一依赖清单，锁定 mcp 为 1.x 系列，避免大版本不兼容升级。
- `mcp_server/install.bat` — 首次安装脚本：检查 Python ≥3.10 → 创建 `.venv` → pip 安装依赖 → 生成并写入 `mcp_server/.env`（`MCP_AUTH_TOKEN`）→ 生成 `.trae/mcp.json`（IDE 自动连接配置）。
- `mcp_server/start.bat` — 启动脚本：激活 `.venv` → 读取 `.env` 中的 `MCP_AUTH_TOKEN` → 校验存在性 → 打印启动信息 → 执行 `python server.py`。
- `mcp_server/server.py` — 应用入口（由 start.bat 直接调用）。
- `mcp_server/static/access.html` — 访问页面（用于其他用户自动分配 Token）。
- `mcp server部署.md` — 部署文档，详细描述了 install.bat / start.bat 的执行流程、目录结构、常见问题排查与安全注意事项。

## 3. 架构与约定

### 虚拟环境隔离
项目根目录下的 `.venv` 是 Python 虚拟环境，由 `install.bat` 通过 `python -m venv .venv` 创建。所有依赖安装到该环境中，start.bat 通过 `call "%ROOT_DIR%\.venv\Scripts\activate.bat"` 激活后再运行 `server.py`，确保依赖隔离。

### 配置管理
- 运行时配置通过 `mcp_server/.env` 提供，当前仅包含 `MCP_AUTH_TOKEN` 一个环境变量。
- IDE 客户端配置通过 `mcp_server/../.trae/mcp.json` 提供，由 install.bat 自动生成，指向 `http://localhost:8765/mcp` 并附带 Bearer Token 头。

### 启动流程
```text
install.bat（一次性）
  → 创建 .venv + 安装 requirements.txt
  → 生成 MCP_AUTH_TOKEN（格式：metam_pat_ + 32位十六进制）
  → 写入 mcp_server/.env
  → 写入 .trae/mcp.json
start.bat（每次启动）
  → 激活 .venv
  → 读取 .env 中的 MCP_AUTH_TOKEN（不存在则报错退出）
  → python server.py
```

### 端口与端点
服务默认监听 `http://0.0.0.0:8765`，暴露 `/sse`（SSE 长连接）和 `/mcp`（MCP JSON-RPC 主端点）两个端点。

## 4. 约定与约束

- **Python 版本要求**：install.bat 显式检查 Python 是否存在，并在错误提示中要求安装 Python 3.10+。
- **依赖版本约束**：`requirements.txt` 将 `mcp` 限制在 `>=1.0.0,<2.0.0`，禁止自动升级到不兼容的大版本；`uvicorn` 仅设定下限 `>=0.30.0`。
- **Token 安全**：`MCP_AUTH_TOKEN` 明文存储在 `mcp_server/.env` 中，文档明确建议仅用于本地开发环境，不要部署到生产环境；如需共享项目应告知用户重新生成 Token。
- **权限模型**：根据脚本注释，`localhost` 访问为系统级（读/写），其他 IP 为用户级（只读），其他用户可通过访问页面获取自动分配的 Token。
- **Windows 优先**：所有部署脚本均为 `.bat` 批处理文件，面向 Windows 环境；未提供 Linux/macOS 等效脚本。
- **无 CI/CD 与制品发布**：仓库中没有 Makefile、Dockerfile、GitHub Actions、Jenkinsfile 等自动化构建或发布配置；项目以源码形式分发，由使用者自行运行 install.bat 完成本地部署。
- **端口固定**：服务绑定 8765 端口，若被占用需手动修改 server.py 中的端口号或通过 netstat/taskkill 解决。
- **.gitignore 缺失**：部署文档提到应将 `.env` 加入 `.gitignore`，但仓库中未见 `.gitignore` 文件，属于潜在风险点。