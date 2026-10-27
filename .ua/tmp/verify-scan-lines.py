"""交叉核对 scan-result.json 的 sizeLines 与真实文件行数。

scan-project.mjs 由 Node 读取，本次已发现其对个别文件的读取会损坏；
此脚本用 CPython 独立复核每个文件的行数，报告偏差，用于判定图谱数据可信度。
"""

import json
import sys
from pathlib import Path

ROOT = Path("e:/codeGIT/pca-mcp-server")

scan = json.loads((ROOT / ".ua/intermediate/scan-result.json").read_text("utf-8"))

mismatches = []
unreadable = []
checked = 0

for f in scan["files"]:
    p = ROOT / f["path"]
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        unreadable.append((f["path"], f["sizeLines"], type(exc).__name__))
        continue
    checked += 1
    real = len(text.splitlines())
    reported = f["sizeLines"]
    if reported == 0:
        if real:
            mismatches.append((f["path"], reported, real, "reported-zero"))
        continue
    drift = abs(real - reported) / max(real, 1)
    if drift > 0.02 and abs(real - reported) > 3:
        mismatches.append((f["path"], reported, real, f"drift={drift:.0%}"))

print(f"checked={checked}/{len(scan['files'])}  files")
print(f"mismatches={len(mismatches)}  unreadable={len(unreadable)}")
if mismatches:
    print("\n--- sizeLines 与真实行数不一致 ---")
    for path, rep, real, why in sorted(mismatches, key=lambda x: -abs(x[2] - x[1])):
        print(f"  {path}: reported={rep} real={real} ({why})")
if unreadable:
    print("\n--- CPython 无法读取/解码 ---")
    for path, rep, why in unreadable:
        print(f"  {path}: reported={rep} ({why})")
