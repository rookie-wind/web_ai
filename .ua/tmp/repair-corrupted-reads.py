"""修复被 Node 损坏读取污染的 8 个文件的结构与行数元数据。

- 5 个 Python 文件：用 CPython ast 注入顶层 functions / classes / exports
  （server.py 已由 patch-server-structure.py 处理，本脚本跳过已带 marker 的条目）
- 全部 8 个文件：把 scan-result.json 的 sizeLines 与 extract 条目的
  totalLines / nonEmptyLines 校正为 CPython 视角的真实值
- 2 个 C 文件无 ast 能力，仅校正行数，结构保持为空并记录原因
"""

import ast
import json
from pathlib import Path

ROOT = Path("e:/codeGIT/pca-mcp-server")

# 被 Node 读取损坏的文件 -> 所属批次
AFFECTED = {
    "agent_assets/skills/protocol-conversion/scripts/gen_test_report.py": 8,
    "agent_assets/skills/protocol-conversion/scripts/protocol_converter.py": 8,
    "agent_assets/skills/protocol-conversion/scripts/test_protocol_converter.py": 8,
    "agent_assets/skills/protocol-conversion/scripts/mapper_core.c": 8,
    "agent_assets/skills/protocol-conversion/scripts/mapper_core.h": 8,
    "agent_assets/skills/xlpa/tools/mcp_client.py": 9,
    "mcp_server/mcp_client.py": 9,
    "mcp_server/server.py": 9,
}

BATCHES = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)


def params_of(node):
    a = node.args
    names = [arg.arg for arg in a.posonlyargs] + [arg.arg for arg in a.args]
    if a.vararg:
        names.append(a.vararg.arg)
    if a.kwarg:
        names.append(a.kwarg.arg)
    return names


def ast_structure(text):
    """顶层 def/class/exports，口径对齐内置脚本（exports = 全部顶层定义）。"""
    tree = ast.parse(text)
    functions, classes, exports = [], [], []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            classes.append(
                {
                    "name": node.name,
                    "startLine": node.lineno,
                    "endLine": node.end_lineno,
                    "methods": [
                        m.name
                        for m in node.body
                        if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                    ],
                    "properties": [
                        t.id
                        for m in node.body
                        if isinstance(m, ast.Assign)
                        for t in m.targets
                        if isinstance(t, ast.Name)
                    ],
                }
            )
            exports.append({"name": node.name, "line": node.lineno, "isDefault": False})
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(
                {
                    "name": node.name,
                    "startLine": node.lineno,
                    "endLine": node.end_lineno,
                    "params": params_of(node),
                }
            )
            exports.append({"name": node.name, "line": node.lineno, "isDefault": False})
    return functions, classes, exports


# --- 载入各批次 extract 结果 ---
data = {}
for i in BATCHES:
    f = ROOT / f".ua/tmp/ua-file-extract-results-{i}.json"
    data[i] = json.loads(f.read_text(encoding="utf-8"))

by_path = {}
for i, d in data.items():
    for r in d["results"]:
        by_path[r["path"]] = (i, r)

injected, line_fixed, c_files = [], [], []

for rel, batch in sorted(AFFECTED.items()):
    p = ROOT / rel
    text = p.read_text(encoding="utf-8")
    lines = text.splitlines()
    real_total = len(lines)
    real_non_empty = len([x for x in lines if x.strip()])

    entry = by_path.get(rel)
    if entry:
        b, r = entry
        r["totalLines"] = real_total
        r["nonEmptyLines"] = real_non_empty
        if not r.get("structureSource") and not r.get("functions") and not r.get("classes"):
            if rel.endswith(".py"):
                fn, cl, ex = ast_structure(text)
                r["functions"], r["classes"], r["exports"] = fn, cl, ex
                r["metrics"] = {
                    "importCount": (r.get("metrics") or {}).get("importCount", 0),
                    "exportCount": len(ex),
                    "functionCount": len(fn),
                    "classCount": len(cl),
                }
                r["structureSource"] = "cpython-ast-fallback"
                injected.append(f"{rel} (batch {b}): fn={len(fn)} cls={len(cl)}")
            else:
                r["structureSource"] = "no-parser-for-c"
                c_files.append(f"{rel} (batch {b}): 行数已校正，结构仍为空")
        line_fixed.append(f"{rel}: totalLines -> {real_total}")
    else:
        print(f"WARN: {rel} 不在任何 extract 结果中（可能被跳过），仅校正 scan")

# --- 校正 scan-result.json 的 sizeLines ---
scan_file = ROOT / ".ua/intermediate/scan-result.json"
scan = json.loads(scan_file.read_text(encoding="utf-8"))
scan_fixed = []
for f in scan["files"]:
    if f["path"] in AFFECTED:
        real = len(ROOT.joinpath(*f["path"].split("/")).read_text(encoding="utf-8").splitlines())
        if f["sizeLines"] != real:
            scan_fixed.append(f"{f['path']}: {f['sizeLines']} -> {real}")
            f["sizeLines"] = real

# --- 落盘 ---
for i in BATCHES:
    (ROOT / f".ua/tmp/ua-file-extract-results-{i}.json").write_text(
        json.dumps(data[i], ensure_ascii=False, indent=2), encoding="utf-8"
    )
scan_file.write_text(
    json.dumps(scan, ensure_ascii=False, indent=2), encoding="utf-8"
)

print("=== ast 注入 ===")
print("\n".join(injected) or "(无，server.py 已在上一步注入)")
print("\n=== extract 行数校正 ===")
print("\n".join(line_fixed) or "(无)")
print("\n=== scan-result sizeLines 校正 ===")
print("\n".join(scan_fixed) or "(无)")
print("\n=== C 文件（无 ast 能力）===")
print("\n".join(c_files) or "(无)")
