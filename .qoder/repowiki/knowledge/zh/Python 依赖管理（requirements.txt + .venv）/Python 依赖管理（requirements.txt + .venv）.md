---
kind: dependency_management
name: Python 依赖管理（requirements.txt + .venv）
category: dependency_management
scope:
    - '**'
source_files:
    - mcp_server/requirements.txt
    - mcp_server/server.py
    - mcp_server/install.bat
    - mcp_server/start.bat
---

## 1. 使用的系统/方法

本项目采用 Python 生态的标准依赖管理方式：通过 `mcp_server/requirements.txt` 声明运行时依赖，配合本地虚拟环境 `.venv/` 隔离安装。服务以 Uvicorn 启动 FastMCP 应用，因此依赖集中在 MCP 协议与 ASGI 服务器两个层面。

## 2. 关键文件

- `mcp_server/requirements.txt`：唯一的外部依赖清单，仅声明 2 个包：
  - `mcp>=1.0.0,<2.0.0`：FastMCP 客户端/服务端 SDK，版本区间锁定主版本，避免破坏性升级。
  - `uvicorn>=0.30.0`：ASGI 服务器，用于在开发/部署时启动 MCP 服务。
- `.venv/`：项目根级 Python 虚拟环境目录（当前为空占位），用于隔离第三方库。
- `mcp_server/server.py`：实际导入并使用这些依赖的入口（`from mcp.server.fastmcp import FastMCP`、通过 uvicorn 启动）。
- `mcp_server/install.bat` / `start.bat`：Windows 一键安装与启动脚本，间接体现依赖安装流程。

## 3. 架构与约定

- **最小化依赖**：除 MCP SDK 和 ASGI 服务器外无其他第三方库，业务逻辑全部由标准库（`os`、`json`、`zipfile`、`secrets`、`contextvars` 等）实现。
- **版本约束策略**：使用 `>=X.Y.Z,<Z.0.0` 形式的“兼容主版本”约束，允许次版本/补丁版本自动升级，但锁定大版本以避免 API 不兼容。
- **无 lockfile**：仓库中不存在 `requirements.lock`、`poetry.lock`、`Pipfile.lock` 等锁定文件；依赖版本由 `requirements.txt` 中的范围约束决定，具体解析结果取决于安装时的 PyPI 可用版本。
- **无私有源/镜像配置**：未发现 `pip.conf`、`setup.cfg` 或环境变量中配置的私有 PyPI 源；依赖直接从官方 PyPI 拉取。
- **无 vendoring**：没有 `vendor/`、`third_party/` 等内嵌第三方代码目录。
- **虚拟环境位置**：`.venv/` 位于仓库根目录而非 `mcp_server/` 子目录，表明整个仓库共享一个 Python 环境。

## 4. 约定与约束

- **可观察到的约定**：
  - 所有外部依赖统一在 `mcp_server/requirements.txt` 中集中声明，未在其它位置发现分散的依赖定义。
  - 新增依赖需同步更新该文件，并由 `install.bat` 或 `pip install -r requirements.txt` 安装到 `.venv`。
  - 依赖版本采用“主版本锁定 + 次版本开放”的宽松策略，便于安全补丁自动升级。
- **未发现的强制规则**：仓库中没有 CI/CD 脚本、Dockerfile 或预提交钩子来强制校验依赖版本或执行 `pip check`；依赖一致性依赖开发者手动维护 `requirements.txt`。
- **OpenSpec 工件**：`openspec/` 目录下的变更工件（proposal/design/tasks/spec）描述功能演进，但不参与依赖声明或版本控制。

综上，该项目是一个极简的 Python MCP 服务，依赖管理遵循最基础的 `requirements.txt` + `.venv` 模式，没有引入更复杂的包管理器或锁定机制。