"""导出批次内每个 Python 文件的 docstring，作为图谱摘要的权威依据。

只输出压缩后的文本（模块/类/函数的首段 docstring + 签名 + 行号），
无 docstring 的符号标注 [NO-DOC] 以便按需回读源码。
"""

import ast
import json
import sys
from pathlib import Path

ROOT = Path("e:/codeGIT/pca-mcp-server")
CAP = 420


def clip(text: str) -> str:
    """压平空白并截断。"""
    flat = " ".join(text.split())
    return flat if len(flat) <= CAP else flat[:CAP] + " …"


def doc_of(node) -> str | None:
    doc = ast.get_docstring(node)
    return clip(doc) if doc else None


def dump_file(rel: str) -> None:
    p = ROOT / rel
    try:
        src = p.read_text(encoding="utf-8")
        tree = ast.parse(src)
    except SyntaxError as exc:
        print(f"FILE {rel}  [PARSE-ERROR: {exc}]")
        return
    except OSError as exc:
        print(f"FILE {rel}  [READ-ERROR: {exc}]")
        return

    print(f"FILE {rel}")
    md = doc_of(tree)
    print(f"  MODULE-DOC: {md if md else '[NO-DOC]'}")

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            bases = ", ".join(
                ast.unparse(b) for b in node.bases
            ) or "-"
            methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            d = doc_of(node)
            print(f"  CLASS {node.name} [{node.lineno}-{node.end_lineno}] bases=({bases}) methods=[{', '.join(methods)}]")
            print(f"    DOC: {d if d else '[NO-DOC]'}")
            for m in node.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    dm = doc_of(m)
                    args = ", ".join(a.arg for a in m.args.args)
                    ln = (m.end_lineno or m.lineno) - m.lineno + 1
                    print(f"      METHOD {m.name}({args}) [{m.lineno}-{m.end_lineno}] {ln}L")
                    print(f"        DOC: {dm if dm else '[NO-DOC]'}")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = ", ".join(a.arg for a in node.args.args)
            d = doc_of(node)
            ln = (node.end_lineno or node.lineno) - node.lineno + 1
            decs = ", ".join(ast.unparse(x) for x in node.decorator_list) or "-"
            print(f"  FUNC {node.name}({args}) [{node.lineno}-{node.end_lineno}] {ln}L deco=({decs})")
            print(f"    DOC: {d if d else '[NO-DOC]'}")
        elif isinstance(node, ast.Assign):
            names = ", ".join(
                t.id for t in node.targets if isinstance(t, ast.Name)
            )
            if names and len(names) < 200:
                print(f"  TOP-ASSIGN {names} [{node.lineno}]")
    print()


def main() -> None:
    batch_index = sys.argv[1]
    inp = json.loads(
        (ROOT / f".ua/tmp/ua-file-analyzer-input-{batch_index}.json").read_text(
            encoding="utf-8"
        )
    )
    for f in inp["batchFiles"]:
        if f["language"] == "python":
            dump_file(f["path"])


if __name__ == "__main__":
    main()
