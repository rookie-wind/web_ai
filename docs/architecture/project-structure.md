# PCA MCP Server 项目结构

> 最后更新：2026-09-23

## 概览

本项目是一个面向智慧能源单元档案管理的 MCP（Model Context Protocol）服务端，
以 FastMCP ASGI 网关桥接后端 HTTP API，将 30+ 后端接口统一暴露为可编排的 MCP
原子工具。同时包含协议转换 Agent 资源包（Skills），支持 Modbus / MQTT / HTTP
三种协议转换方向。

项目按职责分为五层：

```
mcp_server/          服务层 — MCP 网关、建档引擎、测试
agent_assets/skills/ 资源层 — Agent 技能包（自动打包为 ZIP 分发）
docs/                文档层 — 维护者文档
validation/          验证层 — 开发验证资产（不进版本控制、不进用户包）
openspec/            规格层 — OpenSpec 变更与规格
```

---

## 根目录

```
.
├── mcp_server/                  MCP 服务主目录
├── agent_assets/skills/          Agent 资源包发布源
├── docs/                         维护者文档
├── validation/                   开发验证资产
├── openspec/                     OpenSpec 规格与变更
├── pytest.ini                    pytest 配置（默认收集 mcp_server/tests/）
├── README.md                     项目导航
├── .gitignore                    版本控制忽略规则
└── 设备建档模板_20260922153429.xlsx  用户填写工作簿（不读取、不解析）
```

---

## mcp_server/ — 服务层

MCP 网关核心，包含服务入口、API 客户端、建档引擎、鉴权、测试。

### 入口与配置

| 文件 | 说明 |
|------|------|
| `server.py` | 应用入口。FastMCP 实例、30+ MCP 工具注册、ZIP 打包、展示页 |
| `api_client.py` | 后端 HTTP API 客户端。封装 httpx.AsyncClient，统一鉴权与错误处理 |
| `edge_client.py` | 边缘后端 HTTP 客户端（175 环境） |
| `edge_tools.py` | 边缘端 MCP 工具实现 |
| `requirements.txt` | 依赖清单（mcp 1.x + uvicorn） |
| `.env` | 环境变量（`MCP_AUTH_TOKEN`，不提交版本控制） |
| `version.json` | 版本号 |
| `install.bat` | 首次安装脚本（创建 .venv → 安装依赖 → 生成 Token） |
| `start.bat` | 启动脚本（激活 .venv → 校验 Token → 启动服务） |

### 鉴权与会话

| 文件 | 说明 |
|------|------|
| `token_manager.py` | Token 生成、验证、IP 关联管理 |
| `session.py` | 会话绑定与状态管理 |
| `permissions.py` | 权限模型实现（session-role 分级访问控制） |
| `permissions.json` | 运行时权限配置（不提交版本控制） |
| `permissions.template.json` | 权限配置模板 |

### 自动建档引擎 (`archiving/`)

| 文件 | 说明 |
|------|------|
| `engine.py` | 建档主引擎，编排两阶段流程 |
| `stage_orchestrator.py` | 阶段编排器 |
| `models.py` | 数据模型（ArchiveTemplate、Node 等） |
| `converter.py` | Excel → 模板转换器 |
| `excel_reader.py` | Excel 读取与校验 |
| `field_contract.py` | 字段契约定义 |
| `compensation.py` | 参数补偿逻辑 |
| `time_validator.py` | 时间字段校验 |
| `ooxml_validator.py` | OOXML 文件格式校验 |
| `log_sanitizer.py` | 日志脱敏 |
| `reference_config.py` | 参考配置加载 |
| `reference_dict.py` | 参考字典 |
| `reference_provider.py` | 参考数据提供者 |
| `snapshot_store.py` | 快照存储 |
| `task_report_store.py` | 任务报告存储 |

