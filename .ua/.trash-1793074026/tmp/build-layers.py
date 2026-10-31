"""Phase 4 分层：基于 assembled-graph 的路径前缀与依赖方向，把全部文件级节点
划入互斥的架构层，写出 layers.json 并校验覆盖完整、无重复归属。
"""

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

root = Path(sys.argv[1])
graph = json.loads((root / ".ua/intermediate/assembled-graph.json").read_text(encoding="utf-8"))
FILE_LEVEL = {"file", "config", "document", "service", "pipeline", "table", "schema", "resource"}
file_nodes = [n for n in graph["nodes"] if n["type"] in FILE_LEVEL]

LAYERS = [
    (
        "layer:mcp-service-gateway",
        "MCP 服务与接入层",
        "FastMCP 服务装配、鉴权中间件、ASGI 复合应用与接入/展示页面，负责对外暴露 MCP 端点与 HTTP 端点。",
        [
            "mcp_server/server.py",
            "mcp_server/static/access.html",
            "mcp_server/static/showcase.html",
            "mcp_server/.env",
            "mcp_server/version.json",
            "mcp_server/requirements.txt",
            "mcp_server/install.bat",
            "mcp_server/start.bat",
            "mcp_server/mcp_client.py",
        ],
    ),
    (
        "layer:session-auth",
        "会话与权限层",
        "MCP 接入 Token 分配、会话注册、超级账号判定与业务凭据缓存，为写操作提供 Fail-Closed 安全门禁。",
        [
            "mcp_server/session.py",
            "mcp_server/token_manager.py",
            "mcp_server/permissions.py",
            "mcp_server/permissions.template.json",
        ],
    ),
    (
        "layer:edge-integration",
        "边缘集成与审计层",
        "边缘平台客户端、代理配置与联通类 MCP 工具装配，并记录操作日志与任务报告供回读审计。",
        [
            "mcp_server/edge_tools.py",
            "mcp_server/edge_client.py",
            "mcp_server/edge_proxy_config.py",
            "mcp_server/proxy_config.json",
            "mcp_server/operation_log_store.py",
            "mcp_server/cleanup.py",
            "agent_assets/skills/xlpa/tools/mcp_client.py",
        ],
    ),
    (
        "layer:platform-api",
        "平台 API 适配层",
        "封装规约管理后端的全部 REST 接口，向上传递平台主数据与写入能力。",
        [
            "mcp_server/api_client.py",
        ],
    ),
    (
        "layer:archiving-engine",
        "自动建档引擎层",
        "建档领域模型、字段契约、模板生成与读取、版本迁移、Profile 装配、阶段编排、快照与补偿等核心引擎实现。",
        [
            "mcp_server/archiving/",
        ],
    ),
    (
        "layer:conversion-engine",
        "协议转换与映射引擎层",
        "共享映射核心与协议转换技能：C 映射引擎、Python 封装、示例配置与测试报告，覆盖 MQTT/HTTP/Modbus 转换。",
        [
            "agent_assets/skills/protocol-conversion/",
            "agent_assets/skills/http-conversion/",
            "agent_assets/skills/mqtt-conversion/",
            "agent_assets/skills/modbus-conversion/",
            "agent_assets/skills/modbus-cq-adapt/",
        ],
    ),
    (
        "layer:agent-skills",
        "Agent 技能资产层",
        "面向作业编排的技能定义与资源包清单：XLPA 总纲、设备建档作业、打包分发与测试验证技能。",
        [
            "agent_assets/skills/xlpa/SKILL.md",
            "agent_assets/skills/xlpa/manifest.json",
            "agent_assets/skills/xlpa/agents/openai.yaml",
            "agent_assets/skills/xlpa-device-archiving/",
            "agent_assets/skills/pack-distribution/",
            "agent_assets/skills/test-validation/",
            "agent_assets/skills/package-manifest.json",
        ],
    ),
    (
        "layer:test-validation",
        "测试与回归层",
        "离线单元与集成回归测试集，覆盖建档链路、契约、鉴权、快照、日志与下发判据。",
        [
            "mcp_server/tests/",
            "pytest.ini",
            "_verify_download_fix.ps1",
        ],
    ),
    (
        "layer:project-docs",
        "项目文档与参考资料",
        "项目总览、结构与运行时方案文档、部署与 API 参考资料、演示文稿及现场环境草稿。",
        [
            "README.md",
            "mcp_server/README.md",
            "docs/",
            "_vm_list.txt",
        ],
    ),
]

assigned = {}
unmatched = []
for n in file_nodes:
    path = n.get("filePath") or n["id"].split(":", 1)[1]
    hit = None
    for lid, _name, _desc, rules in LAYERS:
        for r in rules:
            if r.endswith("/"):
                if path.startswith(r):
                    hit = lid
                    break
            elif path == r:
                hit = lid
                break
        if hit:
            break
    if hit:
        assigned.setdefault(hit, []).append(n["id"])
    else:
        unmatched.append(path)

if unmatched:
    print("UNMATCHED (需要补规则):", json.dumps(unmatched, ensure_ascii=False, indent=2))
    sys.exit(1)

dupes = [k for k, v in assigned.items() if len(v) != len(set(v))]
layers = [
    {"id": lid, "name": name, "description": desc, "nodeIds": assigned.get(lid, [])}
    for lid, name, desc, _ in LAYERS
    if assigned.get(lid)
]

total = sum(len(l["nodeIds"]) for l in layers)
print("file nodes=%d assigned=%d layers=%d dupes=%s" % (len(file_nodes), total, len(layers), dupes))
if total != len(file_nodes):
    print("覆盖不完整，中止")
    sys.exit(1)

(root / ".ua/intermediate/layers.json").write_text(
    json.dumps(layers, ensure_ascii=False, indent=2), encoding="utf-8"
)
for l in layers:
    print("  %-28s %3d  %s" % (l["id"], len(l["nodeIds"]), l["name"]))
