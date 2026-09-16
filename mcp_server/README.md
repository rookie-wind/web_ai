# 协议转换 MCP Server

基于 FastMCP 实现的协议转换 MCP 服务器，对齐 `protocol-conversion-dev-plan.md` 工具定义。

## 工具清单

`server.py` 实际注册了 48 个 MCP 工具，分为探测、登录、只读、写入四类。完整清单通过调用 `list_mcp_tools` 工具实时获取。

| 类型 | 数量 | 示例 |
|------|------|------|
| probe（探测） | 1 | `list_mcp_tools` |
| login（登录） | 1 | `login` |
| read（只读） | 28+ | `get_classify_list`、`get_device_type_list`、`get_brand_list`、`get_model_list`、`get_protocol_info_list`、`get_data_item_list`、`get_function_type_list`、`get_script_list`、`get_coeff_list`、`get_sense_list`、`get_protocol_type_list` 等 |
| write（写入） | 18+ | `add_*`、`update_*`、`del_*`、`save_*`、`upload_protocol_file`、`gen_script` |

> 写入类工具统一要求 `system` 权限（localhost 访问），非 localhost 的 `user` 权限调用时返回 `FORBIDDEN`。

## 鉴权模型

```
用户访问接入页面 → 服务器检测 IP → 自动分配 Token → 生成接入文本
```

| 来源 | 权限级别 | Token 来源 | 只读工具 | 写入工具 |
|------|---------|-----------|---------|---------|
| localhost (127.0.0.1 / ::1 / 本机网卡 IP) | system | 管理员 Token (MCP_AUTH_TOKEN) | 允许 | 允许（需用户确认） |
| 其它 IP | user | 按 IP 固定自动生成的 Token | 允许 | 拒绝（不询问、不调用） |

- **Token 自动分配**：访问接入页面时，服务器根据 IP 自动生成 Token，无需手动输入
- **Token 按 IP 固定**：非本机 Token 与访问 IP 绑定，持久化到本地 `.token_registry.json`，服务器重启后旧 Token 仍可继续使用，无需重新获取
- **IP 变化需重新获取**：如果访问 IP 发生变化（DHCP 重新分配、更换网络等），需重新打开接入页获取新 Token
- **管理员 Token**：通过 `MCP_AUTH_TOKEN` 环境变量配置，用于 localhost 系统级访问
- **用户 Token**：非 localhost 访问时按 IP 固定生成，仅限只读操作
- **MCP 端点**：所有 `/mcp` 请求需携带 `Authorization: Bearer <TOKEN>`
- **接入页面和 Skills 下载**：无需鉴权
- 鉴权探测：调用 `list_mcp_tools` 返回 `auth` 字段，包含 `token_valid` / `access_level` / `source`，以及 `capabilities` 字段说明服务器支持的特性（如 `persistent_user_token`、`function_type_atomic_tag`、`capability_matrix_report`）

### Token Registry（本地敏感运行态文件）

服务器在 `mcp_server/.token_registry.json` 中持久化非本机 IP 的 user Token 绑定关系：

- 每个记录包含 `ip`、`token`、`accessLevel`、`createdAt`、`lastSeenAt`、`revoked`
- 服务器启动时自动加载，访问接入页或 MCP 鉴权通过后自动更新 `lastSeenAt`
- 已 `revoked` 的 Token 会被鉴权中间件拒绝
- **该文件为本地敏感运行态文件，不得提交到版本控制，不得打包到 Agent 资源包，不得分发给其他用户**
- 已在项目 `.gitignore` 中排除 `mcp_server/.token_registry.json` 和 `.tmp` 临时文件

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
[INFO] Admin token authentication enabled.
[INFO] MCP Server starting on http://0.0.0.0:8765
[INFO]   Access Page:  http://localhost:8765/
[INFO]   MCP Endpoint: http://0.0.0.0:8765/mcp
[INFO]   Skills Download: http://0.0.0.0:8765/api/docs/export-skills-package
[INFO]   Tools:         48 (read: 28, write: 18)
[INFO]   Skills Dir:    E:\codeGIT\pca-mcp-server\.trae\skills
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
├── server.py            # FastMCP 入口 + AuthMiddleware + CompositeApp + 48 个工具
├── api_client.py        # 规约管理后端 API 客户端（httpx 异步）
├── requirements.txt     # Python 依赖
├── install.bat           # 一键安装（创建虚拟环境 + 安装依赖 + 配置 Token）
├── start.bat             # 日常启动
├── .env                  # install.bat 自动生成，保存 Token
├── .token_registry.json  # 本地敏感运行态文件，按 IP 持久化 user Token（不得提交版本控制）
├── static/
│   └── access.html       # 一键接入生成器页面
└── README.md            # 本文件
```

> `.token_registry.json` 是本地敏感运行态文件，已在 `.gitignore` 中排除。不要手动编辑或分发给其他用户。

## 后续开发

当前 48 个工具已覆盖规约管理后端 API 的全部原子操作（大类、设备类型、品牌、型号、规约、数据项、脚本、系数、感知、规约类型字典、功能项、文件上传等）。后续扩展方向：

1. 原子标签查询入口已明确为 `get_function_type_list`（API-E10 `GetProtocoFunctionTypeList`），`get_data_item_list` 仅用于查询采集点位配置
2. 持续完善 `/pca` 前置检查、能力矩阵、版本探测和 Agent 资源包更新流程
3. 持续完善 MODBUS 原子标签批量匹配、置信度、权限分支、续跑摘要和变更影响提示
4. 按需新增 MQTT/HTTP 协议转换的专属工具和 Skill
