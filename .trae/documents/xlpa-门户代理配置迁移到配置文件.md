# 门户代理配置迁移：从 .env 移到配置文件

## Context（背景）

门户代理地址 `PORTAL_PROXY_API_URL` 目前唯一真源是 `mcp_server/edge_client.py:54` 的模块级
`os.getenv("PORTAL_PROXY_API_URL", "")`，靠 `start.bat` 用 `for /f` 逐行读 `.env` 注入进程环境。

实测暴露两个问题：
1. 服务端若**不是**用 `start.bat` 启动（IDE / MCP 客户端直接拉起 `python server.py`），`.env` 完全不被读取 →
   `PORTAL_PROXY_API_URL` 恒为空 → `edge_get_token` 对 20.\* 报「门户代理地址未配置」。
2. 该值在模块导入时冻结（`edge_client.py:54`），改 `.env` 后**必须重启进程**才生效。

目标：把门户代理地址放到 **服务端直接读取的配置文件**（不依赖 `start.bat` / 进程 env 注入），
服务端任意启动方式都能读对。

### 硬约束
- 禁止瞎编：所有改动基于真实文件与既有 `permissions.json` 范式的落地方式。
- 禁止影响现有功能：保持 `.env`/env 部署的既有行为不回归（向后兼容）。
- 禁止引入新问题：`PORTAL_PROXY_FORWARD_PORT`/`PORTAL_PROXY_FORWARD_TYPE` 不动；门禁逻辑不动。

## 现有"配置文件作为事实源"范式（借鉴）
- `permissions.py` 的 `SuperAccountConfig`：路径用 `os.getenv("MCP_PERMISSIONS_PATH", 默认)` 计算，
  JSON 缺失/损坏 → 降级为空配置（不抛错）。
- 本方案照搬该模式：一个 JSON 事实源 + 一个可被 env 覆盖的路径 + 缺失/损坏降级。

## 方案

### 1. 新增 `mcp_server/proxy_config.json`（门户代理配置文件）
默认入库承载当前实测值（服务端运维事实源，用户侧不感知）：
```json
{
  "proxy_api_url": "http://121.229.15.116:7500"
}
```
- 若值为空串/缺失则回退到旧 env（与现状一致），保证不回归。
- 该文件属**服务端私有配置**：不从用户侧文档/提示中暴露具体地址与文件路径。

### 2. 新增 `mcp_server/edge_proxy_config.py`（配置加载器）
```python
import json, os
from pathlib import Path

_DEFAULT_PATH = Path(__file__).resolve().parent / "proxy_config.json"

def portal_proxy_api_url() -> str:
    """读配置文件；缺失/损坏/为空时回退到旧 env（向后兼容）。"""
    path = Path(os.getenv("PORTAL_PROXY_CONFIG_PATH", "") or _DEFAULT_PATH)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            url = str((data or {}).get("proxy_api_url", "") or "").strip()
        except (json.JSONDecodeError, OSError):
            url = ""
        if url:
            return url
    return os.getenv("PORTAL_PROXY_API_URL", "").strip()
```
- 配置文件缺失/损坏时回退到旧 env（与现状一致，零回归）。
- `PORTAL_PROXY_CONFIG_PATH` 环境变量可覆盖默认路径（沿用 `permissions.json` 的 env 覆盖范式）。

### 3. 修改 `mcp_server/edge_client.py`（唯一真源替换）
- L54：`PORTAL_PROXY_API_URL = os.getenv("PORTAL_PROXY_API_URL", "")`
  → `PORTAL_PROXY_API_URL = portal_proxy_api_url()`（来自新加载器）。
- 其余不动：`PORTAL_PROXY_FORWARD_PORT`/`PORTAL_PROXY_FORWARD_TYPE` 常量原样保留；
  模块继续导出 `PORTAL_PROXY_API_URL`（`edge_tools.py:44` 的 import 不被破坏）。

### 4. 修改 `mcp_server/.env`
- 删除 `PORTAL_PROXY_API_URL=http://121.229.15.116:7500` 这一行（配置源迁移到 `proxy_config.json`；
  `MCP_AUTH_TOKEN` 保留不动）。

### 5. 报错文案与服务端私有语义（不动用户侧）
- `edge_tools.py:1588` 门禁报错文案改为**服务端私有、不暴露配置文件地址**的中性描述，
  例如「门户代理未配置，无法连接 20 网段边缘后端，请联系服务端管理员配置后重试」。
- **不改动** `direct-edge-operation.md` / `SKILL.md` 中的用户侧说明，避免引导用户去了解/修改门户代理配置
  （用户只需提需求、拿结果）。如这两份文档有「在 .env 配置 PORTAL_PROXY_API_URL」字样，则**改为服务端私有提示或删除**，
  不出现代理地址与配置文件路径。

### 6. 测试
- 新增 `mcp_server/tests/test_proxy_config.py`：
  - 配置文件存在且有值 → 返回该值；
  - 配置文件缺失 → 回退 env；
  - 配置文件损坏（非法 JSON）→ 回退 env；
  - 配置文件为空值 → 回退 env。
- 更新 `tests/test_portal_proxy.py`：`test_proxy_api_url_from_env`（L139-145）注释/断言对齐
  「来源为 proxy_config.json，env 为回退」；其余用例不改。
- 全量回归：`python -m pytest mcp_server/tests -q` 必须全绿。

## 决策结论（已与你确认）
- 决策1：`proxy_config.json` 默认写入**当前值** `http://121.229.15.116:7500`（服务端开箱即用）；
  但属**服务端私有**，用户侧文档/提示不暴露地址与文件（用户只提需求、拿结果）。
- 决策2：`PORTAL_PROXY_FORWARD_PORT/TYPE`（7500/SmartUnit）**不纳入**配置文件，保持固定常量。

## 验证方式
1. `python -m pytest mcp_server/tests -q` 全绿（新增 + 更新用例）。
2. 手工：服务端（任意启动方式）读到 `proxy_config.json` 的值 → `edge_get_token(ip=20.*)` 不再报「未配置」，
   请求实际发往 `proxy_config.json` 中的代理地址。
3. 回归：删除/清空 `proxy_config.json` 且无 env → 回退为空串，门禁报「门户代理未配置」（中性文案）。

## 涉及文件
- 新增：`mcp_server/proxy_config.json`（含默认值）、`mcp_server/edge_proxy_config.py`
- 修改：`mcp_server/edge_client.py`（真源替换）、`mcp_server/.env`（删除 PORTAL_PROXY_API_URL 行）、
  `edge_tools.py`（门禁文案改为服务端私有中性描述）
- 测试：新增 `tests/test_proxy_config.py`、更新 `tests/test_portal_proxy.py`