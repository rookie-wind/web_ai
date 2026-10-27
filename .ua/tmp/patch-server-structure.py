"""用 CPython ast 补齐 extract-structure 对 mcp_server/server.py 的空提取。

成因未明（tree-sitter 返回 0 结构且无 Warning），此处仅注入确定性的结构事实
（名称 / 行号 / 参数 / 方法），不改动批次内其他文件，也不生成任何语义内容。
注入后在条目上打 marker，便于后续 Phase 与报告归因。
"""

import ast
import json
import sys
from pathlib import Path

ROOT = Path("e:/codeGIT/pca-mcp-server")
TARGET = "mcp_server/server.py"
RESULTS = ROOT / ".ua/tmp/ua-file-extract-results-9.json"


def params_of(node) -> list[str]:
    """位置参数名，与内置脚本的 params 口径一致。"""
    a = node.args
    names = [arg.arg for arg in a.posonlyargs]
    names += [arg.arg for arg in a.args]
    if a.vararg:
        names.append(a.vararg.arg)
    if a.kwarg:
        names.append(a.kwarg.arg)
    return names


def methods_of(cls) -> list[str]:
    return [
        n.name
        for n in cls.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def properties_of(cls) -> list[str]:
    """类体内的直接赋值名（含带注解的赋值）。"""
    out = []
    for n in cls.body:
        if isinstance(n, ast.Assign):
            out += [t.id for t in n.targets if isinstance(t, ast.Name)]
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            out.append(n.target.id)
    return out


def main() -> None:
    tree = ast.parse((ROOT / TARGET).read_text(encoding="utf-8"))

    functions, classes, exports = [], [], []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(
                {
                    "name": node.name,
                    "startLine": node.lineno,
                    "endLine": node.end_lineno,
                    "params": params_of(node),
                }
            )
            exports.append({"name": node.name, "line": node.lineno, "isDefault": False})
        elif isinstance(node, ast.ClassDef):
            classes.append(
                {
                    "name": node.name,
                    "startLine": node.lineno,
                    "endLine": node.end_lineno,
                    "methods": methods_of(node),
                    "properties": properties_of(node),
                }
            )
            exports.insert(
                0, {"name": node.name, "line": node.lineno, "isDefault": False}
            )

    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    entry = next((f for f in data["results"] if f["path"] == TARGET), None)
    if entry is None:
        print("FAIL: server.py 条目不在提取结果中", file=sys.stderr)
        sys.exit(1)

    if entry.get("functions") or entry.get("classes"):
        print("SKIP: 该条目已有结构，不覆盖", file=sys.stderr)
        sys.exit(1)

    entry["functions"] = functions
    entry["classes"] = classes
    entry["exports"] = exports
    entry["metrics"] = {
        "importCount": 0,
        "exportCount": len(exports),
        "functionCount": len(functions),
        "classCount": len(classes),
    }
    entry["structureSource"] = "cpython-ast-fallback"

    RESULTS.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"injected {TARGET}: functions={len(functions)} classes={len(classes)}")
    print("classes: " + ", ".join(f"{c['name']}[{c['startLine']}-{c['endLine']}] m={len(c['methods'])}" for c in classes))
    print("functions: " + ", ".join(f"{f['name']}[{f['startLine']}-{f['endLine']}]" for f in functions))


if __name__ == "__main__":
    main()
