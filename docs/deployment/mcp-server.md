# PCA MCP Server 项目文档

## 目录

- [1. 项目概述](#1-项目概述)
- [2. 核心依赖说明](#2-核心依赖说明)
  - [2.1 requirements.txt](#21-requirementstxt)
  - [2.2 MCP (Model Context Protocol)](#22-mcp-model-context-protocol)
  - [2.3 Uvicorn](#23-uvicorn)
- [3. MCP 与 Uvicorn 工作原理](#3-mcp-与-uvicorn-工作原理)
  - [3.1 角色分工](#31-角色分工)
  - [3.2 ASGI 协议](#32-asgi-协议)
  - [3.3 完整工作流程](#33-完整工作流程)
- [4. 部署脚本详解](#4-部署脚本详解)
  - [4.1 目录结构](#41-目录结构)
  - [4.2 install.bat（安装脚本）](#42-installbat安装脚本)
  - [4.3 activate.bat（虚拟环境激活脚本）](#43-activatebat虚拟环境激活脚本)
  - [4.4 start.bat（启动脚本）](#44-startbat启动脚本)
- [5. 脚本调用关系](#5-脚本调用关系)
- [6. 常见问题排查](#6-常见问题排查)
- [7. 安全注意事项](#7-安全注意事项)

---

## 1. 项目概述

**PCA MCP Server** 是一个基于 MCP（Model Context Protocol）协议构建的 Python 服务端项目，用于为 AI 客户端（如 Claude Desktop、Trae IDE 等）提供工具调用能力。

### 核心功能

- 提供 MCP 协议标准的工具（Tools）调用接口
- 支持 SSE（Server-Sent Events）长连接通信
- 基于 Token 的身份认证机制
- 提供本地开发环境的一键部署方案（Windows）

---

## 2. 核心依赖说明

### 2.1 requirements.txt

```txt
mcp>=1.0.0,<2.0.0
uvicorn>=0.30.0
```

**作用：** 声明项目所需的外部依赖包及其版本范围。

**版本约束说明：**

| 包名        | 版本约束             | 含义                                      |
| --------- | ---------------- | --------------------------------------- |
| `mcp`     | `>=1.0.0,<2.0.0` | 需要 1.x.x 系列的最新版本，避免自动升级到 2.0.0 等不兼容的大版本 |
| `uvicorn` | `>=0.30.0`       | 需要 0.30.0 或更高版本，允许后续所有更新                |

**安装命令：**

```bash
pip install -r requirements.txt
```

---

### 2.2 MCP (Model Context Protocol)

MCP 是 **Model Context Protocol** 的 Python SDK，用于构建 MCP 协议服务端和客户端。

**核心职责：**

- 定义服务端的业务逻辑（工具 Tools、资源 Resources、提示词 Prompts）
- 实现 MCP 协议的 JSON-RPC 消息处理
- 管理工具调用的路由和生命周期

**MCP 协议标准端点：**
| 端点 | 用途 |
|------|------|
| `/sse` | 建立 SSE 长连接，接收客户端消息 |
| `/mcp` | MCP 协议主端点（JSON-RPC over HTTP/SSE） |

---

### 2.3 Uvicorn

Uvicorn 是一个 **极快的 ASGI 服务器**，用于运行 Python 异步 Web 应用程序。

**核心特点：**

| 特点         | 说明                                                           |
| ---------- | ------------------------------------------------------------ |
| **高性能**    | 基于 `uvloop`（替代 asyncio 的事件循环）和 `httptools`，性能接近 Node.js 和 Go |
| **支持异步**   | 原生支持 `async/await`，适合 I/O 密集型任务                              |
| **支持多种协议** | HTTP/1.1、WebSocket、SSE（Server-Sent Events）等                  |
| **轻量级**    | 启动速度快，内存占用低                                                  |

**基本使用：**

```bash
# 启动 ASGI 应用
uvicorn app:app --host 0.0.0.0 --port 8000
```

**参数说明：**

- `app:app` → 文件名为 `app.py`，应用对象名为 `app`
- `--host` → 绑定的 IP 地址
- `--port` → 监听的端口

---

## 3. MCP 与 Uvicorn 工作原理

### 3.1 角色分工

| 角色          | 负责内容                              | 不负责内容          |
| ----------- | --------------------------------- | -------------- |
| **Uvicorn** | 网络层：监听端口、解析 HTTP 协议、管理连接、序列化/反序列化 | 业务逻辑、工具调用      |
| **MCP**     | 应用层：路由、工具调用、资源管理、协议解析（JSON-RPC）   | 网络细节、HTTP 协议处理 |

**通俗理解：**

- **MCP = 客服团队**（懂业务，能回答问题）
- **Uvicorn = 前台接待员**（接收请求，转交给客服，再把答复传回）
- **HTTP/SSE = 电话线**（通信渠道）

客户端不会直接联系 MCP，必须通过 Uvicorn 中转。

---

### 3.2 ASGI 协议

MCP 和 Uvicorn 之所以能配合，是因为它们都遵守 **ASGI（异步服务器网关接口）协议**。

**ASGI 应用标准形式：**

```python
async def app(scope, receive, send):
    # scope: 请求信息（路径、方法、头部等）
    # receive: 接收请求体的函数
    # send: 发送响应的函数

    await send({
        'type': 'http.response.start',
        'status': 200,
        'headers': [...]
    })
    await send({
        'type': 'http.response.body',
        'body': b'Hello World'
    })
```

**ASGI 与 WSGI 对比：**

| 对比项  | ASGI                 | WSGI              |
| ---- | -------------------- | ----------------- |
| 支持协议 | HTTP、WebSocket、SSE 等 | 仅 HTTP            |
| 处理模型 | 异步（async/await）      | 同步（阻塞）            |
| 适用场景 | FastAPI、MCP、实时通信     | Django、Flask 传统应用 |
| 并发能力 | 高并发（事件循环）            | 低（需要多进程）          |

---

### 3.3 完整工作流程

#### 阶段一：启动服务

```bash
uvicorn app:app --host 0.0.0.0 --port 8765
```

执行过程：

```
1. uvicorn 读取命令，找到 app 对象
   ↓
2. 创建 ASGI 应用程序实例（MCP 服务器）
   ↓
3. 启动 uvloop（高性能异步事件循环），监听指定端口
   ↓
4. 服务器进入"等待请求"状态 ✅ 服务已上线
```

---

#### 阶段二：客户端连接（建立 SSE）

以 Claude Desktop 或 Trae IDE 为例：

```
客户端 (Claude Desktop/Trae IDE)
    │
    │ 1. 发起 HTTP GET 请求到 /sse 端点
    ▼
  Uvicorn (前台接待员)
    │
    │ 2. 接收请求，解析 HTTP 头部、路径、参数
    │ 3. 判断为 ASGI 请求，转发给 MCP 应用
    ▼
  MCP 应用 (客服团队)
    │
    │ 4. MCP 的 SSE 端点被触发
    │ 5. 建立 SSE（Server-Sent Events）长连接
    │ 6. 返回响应头：Content-Type: text/event-stream
    │ 7. 连接保持打开状态（不关闭）
    ▼
  Uvicorn
    │
    │ 8. 通过 HTTP 响应流，将 MCP 的数据逐块发送给客户端
    ▼
  客户端 ← 连接建立成功，等待 MCP 发送消息
```

---

#### 阶段三：请求-响应循环

```
┌─────────────────────────────────────────────────────────────┐
│ 1. 客户端通过 SSE 连接发送消息（工具调用请求）              │
│    格式：{"method": "tools/call", "params": {...}}        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. Uvicorn 接收 HTTP 请求体                                │
│    - 解析出请求数据（JSON 格式）                           │
│    - 封装成 ASGI scope 和 receive 通道                    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. Uvicorn 将请求转交给 MCP 应用                          │
│    - 调用 MCP 的 __call__ 方法（ASGI 入口）               │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. MCP 应用内部处理：                                      │
│    a. 根据请求路径和内容，路由到对应的处理器               │
│    b. 执行工具逻辑（如调用 API、数据库查询等）             │
│    c. 生成响应数据（JSON 格式）                           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. MCP 将响应返回给 Uvicorn                               │
│    - 通过 ASGI send 通道发送响应                          │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 6. Uvicorn 将响应组装成 HTTP Response                     │
│    - 设置正确的 HTTP 状态码、头部                         │
│    - 将 JSON 数据作为响应体发送                           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 7. 客户端收到响应，处理并展示结果给用户                    │
└─────────────────────────────────────────────────────────────┘
```

---

#### 并发处理模型

由于 Uvicorn 基于异步事件循环，可以高效处理并发请求：

```
时间线：
─────────────────────────────────────────────────────────────►

请求1 (客户端A) ──► Uvicorn ──► MCP处理（异步等待API）──► 返回A
请求2 (客户端B) ──► Uvicorn ──► MCP处理（异步等待API）──► 返回B
请求3 (客户端C) ──► Uvicorn ──► MCP处理（异步等待API）──► 返回C

关键：Uvicorn 不会阻塞等待，在处理请求1的 I/O 等待时，
      会去处理请求2和请求3，实现高并发。
```

---

## 4. 部署脚本详解

### 4.1 目录结构

```
E:\codeGIT\pca-mcp-server\          ← ROOT_DIR（项目根目录）
│
├── .venv\                          ← Python 虚拟环境（由 install.bat 创建）
│   └── Scripts\
│       ├── activate.bat            ← 虚拟环境激活脚本
│       ├── python.exe              ← 虚拟环境 Python 解释器
│       └── pip.exe                 ← 虚拟环境 pip
│
├── .trae\                          ← （可选）仅当 install.bat 选择为 Trae 预写时创建
│   └── mcp.json                    ← Trae 客户端 MCP 配置；其它工具由接入页 Agent 自动注册
│
└── mcp_server\                     ← SCRIPT_DIR（服务端代码目录）
    ├── install.bat                 ← 一键安装脚本
    ├── start.bat                   ← 服务启动脚本
    ├── server.py                   ← MCP 服务器入口文件
    ├── requirements.txt            ← 依赖声明文件
    └── .env                        ← 环境变量配置（Token）
```

---

### 4.2 install.bat（安装脚本）

**功能：** 一键完成项目环境初始化，只需在首次部署时运行一次。

**执行流程：**

```
┌──────────────────────────────────────────────────────────────────┐
│                     install.bat 执行流程                        │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ① 检查 Python 是否安装（要求 3.10+）                          │
│         ↓ 未安装 → 报错退出                                    │
│         ↓ 已安装 → 继续                                        │
│                                                                  │
│  ② 创建虚拟环境 .venv（如果不存在）                            │
│         ↓                                                       │
│  ③ 激活虚拟环境，用 pip 安装 requirements.txt 依赖             │
│         ↓                                                       │
│  ④ 配置认证 Token                                              │
│     ├─ 用户输入或自动生成                                      │
│     ├─ 写入 mcp_server/.env                                    │
│     └─ 可选：为 Trae 预写 .trae/mcp.json（默认跳过）         │
│         ↓                                                       │
│  ⑤ 完成！提示用户运行 start.bat 启动服务                       │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

**脚本代码解析：**

| 代码段                                  | 说明                  |
| ------------------------------------ | ------------------- |
| `@echo off`                          | 不显示每条命令本身，让输出更干净    |
| `chcp 65001 >nul`                    | 切换为 UTF-8 编码，避免中文乱码 |
| `python --version`                   | 检查 Python 是否安装      |
| `python -m venv .venv`               | 创建虚拟环境              |
| `pip install -r requirements.txt -q` | 安装依赖（安静模式）          |
| `secrets.token_hex(16)`              | 生成密码学安全的随机 Token    |
| `echo MCP_AUTH_TOKEN=%TOKEN% > .env` | 写入环境变量文件            |
| 选择 y 时写 `.trae/mcp.json`         | 可选：预写 Trae 客户端配置（默认跳过） |

**Token 生成规则：**

- 格式：`metam_pat_` + 32 位随机十六进制字符串
- 示例：`metam_pat_a1b2c3d4e5f67890...`
- 使用 Python `secrets` 模块生成，保证密码学安全

**生成的配置文件：**

`.env` 文件内容：

```
MCP_AUTH_TOKEN=metam_pat_a1b2c3d4e5f67890...
```

`.trae/mcp.json` 文件内容（仅当在 install.bat 中选择为 Trae 预写配置时生成）：

```json
{
  "mcpServers": {
    "xl-protocol-agent": {
      "url": "http://localhost:8765/mcp",
      "headers": {
        "Authorization": "Bearer metam_pat_a1b2c3d4e5f67890..."
      }
    }
  }
}
```

> **服务端与工具解耦**：install.bat 默认不再写任何工具专属配置。除 Trae 外的客户端（含 Qoder）由接入页生成的文本驱动目标工具内 Agent，把 `xl-protocol-agent` 合并写入各自真实配置文件（如 Qoder `~/.qoder/mcp.json`），写完调用 `list_mcp_tools` 验证。

---

### 4.3 activate.bat（虚拟环境激活脚本）

**功能：** 修改当前命令行的环境变量，让所有 Python 相关命令指向虚拟环境。

> **注意：** 此脚本由 `python -m venv` 自动生成，用户通常不需要手动修改。

**核心操作：**

```batch
set "VIRTUAL_ENV=E:\codeGIT\pca-mcp-server\.venv"
set "PATH=%VIRTUAL_ENV%\Scripts;%PATH%"
set "PROMPT=(.venv) %PROMPT%"
set PYTHONHOME=
```

**激活前后对比：**

| 项目           | 激活前                                      | 激活后                                     |
| ------------ | ---------------------------------------- | --------------------------------------- |
| `python` 指向  | 系统全局 Python（如 `C:\Python312\python.exe`） | 虚拟环境 Python（`.venv\Scripts\python.exe`） |
| `pip` 指向     | 系统全局 pip                                 | 虚拟环境 pip                                |
| 安装包位置        | `C:\Python312\Lib\site-packages`         | `.venv\Lib\site-packages`               |
| 命令提示符        | `C:\my-project>`                         | `(.venv) C:\my-project>`                |
| `PYTHONHOME` | 可能有值                                     | 被清空                                     |

**退出虚拟环境：**

```bash
deactivate
```

---

### 4.4 start.bat（启动脚本）

**功能：** 每次启动 MCP 服务器时使用，激活虚拟环境、加载配置、启动服务。

**执行流程：**

```
┌─────────────────────────────────────────────────────────┐
│                    start.bat 执行流程                   │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ① 设置 UTF-8 编码，获取脚本目录和项目根目录           │
│         ↓                                              │
│  ② 激活虚拟环境 .venv                                  │
│     └── 失败 → 提示运行 install.bat，退出              │
│         ↓                                              │
│  ③ 从 .env 文件中读取 MCP_AUTH_TOKEN                   │
│     └── 不存在 → 提示运行 install.bat，退出            │
│         ↓                                              │
│  ④ 打印启动信息（Token、URL、工具数量）                │
│         ↓                                              │
│  ⑤ 执行 python server.py（启动 MCP 服务器）            │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**启动后的输出示例：**

```
============================================
  PCA MCP Server
============================================

  Token:  metam_pat_a1b2c3d4e5f67890
  URL:    http://localhost:8765/mcp
  Tools:  48 (read: 28, write: 18)

  Press Ctrl+C to stop
============================================

INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8765
```

---

## 5. 脚本调用关系

```
┌─────────────────────────────────────────────────────────────┐
│                    完整调用链                               │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              install.bat（首次运行）                  │   │
│  │  - 检查 Python 环境                                  │   │
│  │  - 创建虚拟环境 .venv                                │   │
│  │  - 安装依赖包                                        │   │
│  │  - 生成 Token 写入 .env；可选为 Trae 预写配置       │   │
│  └──────────────────────────────────────────────────────┘   │
│                              │                              │
│                              ▼                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              start.bat（日常使用）                    │   │
│  │  ┌─────────────────────────────────────────────┐     │   │
│  │  │  调用 activate.bat（激活虚拟环境）           │     │   │
│  │  │  - 修改 PATH，优先使用虚拟环境              │     │   │
│  │  │  - 修改 PROMPT，显示 (.venv) 前缀          │     │   │
│  │  │  - 清空 PYTHONHOME                          │     │   │
│  │  └─────────────────────────────────────────────┘     │   │
│  │  - 读取 .env 中的 MCP_AUTH_TOKEN                     │   │
│  │  - 打印启动信息                                      │   │
│  │  - 执行 python server.py                             │   │
│  └──────────────────────────────────────────────────────┘   │
│                              │                              │
│                              ▼                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                   server.py                          │   │
│  │  - 创建 MCP 服务器实例                               │   │
│  │  - 注册工具（Tools）                                 │   │
│  │  - 使用 Uvicorn 启动服务（8765 端口）                │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 6. 常见问题排查

### 问题 1：Python 未安装或版本过低

**错误信息：**

```
[X] Python not found, please install Python 3.10+
```

**解决方案：**

1. 从 [python.org](https://www.python.org/downloads/) 下载 Python 3.10+
2. 安装时**务必勾选** "Add Python to PATH"
3. 重新打开命令行并运行 `python --version` 确认安装成功

---

### 问题 2：虚拟环境创建失败

**错误信息：**

```
[X] Virtual environment creation failed
```

**可能原因：**

- Python 版本过低（< 3.10）
- 权限不足（无法在项目目录创建文件夹）
- 磁盘空间不足

**解决方案：**

1. 检查 Python 版本：`python --version`
2. 以管理员身份运行命令行
3. 确保磁盘有足够空间

---

### 问题 3：依赖安装失败

**错误信息：**

```
[X] Dependency installation failed, check network
```

**可能原因：**

- 网络连接问题（无法访问 PyPI）
- pip 版本过低

**解决方案：**

1. 检查网络连接
2. 尝试使用国内镜像源：
   
   ```bash
   pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
   ```
3. 升级 pip：
   
   ```bash
   python -m pip install --upgrade pip
   ```

---

### 问题 4：启动时找不到虚拟环境

**错误信息：**

```
[X] Virtual environment not found, please run install.bat first
```

**解决方案：**

1. 确保已运行 `install.bat`
2. 检查项目根目录下是否存在 `.venv` 文件夹
3. 如果 `.venv` 被删除，重新运行 `install.bat`

---

### 问题 5：Token 未配置

**错误信息：**

```
[X] MCP_AUTH_TOKEN not set
Please run install.bat first to configure Token
```

**解决方案：**

1. 运行 `install.bat` 生成 Token
2. 或手动创建 `mcp_server/.env` 文件，内容为：
   
   ```
   MCP_AUTH_TOKEN=your_custom_token_here
   ```

---

### 问题 6：端口被占用

**错误信息：**

```
ERROR: [Errno 10048] error while attempting to bind on address ('0.0.0.0', 8765)
```

**解决方案：**

1. 查找占用 8765 端口的进程：
   
   ```bash
   netstat -ano | findstr :8765
   ```
2. 结束占用进程：
   
   ```bash
   taskkill /PID <进程ID> /F
   ```
3. 或修改 `server.py` 中的端口号

---

### 问题 7：移动项目文件夹后虚拟环境失效

**原因：** `activate.bat` 中硬编码了虚拟环境的绝对路径。

**解决方案：**

1. 删除旧的 `.venv` 文件夹
2. 重新运行 `install.bat` 创建新的虚拟环境

---

## 7. 安全注意事项

### 7.1 Token 管理

| 风险                     | 建议                         |
| ---------------------- | -------------------------- |
| Token 明文存储在 `.env` 文件中 | 仅用于本地开发环境，不要部署到生产环境        |
| Token 可能被意外提交到 Git     | 确保 `.env` 在 `.gitignore` 中 |
| Token 泄露风险             | 如需共享项目，告知用户重新打开接入页获取新 Token      |
| Token Registry 泄露 | 确保 `.token_registry.json` 在 `.gitignore` 中，不得打包到 Agent 资源包 |

### 7.2 权限模型

根据脚本中的提示，该 MCP 服务器的权限模型如下：

| 访问方式              | 权限级别       | 操作能力     |
| ----------------- | ---------- | -------- |
| `localhost`（本地访问） | 系统级        | 读/写      |
| 其他 IP 地址          | 用户级        | 只读       |
| 其他用户              | 按 IP 固定自动分配 Token | 通过访问页面获取 |

### 7.3 Token Registry（本地敏感运行态文件）

服务器在 `mcp_server/.token_registry.json` 中持久化非本机 IP 的 user Token 绑定关系：

- 每个记录包含 `ip`、`token`、`accessLevel`、`createdAt`、`lastSeenAt`、`revoked`
- 服务器启动时自动加载，访问接入页或 MCP 鉴权通过后自动更新 `lastSeenAt`
- 已 `revoked` 的 Token 会被鉴权中间件拒绝
- **该文件为本地敏感运行态文件，不得提交到版本控制，不得打包到 Agent 资源包，不得分发给其他用户**
- 已在项目 `.gitignore` 中排除 `mcp_server/.token_registry.json` 和 `.tmp` 临时文件

### 7.4 生产环境建议

如果要将此服务部署到生产环境，建议：

1. **更换认证方式**：使用更强的认证机制（如 OAuth2、JWT）
2. **启用 HTTPS**：使用 SSL/TLS 加密通信
3. **使用进程管理**：使用 Gunicorn + Uvicorn 的多进程模式
4. **添加日志审计**：记录所有工具调用和认证尝试
5. **限制访问来源**：使用防火墙或反向代理限制 IP 范围

---

## 附录：快速命令参考

| 操作       | 命令                            |
| -------- | ----------------------------- |
| 首次安装     | `mcp_server\install.bat`      |
| 启动服务     | `mcp_server\start.bat`        |
| 停止服务     | 按 `Ctrl+C`                    |
| 手动激活虚拟环境 | `.venv\Scripts\activate.bat`  |
| 退出虚拟环境   | `deactivate`                  |
| 手动启动服务   | `python mcp_server\server.py` |

---

*文档版本：1.1*  
*最后更新：2026年9月14日*
