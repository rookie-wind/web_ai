# 协议转换 MCP Server

基于 FastMCP 实现的协议转换 MCP 服务器，对齐 `protocol-conversion-dev-plan.md` 工具定义。

## 工具清单

| # | 工具名 | 类型 | 状态 | 说明 |
|---|--------|------|------|------|
| 1 | `list_mcp_tools` | 只读 | 已实现 | 列出所有工具 + 鉴权探测 |
| 2 | `query_device_classes` | 只读 | 桩 | 查询运维平台品牌、型号、原子标签 |
| 3 | `update_protocol_file` | 写入 | 桩 | 更新内部协议参考文件到本地 |
| 4 | `add_device_class` | 写入 | 桩 | 写入运维平台品牌、型号数据 |
| 5 | `check_script_exists` | 只读 | 桩 | 查找是否已有同品牌型号的转换脚本 |
| 6 | `publish_work_log` | 写入 | 桩 | 上传脚本创建记录 |
| 7 | `publish_converted_script` | 写入 | 桩 | 发布生成的转换脚本到平台 |

> 桩工具已注册完整参数 schema，返回占位响应 `{"status": "not_implemented", ...}`。

## 鉴权模型

```
用户访问接入页面 → 服务器检测 IP → 自动分配 Token → 生成接入文本
```

| 来源 | 权限级别 | Token 来源 | 只读工具 | 写入工具 |
|------|---------|-----------|---------|---------|
| localhost (127.0.0.1 / ::1) | system | 管理员 Token (MCP_AUTH_TOKEN) | 允许 | 允许 |
| 其它 IP | user | 自动生成 Token | 允许 | 拒绝 (FORBIDDEN) |

- **Token 自动分配**：访问接入页面时，服务器根据 IP 自动生成 Token，无需手动输入
- **管理员 Token**：通过 `MCP_AUTH_TOKEN` 环境变量配置，用于 localhost 系统级访问
- **用户 Token**：非 localhost 访问时自动生成，仅限只读操作
- **MCP 端点**：所有 `/mcp` 请求需携带 `Authorization: Bearer <TOKEN>`
- **接入页面和 Skills 下载**：无需鉴权
- 鉴权探测：调用 `list_mcp_tools` 返回 `auth` 字段，包含 `token_valid` / `access_level` / `source`

## 部署

### 环境要求

- Python 3.10+
- pip

### 安装

```bash
# 1. 创建虚拟环境
python -m venv .venv

# 2. 激活虚拟环境 (Windows)
.venv\Scripts\activate

# 2. 激活虚拟环境 (Linux/macOS)
source .venv/bin/activate

# 3. 安装依赖
pip install -r mcp_server/requirements.txt
```

### 启动

```bash
# 设置 Token（必须）
# Windows
set MCP_AUTH_TOKEN=your_token_here

# Linux/macOS
export MCP_AUTH_TOKEN=your_token_here

# 启动服务器
python mcp_server/server.py
```

启动后输出：

```
[INFO] Token authentication enabled.
[INFO] MCP Server starting on http://0.0.0.0:8765/mcp
[INFO] Tools: 7 (1 implemented + 6 stubs)
INFO:     Uvicorn running on http://0.0.0.0:8765
```

### 验证

```bash
# 1. 列出所有工具（tools/list）
curl -X POST http://localhost:8765/mcp ^
  -H "Content-Type: application/json" ^
  -H "Authorization: Bearer your_token_here" ^
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\",\"params\":{}}"

# 2. 调用 list_mcp_tools（鉴权探测）
curl -X POST http://localhost:8765/mcp ^
  -H "Content-Type: application/json" ^
  -H "Authorization: Bearer your_token_here" ^
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{\"name\":\"list_mcp_tools\",\"arguments\":{}}}"

# 3. 调用写入工具（localhost 下允许，非 localhost 返回 FORBIDDEN）
curl -X POST http://localhost:8765/mcp ^
  -H "Content-Type: application/json" ^
  -H "Authorization: Bearer your_token_here" ^
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{\"name\":\"update_protocol_file\",\"arguments\":{\"file_name\":\"test.json\"}}}"
```

## 一键接入页面

服务器启动后，浏览器访问 `http://<服务器IP>:8765/` 即可打开接入页面。

### 功能

- 服务器自动检测访问者 IP 并分配 Token（**无需手动输入**）
- 服务器地址根据访问来源自动填充
- 只需选择目标平台（Trae / Cursor / VS Code / Claude Desktop / Windsurf / Cline / Kimi Code）
- 自动生成接入文本（含 MCP 配置 JSON + Skills 安装步骤 + 验证指令 + 安全要求）
- 一键复制或下载 .md 文件

### 工作流程

```
管理员启动服务器 → 浏览器打开接入页面 → 服务器自动检测 IP + 分配 Token
→ 选择目标平台 → 复制接入文本 → 发送给其他用户
→ 用户粘贴到 AI Agent → Agent 自动写入 mcp.json + 安装 Skills + 调用 list_mcp_tools 验证
```

### Skills 包自动打包

服务器自动打包 `.trae/skills/` 目录，**无需手动压缩**：

- ZIP 下载：`http://<服务器IP>:8765/api/docs/export-skills-package`
- Markdown 摘要：`http://<服务器IP>:8765/api/docs/export-skills`

打包时自动排除 `dist/`、`__pycache__/`、`.git/` 等目录。

### API 端点

| 路径 | 方法 | 鉴权 | 说明 |
|------|------|------|------|
| `/` `/access` | GET | 无 | 接入页面 HTML |
| `/api/access-info` | GET | 无 | 自动检测 IP + 分配 Token，返回 JSON |
| `/api/docs/export-skills-package` | GET | 无 | Skills ZIP 下载 |
| `/api/docs/export-skills` | GET | 无 | Skills Markdown 摘要 |
| `/mcp` | POST | Bearer Token | MCP JSON-RPC 端点 |

## 配置

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MCP_HOST` | `0.0.0.0` | 监听地址 |
| `MCP_PORT` | `8765` | 监听端口 |
| `MCP_AUTH_TOKEN` | (空) | 管理员 Bearer Token。空则自动生成。用于 localhost 系统级访问 |

### MCP 客户端配置

项目 `.trae/mcp.json` 已就绪，无需修改：

```json
{
  "mcpServers": {
    "protocol-converter": {
      "url": "http://localhost:8765/mcp",
      "headers": {
        "Authorization": "Bearer your_token_here"
      }
    }
  }
}
```

> 将 `your_token_here` 替换为 `MCP_AUTH_TOKEN` 环境变量设置的值。

## 文件结构

```
mcp_server/
├── server.py            # FastMCP 入口 + AuthMiddleware + CompositeApp + 7 个工具
├── requirements.txt     # Python 依赖
├── install.bat           # 一键安装（创建虚拟环境 + 安装依赖 + 配置 Token）
├── start.bat             # 日常启动
├── .env                  # install.bat 自动生成，保存 Token
├── static/
│   └── access.html       # 一键接入生成器页面
└── README.md            # 本文件
```

## 后续开发

6 个桩工具的实现优先级（按 dev-plan 路线图）：

1. `query_device_classes` — Phase 2，查询数据库
2. `check_script_exists` — Phase 2，幂等检查
3. `update_protocol_file` — Phase 2，文件系统操作
4. `add_device_class` — Phase 3，数据库写入
5. `publish_work_log` — Phase 3，审计日志
6. `publish_converted_script` — Phase 3，脚本发布（需先通过测试验证）