**profiles/** — 设备类型插件

| 文件 | 说明 |
|------|------|
| `base.py` | Profile 基类 |
| `registry.py` | Profile 注册表 |
| `gateway_8163.py` | 8163 网关 Profile |
| `meter_xlba.py` | XLBA 电表 Profile |

**templates/** — 模板生成

| 文件 | 说明 |
|------|------|
| `generator.py` | v14 模板生成器（核心） |
| `stage_zero_generate.py` | 阶段零生成 |

### 前端页面 (`static/`)

| 文件 | 说明 |
|------|------|
| `access.html` | Token 分配访问页 |
| `showcase.html` | 展示页（平台统计、工具清单） |

### 测试 (`tests/`)

429 项离线测试，覆盖建档引擎、鉴权、字段契约、模板生成等。

| 文件 | 覆盖范围 |
|------|----------|
| `test_archiving_template.py` | 建档模板端到端集成（最大测试集） |
| `test_generator_v14.py` | v14 模板生成器 |
| `test_field_contract.py` | 字段契约 |
| `test_auth_revamp.py` | 鉴权模型 |
| `test_session_permission.py` | 会话权限 |
| `test_brand_model_code.py` | 品牌型号逻辑 |
| `test_refactor.py` | 重构回归 |
| `test_reference_dict.py` | 参考字典 |
| `test_reference_provider.py` | 参考数据提供者 |
| `test_snapshot_store.py` | 快照存储 |

### 运行态文件（不提交版本控制）

| 文件/目录 | 说明 |
|-----------|------|
| `archive_templates/` | 建档快照（JSON + XLSX） |
| `.token_registry.json` | Token 持久化注册 |
| `.showcase_cache.json` | 展示页统计缓存 |
| `.stats.json` | 事件计数 |
| `.business_token_cache.json` | 云端业务 Token 缓存 |

---

## agent_assets/skills/ — 资源层

Agent 资源包发布源。服务端自动将此目录打包为 ZIP，
通过 `/api/docs/export-skills-package` 端点分发。

### 目录约定

每个 Skill 遵循统一结构：

```
<skill>/
├── SKILL.md           技能定义（Agent 读取）
├── manifest.json      Skill 元数据
├── agents/            Agent 配置（openai.yaml 等）
├── references/        协议资料、参考文档、配置样例
├── scripts/           工具脚本（映射引擎、测试等）
└── tools/             MCP 客户端工具
```

### Skill 清单

| Skill | 职责 |
|-------|------|
| `xlpa` | 协议转换入口技能，路由到对应协议子技能 |
| `xlpa-device-archiving` | 设备建档技能，含 4 份参考文档 |
| `modbus-conversion` | Modbus 协议转换配置生成 |
| `mqtt-conversion` | MQTT 协议转换配置生成 |
| `http-conversion` | HTTP 协议转换配置生成 |
| `protocol-conversion` | 共享映射核心（mapper_core.c/h） |
| `test-validation` | 转换配置测试验证 |
| `pack-distribution` | 转换包打包分发 |
| `modbus-cq-adapt` | 重庆地区 Modbus 脚本适配 |

### 打包过滤

ZIP 打包时自动排除：

- `temp/`、`output/`、`dist/` — 临时/输出目录
- `__pycache__/` — Python 缓存
- `~$*` — Office 临时锁文件
- `.git/`、`node_modules/` — 版本控制/Node 依赖

### 配置样例

```
http-conversion/references/examples/
├── aimcover-http.json          HTTP→MQTT 样例（Aimcover）
└── linktheall-http.json        HTTP→MQTT 样例（LinkTheAll）

mqtt-conversion/references/examples/
└── vpp-mqtt.json               MQTT→MQTT 样例（VPP）
```

---

## docs/ — 文档层

维护者文档，不进入用户资源包。

```
docs/
├── deployment/
│   └── mcp-server.md           部署指南（install.bat / start.bat 流程）
└── reference/
    ├── edge-archive-fields.md  边缘建档字段与操作流程（合并两份历史文档）
    ├── mcp-service-design.md   MCP 服务化设计 Spec
    └── protocol-management-api.md  基础数据模块 Spec
```

---

## validation/ — 验证层

开发验证资产，不进用户包、不提交版本控制。

```
validation/
├── manual/                     人工显式调用的核验工具
│   ├── probe_archive_readonly.py   边缘建档只读核验（白名单端点、输出脱敏）
│   └── extract_protocol_pages.py   PDF 协议文档提取工具
├── evidence/                   脱敏的历史回执与契约证据（34 个文件）
│   ├── _pathB_*.json/txt/png       Path B 验证过程证据
│   ├── _probe_*.json               接口探测回执
│   └── extend_info_*.png           扩展信息变更截图
├── reference/                  可复用参考数据
│   ├── templates/              历史录入模板（v1-v4）
│   ├── protocols/              协议原文摘录（AMC、BWDK 等）
│   ├── pathB_chunks_raw/       前端 JS 源码快照
│   ├── pathB_endpoints.json    端点清单
│   └── _probe_*_out.json       字典/属性快照
└── reports/                    整理清单与验证结果
    ├── final_delivery.md       最终交付清单
    ├── inventory_action_list.md    逐文件处置清单
    └── inventory_execution.md      执行报告
```

---

## openspec/ — 规格层

OpenSpec 工作流产物，记录变更提案、设计、规格与任务。

```
openspec/
├── config.yaml                 OpenSpec 配置
├── specs/                      当前生效的规格
│   ├── agent-assets-package-management/
│   ├── mcp-token-management/
│   ├── modbus-mcp-workflow/
│   └── pca-entry-workflow/
└── changes/                    变更记录
    ├── archive/                已归档变更（10 个）
    └── <active>/               进行中变更
        ├── proposal.md         提案
        ├── design.md           设计
        ├── tasks.md            任务清单
        └── specs/              Delta 规格
```

---

## 数据流

```
用户/Agent
    │
    ▼
┌─────────────────────────────────┐
│  mcp_server/server.py           │
│  FastMCP ASGI 网关 (:8765)      │
│  ┌──────────┐  ┌──────────────┐ │
│  │ MCP 工具  │  │ 鉴权/会话    │ │
│  │ 30+ 个   │  │ Token+权限   │ │
│  └────┬─────┘  └──────────────┘ │
│       │                         │
│  ┌────▼─────────────────────┐   │
│  │ api_client.py            │   │
│  │ edge_client.py           │   │
│  └────┬─────────────────────┘   │
└───────┼─────────────────────────┘
        │ HTTP
        ▼
┌──────────────────┐     ┌──────────────────┐
│ 云端规约平台 API  │     │ 175 边缘后端 API  │
│ (品牌/型号/大类)  │     │ (建档/参数/召测)  │
└──────────────────┘     └──────────────────┘
```

---

## 版本控制

### 提交内容

- `mcp_server/` 源码（排除运行态文件）
- `agent_assets/skills/` 资源包
- `docs/` 文档
- `openspec/` 规格
- `pytest.ini`、`README.md`、`.gitignore`
- `设备建档模板_20260922153429.xlsx` 用户工作簿

### 不提交内容（.gitignore）

- `.venv/`、`__pycache__/`、`.pytest_cache/`
- `validation/` 验证资产
- `mcp_server/.token_registry.json` Token 注册
- `mcp_server/.business_token_cache.json` 业务 Token 缓存
- `mcp_server/permissions.json` 权限配置
- `mcp_server/.env` 环境变量
- `mcp_server/archive_templates/` 建档快照
- `mcp_server/.stats.json` 事件计数
- `~$*` Office 临时锁文件
