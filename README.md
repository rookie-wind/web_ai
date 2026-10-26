# PCA MCP Server

协议转换平台 MCP Server，提供设备建档、协议转换、品牌型号管理等工具，
通过 FastMCP ASGI 网关对外暴露。

## 目录结构

```
mcp_server/              MCP 服务、启动脚本、服务配置模板
  tests/                 离线单元与集成测试（pytest）
  archiving/             自动建档引擎（模板生成、字段契约、补偿）
  static/                前端接入页与展示页

agent_assets/skills/     Agent 资源包发布源（由服务端自动打包为 ZIP）
  <skill>/references/    Skill 协议资料与可复用配置样例
  <skill>/scripts/       映射引擎、测试脚本
  package-manifest.json  资源包清单与必需文件声明

docs/                    维护者文档
  deployment/            部署与配置指南
  reference/             API 规格、字段参考、服务设计
  architecture/          （预留）模块关系与扩展指南
  experience/            （预留）经验、踩坑与待验证事项

validation/              开发验证资产（不进用户包、不提交版本控制）
  manual/                参数化只读核验工具（人工显式调用）
  evidence/              脱敏历史回执与契约证据
  reference/             字典快照、协议原文摘录、参考工作簿
  reports/               整理清单与验证结果

openspec/                OpenSpec 规格与变更
```

## 快速启动

```bash
cd mcp_server
pip install -r requirements.txt
python server.py
```

## 测试

```bash
# 离线测试（默认收集 mcp_server/tests/）
pytest

# 映射引擎自测
pytest agent_assets/skills/protocol-conversion/scripts/test_protocol_converter.py
```

## 用户资源包

服务端自动将 `agent_assets/skills/` 打包为 ZIP，
通过 `/api/docs/export-skills-package` 端点下载。
打包时自动排除 `temp/`、`output/`、`__pycache__/`、`~$*` 等非必要文件。

## 关键文件

| 文件 | 说明 |
|------|------|
| `设备建档模板_20260922153429.xlsx` | 用户填写工作簿（本阶段不读取、不解析） |
| `agent_assets/skills/package-manifest.json` | 资源包清单 |
| `mcp_server/permissions.template.json` | 权限配置模板 |
| `mcp_server/.env` | 环境变量（不提交版本控制） |
