"""Python 文件结构提取器（CPython ast 实现）。

本机 Node 读文件会按 4096 字节向上取整并附带未初始化内存，导致 tree-sitter
对较大 .py 文件解析为空；本脚本用 CPython 读取 + ast 解析，输出与
extract-structure.mjs 相同 schema 的结果，供 /understand Phase 2 替换使用。

用法:
    python ua-py-extract.py <project_root> <input_json> <output_json>
"""

import ast
import json
import os
import re
import sys


def _params(node):
    """提取函数形参名列表。"""
    names = []
    a = node.args
    for pos in list(a.posonlyargs) + list(a.args):
        names.append(pos.arg)
    if a.vararg:
        names.append("*" + a.vararg.arg)
    for kw in a.kwonlyargs:
        names.append(kw.arg)
    if a.kwarg:
        names.append("**" + a.kwarg.arg)
    return names


def _end(node):
    """返回节点结束行（1-based）。"""
    return getattr(node, "end_lineno", None) or node.lineno


def _callee_name(call):
    """把调用表达式压成可读名称。"""
    f = call.func
    parts = []
    while isinstance(f, ast.Attribute):
        parts.append(f.attr)
        f = f.value
    if isinstance(f, ast.Name):
        parts.append(f.id)
    elif isinstance(f, ast.Call):
        inner = _callee_name(f)
        if not inner:
            return None
        parts.append(inner)
    else:
        return None
    return ".".join(reversed(parts))


class Walker(ast.NodeVisitor):
    """收集函数、类、导出与调用图。"""

    def __init__(self, path):
        self.path = path
        self.functions = []
        self.classes = []
        self.exports = []
        self.calls = []
        self._class_stack = []

    def visit_FunctionDef(self, node):
        info = {
            "name": node.name,
            "startLine": node.lineno,
            "endLine": _end(node),
            "params": _params(node),
        }
        if self._class_stack:
            self._class_stack[-1]["_method_nodes"].append(node)
        else:
            self.functions.append(info)
        self.exports.append({"name": node.name, "line": node.lineno, "isDefault": False})
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        info = {
            "name": node.name,
            "startLine": node.lineno,
            "endLine": _end(node),
            "methods": [],
            "properties": [],
            "_method_nodes": [],
            "exports": None,
        }
        bases = []
        for b in node.bases:
            if isinstance(b, ast.Name):
                bases.append(b.id)
            elif isinstance(b, ast.Attribute):
                bases.append(b.attr)
        info["_bases"] = bases
        self._class_stack.append(info)
        self.generic_visit(node)
        self._class_stack.pop()
        info["methods"] = [m.name for m in info.pop("_method_nodes")]
        self.classes.append(info)
        self.exports.append({"name": node.name, "line": node.lineno, "isDefault": False})

    def visit_Call(self, node):
        name = _callee_name(node)
        if name:
            owner = self._class_stack[-1]["name"] if self._class_stack else "<module>"
            self.calls.append(
                {"caller": owner, "callee": name, "lineNumber": node.lineno}
            )
        self.generic_visit(node)

    def visit_Assign(self, node):
        # 类体与模块级的简单属性赋值，用于 properties 概览
        if self._class_stack:
            for t in node.targets:
                if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name):
                    if t.value.id == "self":
                        self._class_stack[-1]["properties"].append(t.attr)
        self.generic_visit(node)


def extract(path, root):
    """提取单个 Python 文件的结构信息。"""
    abs_path = os.path.join(root, path.replace("/", os.sep))
    with open(abs_path, "rb") as fh:
        raw = fh.read()
    text = raw.decode("utf-8-sig", errors="replace")
    lines = text.split("\n")
    total_lines = len(lines)
    non_empty = len([l for l in lines if l.strip()])

    tree = ast.parse(text, filename=path)
    w = Walker(path)
    w.visit(tree)

    classes = []
    for c in w.classes:
        bases = c.pop("_bases", [])
        c = {k: v for k, v in c.items() if not k.startswith("_")}
        c["bases"] = bases
        classes.append(c)

    result = {
        "path": path,
        "language": "python",
        "fileCategory": "code",
        "totalLines": total_lines,
        "nonEmptyLines": non_empty,
        "functions": w.functions,
        "classes": classes,
        "exports": w.exports,
        "callGraph": w.calls,
        "metrics": {
            "exportCount": len(w.exports),
            "functionCount": len(w.functions),
            "classCount": len(classes),
        },
    }
    return result


def extract_c(path, root):
    """用正则在 CPython 侧提取 C 文件的函数定义与声明（Node 读取缺陷兜底）。"""
    abs_path = os.path.join(root, path.replace("/", os.sep))
    with open(abs_path, "rb") as fh:
        text = fh.read().decode("utf-8-sig", errors="replace")
    lines = text.split("\n")
    total_lines = len(lines)
    non_empty = len([l for l in lines if l.strip()])

    functions = []
    exports = []
    for i, line in enumerate(lines, start=1):
        m = re.match(
            r"^[A-Za-z_][A-Za-z0-9_ *]*\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^;{]*)\)\s*\{\s*$",
            line,
        )
        if m:
            functions.append(
                {
                    "name": m.group(1),
                    "startLine": i,
                    "endLine": i,
                    "params": [p.strip() for p in m.group(2).split(",") if p.strip()],
                }
            )
            exports.append({"name": m.group(1), "line": i, "isDefault": False})
            continue
        d = re.match(r"^(?:typedef\s+)?(struct|enum)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\{", line)
        if d:
            exports.append({"name": d.group(2), "line": i, "isDefault": False})

    # 函数结束行：下一个函数定义行 - 1（粗粒度区间，仅供定位）
    for idx, fn in enumerate(functions):
        fn["endLine"] = functions[idx + 1]["startLine"] - 1 if idx + 1 < len(functions) else total_lines

    return {
        "path": path,
        "language": "c",
        "fileCategory": "code",
        "totalLines": total_lines,
        "nonEmptyLines": non_empty,
        "functions": functions,
        "classes": [],
        "exports": exports,
        "callGraph": [],
        "metrics": {
            "exportCount": len(exports),
            "functionCount": len(functions),
            "classCount": 0,
        },
    }


def main():
    root = sys.argv[1]
    with open(sys.argv[2], "r", encoding="utf-8") as fh:
        spec = json.load(fh)
    results = []
    skipped = []
    for f in spec["batchFiles"]:
        lang = f.get("language")
        try:
            if lang == "python":
                results.append(extract(f["path"], root))
            elif lang == "c":
                results.append(extract_c(f["path"], root))
        except Exception as exc:  # noqa: BLE001 - 记录跳过原因供上层报告
            skipped.append({"path": f["path"], "reason": type(exc).__name__ + ": " + str(exc)})
    out = {
        "extractor": "cpython-ast",
        "filesAnalyzed": len(results),
        "filesSkipped": skipped,
        "results": results,
    }
    with open(sys.argv[3], "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print(
        "ua-py-extract: analyzed=%d skipped=%d functions=%d classes=%d calls=%d"
        % (
            len(results),
            len(skipped),
            sum(len(r["functions"]) for r in results),
            sum(len(r["classes"]) for r in results),
            sum(len(r["callGraph"]) for r in results),
        )
    )


if __name__ == "__main__":
    main()
