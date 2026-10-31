"""Phase 5 导览：写出 tour.json，并校验每个 nodeIds 条目都存在于合并节点集合中。"""

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

root = Path(sys.argv[1])
graph = json.loads((root / ".ua/intermediate/assembled-graph.json").read_text(encoding="utf-8"))
ids = {n["id"] for n in graph["nodes"]}

STEPS = [
    (
        "项目总览与目录职责",
        "先读根 README 与项目结构说明，确认 mcp_server（服务端）、agent_assets/skills（资源包发布源）、docs（维护者文档）三大板块的边界。",
        ["document:README.md", "document:docs/architecture/project-structure.md"],
    ),
    (
        "服务入口：FastMCP 装配与工具分组",
        "server.py 是唯一的进程入口：它装配 FastMCP、注册平台工具、包装鉴权与日志，并由 CompositeApp 分流 /mcp 与静态页面。",
        ["file:mcp_server/server.py", "class:mcp_server/server.py:CompositeApp", "function:mcp_server/server.py:list_mcp_tools"],
    ),
    (
        "鉴权与权限模型",
        "本机 IP 获得系统级 Token（可读写），外部 IP 获得用户级 Token（只读）；理解 TokenManager、SystemTokenManager、权限矩阵与业务凭据缓存的分工。",
        [
            "class:mcp_server/server.py:TokenManager",
            "class:mcp_server/server.py:AuthMiddleware",
            "class:mcp_server/token_manager.py:SystemTokenManager",
            "class:mcp_server/permissions.py:SuperAccountConfig",
            "document:docs/reference/mcp-service-design.md",
        ],
    ),
    (
        "会话与归属解耦",
        "Session/SessionRegistry 把 MCP Token 与后端业务 Token 隔离，归属主体与凭据解耦是日志隔离和越权防护的前提。",
        [
            "file:mcp_server/session.py",
            "class:mcp_server/session.py:SessionRegistry",
            "class:mcp_server/permissions.py:BusinessTokenCache",
        ],
    ),
    (
        "平台后端 API 适配",
        "ProtocolApiClient 一个类封装了平台全部 REST 接口，是 MCP 工具与规约管理后端之间的唯一通道。",
        ["file:mcp_server/api_client.py", "class:mcp_server/api_client.py:ProtocolApiClient", "document:docs/reference/protocol-management-api.md"],
    ),
    (
        "边缘客户端与联通三工具",
        "EdgeDeviceClient 负责设备树查询、建档写入、参数读写与召测；edge_tools 把这些能力装配为通用 MCP 工具，对设备类型无感知。",
        [
            "file:mcp_server/edge_client.py",
            "class:mcp_server/edge_client.py:EdgeDeviceClient",
            "file:mcp_server/edge_tools.py",
            "function:mcp_server/edge_tools.py:register_edge_tools",
        ],
    ),
    (
        "建档领域模型与字段契约",
        "models.py 定义任务配置、拓扑节点、字段规格与干跑计划；field_contract.py 是生成端、解析端与下发端共用的单一事实源。",
        [
            "file:mcp_server/archiving/models.py",
            "class:mcp_server/archiving/models.py:FieldSpec",
            "file:mcp_server/archiving/field_contract.py",
            "function:mcp_server/archiving/field_contract.py:_meter_fields",
        ],
    ),
    (
        "模板生成、读取与版本迁移",
        "generator.py 按契约产出骨架工作簿，excel_reader.py 在读入时执行版本门禁与洁净度校验，template_migrator.py 负责跨版本升级。",
        [
            "function:mcp_server/archiving/templates/generator.py:generate_template",
            "function:mcp_server/archiving/excel_reader.py:read_archive_template",
            "function:mcp_server/archiving/template_migrator.py:migrate_template",
        ],
    ),
    (
        "设备 Profile 与报文组装",
        "DeviceProfile 抽象 + XLBA/网关/照明/配电房具体实现，承担字段到报文的组装；authParam 的编码规则是下发成败的关键。",
        [
            "class:mcp_server/archiving/profiles/base.py:DeviceProfile",
            "class:mcp_server/archiving/profiles/meter_xlba.py:MeterXlbaProfile",
            "class:mcp_server/archiving/profiles/registry.py:ProfileRegistry",
            "function:mcp_server/archiving/profiles/base.py:assemble_auth_param",
        ],
    ),
    (
        "计划生成与阶段编排（含免模板路径）",
        "engine.build_plan 产出拓扑有序的干跑计划，StageOrchestrator 按阶段状态驱动续跑；edge_tools 中的免模板路径以边缘现状回推报文。",
        [
            "function:mcp_server/archiving/engine.py:build_plan",
            "class:mcp_server/archiving/stage_orchestrator.py:StageOrchestrator",
            "function:mcp_server/edge_tools.py:_deploy_without_template",
            "function:mcp_server/edge_tools.py:execute_archive_task",
            "class:mcp_server/archiving/compensation.py:CompensationRecorder",
        ],
    ),
    (
        "快照、分块上传与安全校验",
        "SnapshotStore 按 owner 隔离快照并支持分块上传，ooxml_validator 抵御 zip 炸弹，log_sanitizer 保证日志不落敏感值。",
        [
            "class:mcp_server/archiving/snapshot_store.py:SnapshotStore",
            "function:mcp_server/archiving/ooxml_validator.py:validate_ooxml",
            "function:mcp_server/archiving/log_sanitizer.py:sanitize_report",
        ],
    ),
    (
        "操作日志与审计回读",
        "OperationLogStore 以 JSONL 按身份隔离落盘，展示页据此渲染操作轨迹；写操作的请求与结果都要可回读。",
        [
            "class:mcp_server/operation_log_store.py:OperationLogStore",
            "file:mcp_server/static/showcase.html",
            "file:mcp_server/static/access.html",
        ],
    ),
    (
        "协议转换与映射引擎",
        "mapper_core.c 提供路径取值/构建与模板替换，protocol_converter.py 以 ctypes 复用同一引擎，转换技能据此生成 JSON 配置。",
        [
            "function:agent_assets/skills/protocol-conversion/scripts/mapper_core.c:template_substitute",
            "class:agent_assets/skills/protocol-conversion/scripts/protocol_converter.py:MapperCore",
            "document:agent_assets/skills/protocol-conversion/SKILL.md",
        ],
    ),
    (
        "Agent 技能资产与资源包分发",
        "agent_assets/skills 是发布源，package-manifest.json 声明必需文件，服务端自动打包供 /api/docs/export-skills-package 下载。",
        [
            "config:agent_assets/skills/package-manifest.json",
            "document:agent_assets/skills/xlpa/SKILL.md",
            "document:agent_assets/skills/xlpa-device-archiving/SKILL.md",
            "document:agent_assets/skills/pack-distribution/SKILL.md",
        ],
    ),
    (
        "测试与回归基线",
        "mcp_server/tests 是离线回归主战场；改动建档链路、契约或鉴权后，先跑 pytest 再谈交付。",
        [
            "file:mcp_server/tests/test_archiving_template.py",
            "file:mcp_server/tests/test_refactor.py",
            "file:mcp_server/tests/test_field_contract.py",
            "config:pytest.ini",
        ],
    ),
    (
        "部署与运行时方案",
        "最后是运维视角：部署指南说明启动与配置，运行时方案文档解释 Web-Backend-CLI-MCP 分层与多会话隔离前提。",
        [
            "document:docs/deployment/mcp-server.md",
            "document:docs/architecture/web-chat-agent-runtime-solution.md",
            "document:mcp_server/README.md",
        ],
    ),
]

tour = []
missing = []
for i, (title, desc, node_ids) in enumerate(STEPS, start=1):
    valid = []
    for nid in node_ids:
        if nid in ids:
            valid.append(nid)
        else:
            missing.append((i, nid))
    tour.append({"order": i, "title": title, "description": desc, "nodeIds": valid})

if missing:
    print("MISSING node refs:", json.dumps(missing, ensure_ascii=False, indent=2))
    sys.exit(1)

(root / ".ua/intermediate/tour.json").write_text(
    json.dumps(tour, ensure_ascii=False, indent=2), encoding="utf-8"
)
print("tour steps=%d written" % len(tour))
