"""用 CPython ast 独立复核 extract-structure 对全部 Python 文件的结构提取。

判定批次产物可信度：逐文件比对 ast 的顶层 def/class 集合与 extract 结果，
并复核 sizeLines 是否为 ast 视角的真实行数（垃圾读取会同时暴露两者不一致）。
"""

import ast
import json
from pathlib import Path

ROOT = Path("e:/codeGIT/pca-mcp-server")

extract = {}
for i in range(1, 11):
    f = ROOT / f".ua/tmp/ua-file-extract-results-{i}.json"
    if not f.exists():
        continue
    data = json.loads(f.read_text(encoding="utf-8"))
    for r in data["results"]:
        extract[r["path"]] = (i, r)

scan = json.loads((ROOT / ".ua/intermediate/scan-result.json").read_text("utf-8"))
py_files = [f for f in scan["files"] if f["language"] == "python"]

agree = 0
problems = []

for f in py_files:
    path, reported_lines = f["path"], f["sizeLines"]
    p = ROOT / path
    try:
        src = p.read_text(encoding="utf-8")
        tree = ast.parse(src)
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        problems.append(f"{path}: ast 无法解析 ({type(exc).__name__})")
        continue

    real_lines = len(src.splitlines())
    ast_fns = sorted(
        n.name for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    ast_cls = sorted(n.name for n in tree.body if isinstance(n, ast.ClassDef))

    entry = extract.get(path)
    if entry is None:
        problems.append(f"{path}: extract 结果缺失（该文件未产出结构条目）")
        continue
    batch, r = entry
    ex_fns = sorted(x["name"] for x in r.get("functions") or [])
    ex_cls = sorted(x["name"] for x in r.get("classes") or [])

    errs = []
    if real_lines != reported_lines:
        errs.append(f"sizeLines={reported_lines} 真实={real_lines}")
    if ast_fns != ex_fns:
        miss = set(ast_fns) - set(ex_fns)
        extra = set(ex_fns) - set(ast_fns)
        if miss or extra or not ast_fns:
            errs.append(
                f"函数不一致 ast={len(ast_fns)} extract={len(ex_fns)}"
                f" 缺={sorted(miss)[:4]} 多={sorted(extra)[:4]}"
            )
    if ast_cls != ex_cls:
        miss = set(ast_cls) - set(ex_cls)
        extra = set(ex_cls) - set(ast_cls)
        if miss or extra:
            errs.append(
                f"类不一致 ast={len(ast_cls)} extract={len(ex_cls)}"
                f" 缺={sorted(miss)[:4]} 多={sorted(extra)[:4]}"
            )
    # ast 补资过的条目带 marker，不算不一致
    if r.get("structureSource") == "cpython-ast-fallback":
        errs = [e for e in errs if "sizeLines" in e]

    if errs:
        problems.append(f"{path} (batch {batch}): " + "; ".join(errs))
    else:
        agree += 1

print(f"Python 文件总数={len(py_files)}  完全一致={agree}  存在问题={len(problems)}")
print()
for line in problems:
    print("  " + line)
