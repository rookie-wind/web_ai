"""Phase 6：把 nodes/edges/layers/tour 组装成完整 KnowledgeGraph 并写出。"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

root = Path(sys.argv[1])
inter = root / ".ua/intermediate"
scan = json.loads((inter / "scan-result.json").read_text(encoding="utf-8"))
assembled = json.loads((inter / "assembled-graph.json").read_text(encoding="utf-8"))
layers = json.loads((inter / "layers.json").read_text(encoding="utf-8"))
tour = json.loads((inter / "tour.json").read_text(encoding="utf-8"))

graph = {
    "version": "1.0.0",
    "project": {
        "name": scan["name"],
        "languages": scan["languages"],
        "frameworks": scan["frameworks"],
        "description": scan["description"],
        "analyzedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "gitCommitHash": sys.argv[2],
    },
    "nodes": assembled["nodes"],
    "edges": assembled["edges"],
    "layers": layers,
    "tour": tour,
}

ids = {n["id"] for n in graph["nodes"]}
problems = []
for lay in layers:
    for nid in lay["nodeIds"]:
        if nid not in ids:
            problems.append("layer dangling " + nid)
for step in tour:
    for nid in step["nodeIds"]:
        if nid not in ids:
            problems.append("tour dangling " + nid)
if problems:
    print(json.dumps(problems, ensure_ascii=False, indent=2))
    sys.exit(1)

(inter / "assembled-graph.json").write_text(
    json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(
    "assembled graph: nodes=%d edges=%d layers=%d tour=%d"
    % (len(graph["nodes"]), len(graph["edges"]), len(layers), len(tour))
)
